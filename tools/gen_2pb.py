#!/usr/bin/env python3
"""Generate the hole-level SVG for the two-breadboard build.

Single source of truth for the drawing inside `docs/wiring_dos_protoboards.html`:
the script rewrites whatever sits between the SVG:START / SVG:END markers, so
editing the SVG by hand in the HTML is lost on the next run — change the layout
here instead.

    ./.venv/bin/python tools/gen_2pb.py

Two boards, drawn as real 830-point breadboards (63 columns, rows A-E / F-J, a
centre channel and two power-rail pairs each):

  A  sensing   — ADS1115, the 10k/22k divider, the DS18B20 and the transducer
  B  control   — IRLZ44N and its gate network, nothing else

Layout decisions worth keeping when this is edited:

* **5 V never reaches a rail.** Only the transducer needs it, so it arrives as a
  single jumper from header pin 2 into that one column. Putting 3.3 V and 5 V on
  neighbouring rails of the same board is the exact off-by-one that can back-feed
  the 3.3 V rail, and this rig has already lost one Pi to a shorted 3.3 V rail.
* **No 12 V anywhere on either board.** The coil path is off-board wire.
* **Ground enters the breadboard system once**, at header pin 9 (pins 6 and 14
  are damaged on this board), and the two boards' - rails are bridged to each
  other rather than each running to the star screw.
* The MOSFET's drain and source get **dedicated wires in their own columns** and
  the source goes straight to the star screw, so the 1.08 A coil return never
  travels a rail.
"""
from __future__ import annotations

import pathlib
import re

# ---------------------------------------------------------------- geometry ---
NCOL = 63
COL0 = 90.0          # x of column 1
PITCH = 14.5         # column pitch
BW, BX = 940.0, 70.0  # board rect width / x

# row offsets measured from the board's top edge
R_RAIL_TP, R_RAIL_TM = 14.0, 32.0     # top rails: + then -
ROWS_TOP = {"A": 100.0, "B": 118.0, "C": 136.0, "D": 154.0, "E": 172.0}
CH_Y, CH_H = 186.0, 34.0              # centre channel
ROWS_BOT = {"F": 234.0, "G": 252.0, "H": 270.0, "I": 288.0, "J": 306.0}
R_RAIL_BM, R_RAIL_BP = 340.0, 358.0   # bottom rails: - then +
BH = 378.0                            # board height

BOARD_A_Y = 200.0
BOARD_B_Y = 720.0

ROWS = {**ROWS_TOP, **ROWS_BOT}


def cx(col: int) -> float:
    return COL0 + (col - 1) * PITCH


def cy(board_y: float, row: str) -> float:
    return board_y + ROWS[row]


def rail_y(board_y: float, which: str) -> float:
    return board_y + {"tp": R_RAIL_TP, "tm": R_RAIL_TM,
                      "bm": R_RAIL_BM, "bp": R_RAIL_BP}[which]


# ------------------------------------------------------------------ pieces ---
def esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def txt(x, y, s, size=11, fill="currentColor", anchor="start",
        weight=None, op=None, rot=None):
    a = [f'x="{x:.1f}"', f'y="{y:.1f}"', f'font-size="{size}"', f'fill="{fill}"']
    if anchor != "start":
        a.append(f'text-anchor="{anchor}"')
    if weight:
        a.append(f'font-weight="{weight}"')
    if op is not None:
        a.append(f'opacity="{op}"')
    if rot is not None:
        a.append(f'transform="rotate({rot} {x:.1f} {y:.1f})"')
    return f'<text {" ".join(a)}>{esc(s)}</text>'


def board(y: float, title: str, colour: str, subtitle: str) -> list[str]:
    """The empty breadboard: body, channel, rails, holes, column numbers."""
    o: list[str] = []
    o.append(f'<rect x="{BX}" y="{y}" width="{BW}" height="{BH}" rx="10" '
             f'fill="currentColor" fill-opacity=".045" stroke="{colour}" '
             f'stroke-width="1.8" stroke-opacity=".55"/>')
    # centre channel
    o.append(f'<rect x="{BX + 8}" y="{y + CH_Y}" width="{BW - 16}" height="{CH_H}" '
             f'fill="currentColor" fill-opacity=".07"/>')
    # rail stripes
    for w, col, lab in (("tp", "var(--ok)", "+ 3.3 V"), ("tm", "var(--gnd)", "- GND"),
                        ("bm", "var(--gnd)", "- GND"), ("bp", "var(--off)", "+ sin usar")):
        ry = rail_y(y, w)
        o.append(f'<line x1="{BX + 12}" y1="{ry}" x2="{BX + BW - 12}" y2="{ry}" '
                 f'stroke="{col}" stroke-width="2.4" stroke-opacity=".35"/>')
        o.append(txt(BX - 6, ry + 4, lab, 10.5, fill=col, anchor="end", weight="500"))
    # holes
    for c in range(1, NCOL + 1):
        x = cx(c)
        for w in ("tp", "tm", "bm", "bp"):
            o.append(f'<circle cx="{x:.1f}" cy="{rail_y(y, w):.1f}" r="2.6" '
                     f'fill="none" stroke="currentColor" stroke-opacity=".28"/>')
        for r in ROWS:
            o.append(f'<circle cx="{x:.1f}" cy="{cy(y, r):.1f}" r="2.6" '
                     f'fill="none" stroke="currentColor" stroke-opacity=".28"/>')
    # column numbers every 5, in the channel
    for c in range(1, NCOL + 1, 5):
        o.append(txt(cx(c), y + CH_Y + 22, str(c), 10, anchor="middle", op=".45"))
    # row letters
    for r, off in ROWS.items():
        o.append(txt(BX - 6, y + off + 4, r, 10, anchor="end", op=".45"))
    # title
    o.append(txt(BX, y - 30, title, 15, fill=colour, weight="500"))
    o.append(txt(BX, y - 13, subtitle, 11.5, op=".62"))
    return o


def leg(x, y, col="var(--act)"):
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.2" fill="{col}"/>'


def resistor(by, row, c1, c2, label, sub=""):
    """A resistor lying across two columns of the same row."""
    o = []
    x1, x2, y = cx(c1), cx(c2), cy(by, row)
    o.append(f'<line x1="{x1:.1f}" y1="{y:.1f}" x2="{x2:.1f}" y2="{y:.1f}" '
             f'stroke="var(--res)" stroke-width="1.8"/>')
    mx = (x1 + x2) / 2
    w = max(abs(x2 - x1) - 12, 16)
    o.append(f'<rect x="{mx - w / 2:.1f}" y="{y - 6:.1f}" width="{w:.1f}" height="12" '
             f'rx="3" fill="var(--res)" fill-opacity=".28" stroke="var(--res)" '
             f'stroke-width="1.3"/>')
    o.append(leg(x1, y, "var(--res)"))
    o.append(leg(x2, y, "var(--res)"))
    o.append(txt(mx, y - 12, label, 10.5, fill="var(--res)", anchor="middle", weight="500"))
    return o


def module(by, row, c1, n, name, pins, colour="var(--dat)"):
    """A single-row breakout: n pins starting at column c1, in `row`."""
    o = []
    y = cy(by, row)
    x1, x2 = cx(c1), cx(c1 + n - 1)
    o.append(f'<rect x="{x1 - 8:.1f}" y="{y - 26:.1f}" width="{x2 - x1 + 16:.1f}" '
             f'height="22" rx="4" fill="{colour}" fill-opacity=".16" '
             f'stroke="{colour}" stroke-width="1.4"/>')
    o.append(txt((x1 + x2) / 2, y - 11, name, 11, fill=colour, anchor="middle", weight="500"))
    for i, p in enumerate(pins):
        o.append(leg(cx(c1 + i), y, colour))
        o.append(txt(cx(c1 + i), y - 32, p, 9.5, fill=colour, anchor="middle", rot=-90))
    return o


def wire(pts, colour, width=2.0, dash=None, label=None, lx=None, ly=None):
    d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts)
    a = f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="{width}" ' \
        f'stroke-linecap="round" stroke-linejoin="round"'
    if dash:
        a += f' stroke-dasharray="{dash}"'
    o = [a + "/>"]
    if label:
        o.append(txt(lx, ly, label, 10, fill=colour, anchor="middle", weight="500"))
    return o


# -------------------------------------------------------------------- draw ---
def descr(by, col, lines, colour):
    """Component caption parked in the empty bottom half, with a leader line."""
    o = [f'<line x1="{cx(col):.1f}" y1="{cy(by, "E") + 8:.1f}" '
         f'x2="{cx(col):.1f}" y2="{cy(by, "F") - 6:.1f}" stroke="{colour}" '
         f'stroke-width="1" stroke-dasharray="2 3" stroke-opacity=".7"/>']
    for k, ln in enumerate(lines):
        o.append(txt(cx(col), cy(by, "F") + 6 + k * 14, ln, 10,
                     fill=colour if k == 0 else "currentColor",
                     anchor="middle", weight="500" if k == 0 else None,
                     op=None if k == 0 else ".62"))
    return o


def build() -> str:
    o: list[str] = []
    W, HA, HB = 1120, 700, 620
    o.append(f'<svg viewBox="0 0 {W} {HA}" xmlns="http://www.w3.org/2000/svg" role="img" '
             f'aria-label="Protoboard A de sensado: ADS1115 en las columnas 2 a 11, '
             f'divisor en 18 a 24, sonda en 31 a 33 y transductor en 45 a 47">')

    A, B = BOARD_A_Y, 150.0

    # ---------------- header ----------------
    hy = 26.0
    o.append(f'<rect x="{BX}" y="{hy}" width="{BW}" height="76" rx="8" fill="none" '
             f'stroke="currentColor" stroke-width="1.4" stroke-opacity=".45"/>')
    o.append(txt(BX + 14, hy + 20, "RASPBERRY PI 4 — header de 40 pines", 12.5, weight="500"))
    pins = [("1", "3.3 V", "var(--ok)"), ("2", "5 V", "var(--pwr)"),
            ("3", "SDA", "var(--dat)"), ("5", "SCL", "var(--dat)"),
            ("7", "GPIO4", "var(--sig)"), ("9", "GND", "var(--gnd)"),
            ("12", "GPIO18", "var(--sig)"), ("16", "GPIO23", "var(--act)"),
            ("6", "GND", "var(--bad)"), ("14", "GND", "var(--bad)")]
    px = {}
    for i, (pn, nm, c) in enumerate(pins):
        x = BX + 60 + i * 92
        px[pn] = x
        o.append(txt(x, hy + 46, f"pin {pn}", 11, fill=c, anchor="middle", weight="500"))
        o.append(txt(x, hy + 61, nm, 10, fill=c, anchor="middle", op=".85"))
    o.append(txt((px["6"] + px["14"]) / 2, hy + 74, "DAÑADOS — no metas cable", 9.5,
                 fill="var(--bad)", anchor="middle", weight="500"))
    o.append(txt(px["12"], hy + 74, "directo al servo,", 9, fill="var(--sig)", anchor="middle", op=".8"))
    o.append(txt(px["12"], hy + 86, "no toca protoboard", 9, fill="var(--sig)", anchor="middle", op=".8"))
    o.append(txt(px["16"], hy + 74, "va a la placa B", 9, fill="var(--act)", anchor="middle", op=".8"))

    # ---------------- board A ----------------
    o += board(A, "PROTOBOARD A — sensado",
               "var(--ok)", "3.3 V y 5 V · µA-mA · nada que conmute")

    o += module(A, "E", 2, 10, "ADS1115",
                ["VDD", "GND", "SCL", "SDA", "ADDR", "ALRT", "A0", "A1", "A2", "A3"])
    o += descr(A, 6, ["ADS1115 HiLetgo · cols 2-11",
                      "una tira de 10 pines,", "no cruza el canal"], "var(--dat)")

    o += resistor(A, "B", 18, 21, "R1 10k")
    # R2 on row C so column 21 shows two holes: R1's leg (row B) and
    # R2's leg (row C) share the NODE, never the hole.
    o += resistor(A, "C", 21, 24, "R2 22k")
    o += descr(A, 21, ["Divisor 10k/22k, kit 1 % · cols 18-24",
                       "col 21 es el NODO", "ratio 0.6875"], "var(--res)")

    o += module(A, "B", 31, 3, "DS18B20", ["ROJO", "AMAR", "NEGRO"], "var(--sig)")
    # Pull-up: DATA (col 32) to VDD (col 34, jumpered to the 3.3 V rail below).
    # NOT 31->33: those are VDD and GND, and a resistor there is a 0.7 mA heater
    # that leaves the 1-Wire line floating. The pull-up IS the bus's idle high.
    o += resistor(A, "D", 32, 34, "4.7k")
    o += wire([(cx(34), cy(A, "D")), (cx(34), cy(A, "A") - 12), (cx(37), cy(A, "A") - 12),
               (cx(37), rail_y(A, "tp"))], "var(--ok)", 1.5)
    o += descr(A, 32, ["Sonda DS18B20 · cols 31-33",
                       "4.7k: col 32 (AMAR) → col 34 → 3.3 V",
                       "NUNCA de rojo a negro"], "var(--sig)")

    o += module(A, "B", 45, 3, "TRANSDUCTOR", ["ROJO", "VERDE", "NEGRO"], "var(--pwr)")
    o += descr(A, 46, ["Transductor 0-15 PSI 0.5-4.5 V · cols 45-47",
                       "ROJO = 5 V del pin 2", "rojo y negro NO se cambian"], "var(--pwr)")

    ra_p, ra_m = rail_y(A, "tp"), rail_y(A, "tm")
    GN, OK, PW, DT, SG = ("var(--gnd)", "var(--ok)", "var(--pwr)",
                          "var(--dat)", "var(--sig)")

    # ADS1115: VDD, GND, ADDR
    o += wire([(cx(2), cy(A, "E")), (cx(2), cy(A, "A") - 46), (cx(2) - 12, cy(A, "A") - 46),
               (cx(2) - 12, ra_p), (cx(2), ra_p)], OK, 1.8)
    o += wire([(cx(3), cy(A, "E")), (cx(3), ra_m)], GN, 1.8)
    o += wire([(cx(6), cy(A, "E")), (cx(6), cy(A, "C")), (cx(14), cy(A, "C")),
               (cx(14), ra_m)], GN, 1.5)
    o.append(txt(cx(10), cy(A, "C") - 5, "ADDR → GND = 0x48", 9.5, fill=GN, anchor="middle"))

    # divider node -> A0  (routed through the empty bottom half)
    o += wire([(cx(21), cy(A, "B")), (cx(21), cy(A, "A") - 24), (cx(8), cy(A, "A") - 24),
               (cx(8), cy(A, "E"))], DT, 2.2)
    o.append(txt(cx(15), cy(A, "A") - 29, "nodo (col 21) → A0 (col 8)", 10,
                 fill=DT, anchor="middle", weight="500"))
    o += wire([(cx(24), cy(A, "C")), (cx(24), cy(A, "D")), (cx(27), cy(A, "D")),
               (cx(27), ra_m)], GN, 1.5)

    # transducer green -> R1
    o += wire([(cx(46), cy(A, "B")), (cx(46), cy(A, "A") - 38), (cx(18), cy(A, "A") - 38),
               (cx(18), cy(A, "B"))], DT, 2.2)
    o.append(txt(cx(32), cy(A, "A") - 43, "VERDE (col 46) → R1 (col 18)", 10,
                 fill=DT, anchor="middle", weight="500"))

    # probe / transducer power and grounds
    o += wire([(cx(31), cy(A, "B")), (cx(31), cy(A, "A") - 12), (cx(29), cy(A, "A") - 12),
               (cx(29), ra_p)], OK, 1.5)
    o += wire([(cx(33), cy(A, "B")), (cx(33), cy(A, "C")), (cx(39), cy(A, "C")),
               (cx(39), ra_m)], GN, 1.5)
    o += wire([(cx(47), cy(A, "B")), (cx(47), cy(A, "C")), (cx(50), cy(A, "C")),
               (cx(50), ra_m)], GN, 1.5)

    # header -> board A
    o += wire([(px["1"], hy + 76), (px["1"], A - 52), (cx(2) - 12, A - 52),
               (cx(2) - 12, ra_p)], OK, 2.0, dash="5 3")
    o += wire([(px["9"], hy + 76), (px["9"], A - 40), (cx(41), A - 40),
               (cx(41), ra_m)], GN, 2.6, dash="5 3")
    o.append(txt(cx(41) + 8, A - 44, "pin 9 → riel −  (ÚNICA entrada de tierra)", 10,
                 fill=GN, weight="500"))
    o += wire([(px["3"], hy + 76), (px["3"], A - 62), (cx(5), A - 62),
               (cx(5), cy(A, "E"))], DT, 1.8, dash="5 3")
    o += wire([(px["5"], hy + 76), (px["5"], A - 74), (cx(4), A - 74),
               (cx(4), cy(A, "E"))], DT, 1.8, dash="5 3")
    o += wire([(px["7"], hy + 76), (px["7"], A - 28), (cx(32), A - 28),
               (cx(32), cy(A, "B"))], SG, 1.8, dash="5 3")
    o += wire([(px["2"], hy + 76), (px["2"], A - 88), (cx(45), A - 88),
               (cx(45), cy(A, "B"))], PW, 2.6, dash="5 3")
    o.append(txt(cx(45) + 8, A - 92, "5 V ← pin 2 · UN SOLO HOYO, nunca a un riel", 10.5,
                 fill=PW, weight="500"))

    # rails of board A bridged
    o += wire([(cx(63) + 16, ra_m), (cx(63) + 30, ra_m), (cx(63) + 30, rail_y(A, "bm")),
               (cx(63) + 16, rail_y(A, "bm"))], GN, 1.8, dash="4 3")

    o.append(txt(W / 2, HA - 14,
                 "Si por un cable pasan más de ~1 A, ese cable no toca el protoboard.",
                 11.5, anchor="middle", op=".65"))
    o.append("</svg>")

    # ---------------- board B, hoja aparte ----------------
    o.append(f'<svg viewBox="0 0 {W} {HB}" xmlns="http://www.w3.org/2000/svg" role="img" '
             f'aria-label="Protoboard B de control: IRLZ44N en las columnas 5 a 7 con '
             f'su red de compuerta">')
    o += board(B, "PROTOBOARD B — control",
               "var(--act)", "compuerta (µA) + zona del V1738 · 12 V solo en las columnas del V1738")

    o += module(B, "E", 5, 3, "IRLZ44N", ["G", "D", "S"], "var(--act)")
    o += resistor(B, "C", 2, 5, "470 Ω")
    o += resistor(B, "A", 5, 8, "10k")
    o += descr(B, 6, ["IRLZ44N (el MOSFET) · cols 5-7",
                      "de frente y parado: G · D · S", "la aleta es el DRAIN"], "var(--act)")
    o += descr(B, 28, ["470 Ω  cols 2→5 · compuerta",
                       "10k  cols 5→8 · a GND",
                       "3.3/470 = 7 mA < 8 mA del Pi 4"], "var(--res)")

    rb_m = rail_y(B, "tm")
    o += wire([(cx(8), cy(B, "A")), (cx(8), cy(B, "A") - 26), (cx(11), cy(B, "A") - 26),
               (cx(11), rb_m)], GN, 1.5)
    # NO jumper G->10k->470R: they already share column 5 (one node, three holes).
    o += wire([(cx(2), 40.0), (cx(2), cy(B, "C"))], "var(--act)", 2.0, dash="5 3")
    o.append(txt(cx(2) + 10, 44.0, "← pin 16 del header (GPIO23) → 470 Ω → compuerta", 11,
                 fill="var(--act)", weight="500"))

    # drain / source leave the board through the empty bottom half
    o += wire([(cx(6), cy(B, "E")), (cx(6), cy(B, "I")), (cx(30), cy(B, "I"))], PW, 2.8)
    o.append(txt(cx(31), cy(B, "I") + 4,
                 "D → bobina − del solenoide 231Y-6-12VDC   (1.08 A)", 11, fill=PW, weight="500"))
    o += wire([(cx(7), cy(B, "E")), (cx(7), cy(B, "J")), (cx(30), cy(B, "J"))],
              "var(--bad)", 2.8)
    o.append(txt(cx(31), cy(B, "J") + 4,
                 "S → cable directo al TORNILLO ESTRELLA   (1.08 A de retorno)", 11,
                 fill="var(--bad)", weight="500"))
    o.append(txt(cx(31), cy(B, "J") + 20,
                 "ninguno de los dos toca un riel, y nada más se planta en esas columnas",
                 9.5, op=".62"))

    # V1738 reserved zone: NOT drawn into specific columns because its pitch is
    # unmeasured (Stage 0.6). 5.08 mm straddles alternating columns and plants;
    # 3.5/3.81 mm does not fit the 0.1" grid and stays off-board in the harness.
    zx1, zx2 = cx(40) - 10, cx(58) + 10
    zy1, zy2 = cy(B, "F") - 18, cy(B, "H") + 14
    o.append(f'<rect x="{zx1:.1f}" y="{zy1:.1f}" width="{zx2 - zx1:.1f}" '
             f'height="{zy2 - zy1:.1f}" rx="7" fill="var(--pwr)" fill-opacity=".05" '
             f'stroke="var(--pwr)" stroke-width="1.6" stroke-dasharray="7 4"/>')
    zmx = (zx1 + zx2) / 2
    o.append(txt(zmx, zy1 + 16, "ZONA V1738 — plug de la bobina del 231Y-6-12VDC", 10.5,
                 fill="var(--pwr)", anchor="middle", weight="500"))
    o.append(txt(zmx, zy1 + 31, "plantar aquí SOLO si su pitch mide 5.08 mm (Stage 0.6)", 9.5,
                 anchor="middle", op=".75"))
    o.append(txt(zmx, zy1 + 45, "polo 1 ← +12 V del fusible · polo 2 → drain · polo 3 MUERTO (llave)", 9.5,
                 anchor="middle", op=".75"))
    o.append(txt(zmx, zy1 + 59, "si mide 3.5/3.81 mm NO entra al grid: se queda fuera, en el arnés", 9.5,
                 anchor="middle", op=".75"))

    # el riel − de B se puentea al de A: una sola entrada de tierra en todo el sistema
    o += wire([(cx(63) + 16, rb_m), (cx(63) + 30, rb_m), (cx(63) + 30, rb_m - 46),
               (cx(52), rb_m - 46)], GN, 2.2)
    o.append(txt(cx(51), rb_m - 50, "→ riel − de la placa A", 10.5,
                 fill=GN, anchor="end", weight="500"))
    o.append(txt(cx(51), rb_m - 36, "B nunca toca el tornillo estrella", 9.5,
                 anchor="end", op=".62"))

    o.append(txt(W / 2, HB - 14,
                 "Si el V1738 se planta aquí, los 12 V viven SOLO en sus dos columnas — jamás en un riel.",
                 11.5, anchor="middle", op=".65"))
    o.append("</svg>")
    return "\n".join(o)


def main() -> None:
    root = pathlib.Path(__file__).resolve().parent.parent
    sheet = root / "docs" / "wiring_dos_protoboards.html"
    svg = build()
    s = sheet.read_text()
    new, n = re.subn(r"(?s)(<!--SVG:START-->).*?(<!--SVG:END-->)",
                     lambda m: m.group(1) + "\n" + svg + "\n" + m.group(2), s)
    if not n:
        raise SystemExit("no encontré los marcadores SVG:START / SVG:END en la hoja")
    sheet.write_text(new)
    print(f"  ✓ {sheet.relative_to(root)}: SVG regenerado ({len(svg)} bytes)")


if __name__ == "__main__":
    main()
