"""Generate the workshop wiring diagram (docs/wiring_diagram.png).

Audience: Adrian, building the rig by stages while the remaining parts ship.
NOT an EE schematic — plain labels, colour-coded by "have it" vs "missing",
with the do-NOT-do rules and the reason for each one spelled out.

Single source of truth for the picture — edit and re-run:
    ./.venv/bin/python tools/gen_wiring.py

Wiring facts must stay in sync with docs/ASSEMBLY.md ("Wiring" table) and the
sensor/valve/diverter/temperature blocks of config.yaml.
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")

INK = "#1a1a1a"
MUTED = "#5b5b5b"
SIG = "#8a6d00"      # sensing chain
CTRL = "#7a2f2f"     # actuators
PWR = "#1f5e8b"      # power
BAD = "#b3261e"      # prohibitions
GOOD = "#1e7d32"     # have it

HAVE_FC, HAVE_EC = "#e6f4ea", GOOD
MISS_FC, MISS_EC = "#fdecec", "#c0392b"

DASH = (0, (4, 2))


def box(ax, x, y, w, h, text, fc="white", ec=INK, fs=8.5, lw=1.2, weight="normal"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.25",
                                fc=fc, ec=ec, lw=lw, zorder=2))
    if text:
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                fontsize=fs, color=INK, linespacing=1.45, zorder=3, weight=weight)


def arrow(ax, p0, p1, color=INK, ls="-", lw=1.5):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=12,
                                 color=color, ls=ls, lw=lw, shrinkA=1, shrinkB=1,
                                 zorder=4))


def label(ax, x, y, text, color=MUTED, fs=7.6, ha="center", va="center", weight="normal"):
    ax.text(x, y, text, ha=ha, va=va, fontsize=fs, color=color,
            linespacing=1.4, zorder=5, weight=weight)


def section(ax, x, y, text, color):
    label(ax, x, y, text, color, 9.8, ha="left", weight="bold")


fig, ax = plt.subplots(figsize=(20, 13.4))
ax.set_xlim(0, 200)
ax.set_ylim(0, 134)
ax.axis("off")
fig.patch.set_facecolor("white")

# ============================================================ title
label(ax, 3, 130.5, "Membrane Rig  —  Diagrama de conexión", INK, 20, ha="left", weight="bold")
label(ax, 3, 126.3,
      "Guía de armado por etapas. Los colores dicen qué YA tienes y qué falta. "
      "Nada de lo que está aquí requiere energizar el servo.",
      MUTED, 10.5, ha="left")

box(ax, 150, 124.4, 9, 4.2, "", HAVE_FC, HAVE_EC)
label(ax, 160.5, 126.5, "ya lo tienes", INK, 9.5, ha="left")
box(ax, 176, 124.4, 9, 4.2, "", MISS_FC, MISS_EC)
label(ax, 186.5, 126.5, "falta comprar", INK, 9.5, ha="left")

# ============================================================ servo warning band
ax.add_patch(FancyBboxPatch((3, 111.5), 194, 11.0, boxstyle="round,pad=0.3",
                            fc="#fff4e5", ec="#e07b00", lw=2.2, zorder=2))
label(ax, 6, 119.6,
      "⚠   NO energices ni muevas el servo todavía  —  esa etapa quedó fuera de este diagrama a propósito",
      "#8a4b00", 12.5, ha="left", weight="bold")
label(ax, 6, 115.9,
      "En cuanto el software arranca en modo hardware, el servo se va solo a 700 µs. Si para entonces ya está acoplado al vástago, puede forzar la válvula contra su tope.",
      "#8a4b00", 9.3, ha="left")
label(ax, 6, 113.2,
      "Además servo_close_us sigue en 0 = sin calibrar.   Cuando toque:  (1) DESACOPLA el servo del vástago   (2) verifica el extremo de 700 µs contra el tope físico   (3) recién ahí acoplas.",
      "#8a4b00", 9.3, ha="left")

# ============================================================ DIAGRAM (left)
label(ax, 3, 106.5, "CÓMO SE CONECTA", INK, 13, ha="left", weight="bold")

# --- Raspberry Pi
box(ax, 4, 31, 23, 71, "", "#f2f6fa", PWR, lw=1.8)
label(ax, 15.5, 99.0, "Raspberry Pi 4", INK, 12, weight="bold")
label(ax, 15.5, 96.0, "(ya lo tienes)", GOOD, 8.4)

pins = [
    ("5V   (pin 2)", 90.0),
    ("3.3V (pin 1)", 86.0),
    ("GPIO2 / GPIO3", 82.0),
    ("GPIO4", 71.0),
    ("GPIO18", 57.0),
    ("GPIO23", 43.0),
    ("GND  (varios)", 34.0),
]
for name, yy in pins:
    label(ax, 25.6, yy, name, INK, 9.2, ha="right", weight="bold")
    ax.plot([26, 28.5], [yy, yy], color=MUTED, lw=1.2, zorder=3)

# ---------------------------------------------------------- ROW 1: sensing
section(ax, 29, 101.5, "CADENA DE PRESIÓN", SIG)
box(ax, 38, 85.5, 21, 9, "Transductor\n0–15 PSI · 0.5–4.5 V", MISS_FC, MISS_EC, 8.6)
box(ax, 65, 85.5, 21, 9, "Divisor\nR1 10k  +  R2 20k", HAVE_FC, HAVE_EC, 8.6)
box(ax, 92, 85.5, 24, 9, "ADS1115  (HiLetgo)\nA0 · ADDR→GND · 0x48", HAVE_FC, HAVE_EC, 8.6)

arrow(ax, (28.5, 90.0), (38, 90.0), PWR)
label(ax, 33.2, 91.6, "5 V", PWR, 7.8)
arrow(ax, (59, 90.0), (65, 90.0), SIG)
label(ax, 62, 92.0, "0.5–4.5 V", SIG, 7.4)
arrow(ax, (86, 90.0), (92, 90.0), SIG)
label(ax, 89, 92.0, "0–3.0 V", SIG, 7.4)
label(ax, 75.5, 83.0, "4.5 V × 0.667 = 3.0 V  →  así ya cabe en el ADC sin quemarlo", SIG, 7.7)

# I2C + 3.3V
arrow(ax, (28.5, 82.0), (104, 82.0), SIG, ls=DASH)
ax.plot([104, 104], [82, 85.5], color=SIG, lw=1.5, ls=DASH, zorder=3)
label(ax, 62, 80.0, "I²C  SDA/SCL  (datos)", SIG, 7.8)
ax.plot([28.5, 118], [86.0, 86.0], color=PWR, lw=1.2, ls=(0, (1, 2.4)), zorder=1)
label(ax, 121, 86.0, "3.3 V alimenta el ADS1115\ny el pull-up de la sonda", PWR, 7.6, ha="left")

# ---------------------------------------------------------- ROW 2: temperature
section(ax, 29, 76.5, "TEMPERATURA DEL AGUA", SIG)
box(ax, 38, 66.5, 25, 7.5, "DS18B20 (sonda 1-Wire)", MISS_FC, MISS_EC, 8.6)
box(ax, 69, 66.5, 23, 7.5, "Pull-up 4.7k → 3.3 V", HAVE_FC, HAVE_EC, 8.6)
arrow(ax, (28.5, 71.0), (38, 71.0), SIG)
label(ax, 33.2, 69.2, "dato", SIG, 7.4)
ax.plot([63, 69], [70.2, 70.2], color=SIG, lw=1.5, zorder=3)
label(ax, 66, 64.2, "sin el pull-up la sonda no responde   ·   hay que habilitar 1-Wire y reiniciar el Pi", MUTED, 7.5, ha="left")

# ---------------------------------------------------------- ROW 3: servo
section(ax, 29, 62.0, "SERVO   (solo cableado — NO energizar)", CTRL)
box(ax, 38, 52.5, 21, 7.5, "Servo DS3218", HAVE_FC, HAVE_EC, 8.6)
box(ax, 69, 52.5, 23, 7.5, "UBEC 12V→6V  3 A", HAVE_FC, HAVE_EC, 8.6)
arrow(ax, (28.5, 57.0), (38, 57.0), CTRL)
label(ax, 33.2, 55.2, "señal", CTRL, 7.4)
arrow(ax, (69, 55.0), (59, 55.0), CTRL)
label(ax, 64, 50.2, "6 V  ·  alimentación", CTRL, 7.5)
label(ax, 96, 56.2, "✗  la corriente del servo NUNCA sale del Pi", BAD, 8.6, ha="left", weight="bold")

# ---------------------------------------------------------- ROW 4: diverter
section(ax, 29, 48.0, "DIVERTER   (solenoide de 3 vías)", CTRL)
box(ax, 38, 38.0, 19, 8, "220 Ω serie\n+ 10k a GND", HAVE_FC, HAVE_EC, 8.4)
box(ax, 62, 38.0, 18, 8, "MOSFET\nIRLZ44N", MISS_FC, MISS_EC, 8.6)
box(ax, 85, 38.0, 21, 8, "Solenoide 3 vías\n12 V (agua)", MISS_FC, MISS_EC, 8.6)
box(ax, 111, 38.0, 19, 8, "Diodo 1N5819\n(flyback)", MISS_FC, MISS_EC, 8.4)
arrow(ax, (28.5, 43.0), (38, 43.0), CTRL)
label(ax, 33.2, 41.2, "señal", CTRL, 7.4)
arrow(ax, (57, 42.0), (62, 42.0), CTRL)
arrow(ax, (80, 42.0), (85, 42.0), CTRL)
arrow(ax, (106, 42.0), (111, 42.0), CTRL, ls=(0, (3, 2)))
label(ax, 38, 36.6, "sin corriente = permeado va a desecho  ·  así debe quedar al apagar", GOOD, 7.8, ha="left")
label(ax, 120.5, 36.6, "en paralelo a la bobina", MUTED, 7.4)

# ---------------------------------------------------------- ROW 5: power
section(ax, 29, 32.0, "ALIMENTACIÓN", PWR)
box(ax, 38, 22.0, 19, 7.5, "Fuente 12 V 3 A", MISS_FC, MISS_EC, 8.6)
box(ax, 62, 22.0, 18, 7.5, "Fusible 3 A", MISS_FC, MISS_EC, 8.6)
box(ax, 85, 22.0, 21, 7.5, "Riel 12 V\n(protoboard)", MISS_FC, MISS_EC, 8.4)
arrow(ax, (57, 25.7), (62, 25.7), PWR)
arrow(ax, (80, 25.7), (85, 25.7), PWR)
label(ax, 110, 26.5,
      "Del riel de 12 V salen DOS cosas:\n→ el UBEC (que alimenta el servo)\n→ el + de la solenoide",
      PWR, 8.0, ha="left")

# ---------------------------------------------------------- GND bus
ax.plot([6, 140], [17.0, 17.0], color=INK, lw=3.4, zorder=3)
for xx in [15, 47, 71, 95, 120]:
    ax.plot([xx, xx], [17.0, 19.2], color=INK, lw=1.6, zorder=3)
label(ax, 6, 14.3,
      "TIERRA COMÚN (GND)  —  Pi  +  fuente de 12 V  +  UBEC  +  sensores  +  servo:  TODO se une a esta barra",
      INK, 9.6, ha="left", weight="bold")

# ============================================================ RIGHT COLUMN
COLX = 145

label(ax, COLX, 106.5, "INVENTARIO", INK, 13, ha="left", weight="bold")
box(ax, COLX, 84.0, 52, 18.5, "", HAVE_FC, HAVE_EC, lw=1.6)
label(ax, COLX + 2.5, 100.0, "✓   YA TIENES", GOOD, 10.4, ha="left", weight="bold")
label(ax, COLX + 2.5, 91.6,
      "Raspberry Pi 4 + microSD\n"
      "Servo DS3218\n"
      "UBEC 12V→6V 3 A\n"
      "ADS1115 (HiLetgo)\n"
      "Kit de resistencias 1 %\n"
      "Válvula de bola, probeta, manómetro",
      INK, 8.8, ha="left", va="center")

box(ax, COLX, 59.5, 52, 21.5, "", MISS_FC, MISS_EC, lw=1.6)
label(ax, COLX + 2.5, 78.5, "✗   FALTA", "#c0392b", 10.4, ha="left", weight="bold")
label(ax, COLX + 2.5, 69.0,
      "Transductor de presión 0–15 PSI\n"
      "Fuente 12 V 3 A  +  fusible 3 A\n"
      "MOSFET IRLZ44N\n"
      "Diodo 1N5819 (flyback)\n"
      "Protoboard + jumpers\n"
      "Sonda DS18B20\n"
      "Solenoide 3 vías de agua (~$53)",
      INK, 8.8, ha="left", va="center")
label(ax, COLX, 56.8, "Si ya tienes alguno de los de abajo, dime y lo actualizo.", MUTED, 7.8, ha="left")

label(ax, COLX, 51.5, "LO QUE NO HAY QUE HACER", BAD, 13, ha="left", weight="bold")
rules = [
    ("Servo al riel de 5 V del Pi",
     "jala picos de ~2 A y el Pi se reinicia solo  →  aliméntalo del UBEC"),
    ("Transductor directo al ADS1115",
     "el ADC vive a 3.3 V y la señal llega a 4.5 V: lo quemas  →  divisor 10k/20k primero"),
    ("Tierras separadas",
     "sin GND común las lecturas flotan y el MOSFET no conmuta bien  →  une TODOS los GND"),
    ("Solenoide sin diodo flyback",
     "al cortar, la bobina devuelve un pico inverso que mata el MOSFET  →  1N5819 en la bobina"),
    ("Dejar la compuerta del MOSFET al aire",
     "al arrancar, el pin queda indefinido y la solenoide puede activarse sola  →  10k a GND"),
]
yy = 46.5
for title, why in rules:
    label(ax, COLX, yy, "✗", BAD, 11.5, ha="left", weight="bold")
    label(ax, COLX + 3.8, yy, title, INK, 9.2, ha="left", weight="bold")
    label(ax, COLX + 3.8, yy - 3.1, why, MUTED, 8.0, ha="left")
    yy -= 7.6

# ============================================================ BUILD ORDER
label(ax, 3, 10.0, "ORDEN DE ARMADO   —   de lo más seguro a lo más riesgoso", INK, 13, ha="left", weight="bold")

stages = [
    ("1", "Solo electrónica", "En el protoboard: SIN agua,\nsin presión y sin servo.\nMide voltajes con multímetro.", HAVE_FC, HAVE_EC),
    ("2", "Verifica los buses", "i2cdetect -y 1  →  debe salir 0x48\nls /sys/bus/w1/devices/  →  28-…\n(1-Wire pide reiniciar)", HAVE_FC, HAVE_EC),
    ("3", "Mide el divisor", "Vout/Vin con el multímetro, ya\nsoldado, y escribe ESE número\nen divider_ratio. No asumas 0.667.", HAVE_FC, HAVE_EC),
    ("4", "Transductor", "Al puerto del manómetro.\nCalibración de 2 puntos contra\nla carátula. Ya hay presión: cuidado.", "#fff8e1", "#b8860b"),
    ("5", "Solenoide + sonda", "Barbs y abrazaderas en la línea\nde permeado. La sonda va en el\nchorro de desecho.", "#fff8e1", "#b8860b"),
    ("6", "Fugas + kill test", "Presuriza y verifica que sostiene.\nLuego desconecta el sensor a media\ncorrida: DEBE ventear y abortar.", "#fff8e1", "#b8860b"),
    ("7", "Servo — aún NO", "Acople, extremos y servo_close_us.\nCon la válvula DESACOPLADA\ndel vástago. Requiere OK.", "#fdecec", BAD),
]
x0, wbox = 3, 27.2
for i, (num, title, body, fc, ec) in enumerate(stages):
    xx = x0 + i * (wbox + 0.85)
    box(ax, xx, 0.5, wbox, 7.6, "", fc, ec, lw=1.7)
    label(ax, xx + 1.8, 6.4, num, ec, 13, ha="left", weight="bold")
    label(ax, xx + 5.6, 6.4, title, INK, 8.7, ha="left", weight="bold")
    label(ax, xx + 1.8, 3.0, body, INK, 7.3, ha="left", va="center")

os.makedirs(OUT, exist_ok=True)
path = os.path.join(OUT, "wiring_diagram.png")
fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
print("wrote", path)


# =====================================================================
# Figure 2 — voltage-divider detail sheet
# The divider is the one spot where a wiring mistake destroys a part, and
# it is NOT a purchasable component: it is two resistors from the kit.
# =====================================================================
fig2, ax = plt.subplots(figsize=(13.6, 8.4))
ax.set_xlim(0, 136)
ax.set_ylim(0, 84)
ax.axis("off")
fig2.patch.set_facecolor("white")


def res_h(ax, x, y, w, h, text):
    """Horizontal resistor."""
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.15",
                                fc="#fff8e1", ec="#b8860b", lw=2.0, zorder=3))
    label(ax, x + w / 2, y + h / 2, text, INK, 10.5, weight="bold")


label(ax, 3, 79.5, "El divisor de voltaje  —  qué es y cómo se arma", INK, 19, ha="left", weight="bold")

ax.add_patch(FancyBboxPatch((3, 68.5), 130, 8.0, boxstyle="round,pad=0.3",
                            fc="#fff4e5", ec="#e07b00", lw=2.0, zorder=2))
label(ax, 6, 74.4, "NO es una pieza que se compra.  Son DOS resistencias de tu kit, conectadas así.",
      "#8a4b00", 12.5, ha="left", weight="bold")
label(ax, 6, 70.8,
      "Sirve para una sola cosa: bajar la señal del transductor de 4.5 V a 3.0 V, porque el ADS1115 vive a 3.3 V y 4.5 V lo quema.",
      "#8a4b00", 9.6, ha="left")

# ---- circuit
box(ax, 5, 53, 23, 10, "Transductor\nseñal  0.5 – 4.5 V", MISS_FC, MISS_EC, 9.4)
ax.plot([28, 37], [58, 58], color=SIG, lw=2.2, zorder=2)
res_h(ax, 37, 54.8, 17, 6.4, "R1 = 10 kΩ")
ax.plot([54, 70], [58, 58], color=SIG, lw=2.2, zorder=2)

# node
ax.plot([70], [58], marker="o", ms=9, color=INK, zorder=5)
label(ax, 70, 65.2, "punto de unión", MUTED, 8.4)

# to ADC
ax.plot([70, 84], [58, 58], color=SIG, lw=2.2, zorder=2)
arrow(ax, (84, 58), (88, 58), SIG, lw=2.0)
box(ax, 88, 53, 25, 10, "ADS1115\nentrada A0", HAVE_FC, HAVE_EC, 9.4)
label(ax, 84, 60.6, "0 – 3.0 V   ✓ seguro", GOOD, 9.6, weight="bold")

# R2 branch down to ground
ax.plot([70, 70], [58, 48], color=SIG, lw=2.2, zorder=2)
ax.add_patch(FancyBboxPatch((65.8, 37), 8.4, 11, boxstyle="round,pad=0.15",
                            fc="#fff8e1", ec="#b8860b", lw=2.0, zorder=3))
label(ax, 70, 42.5, "R2\n20 kΩ", INK, 10.5, weight="bold")
ax.plot([70, 70], [37, 31], color=SIG, lw=2.2, zorder=2)
for i, hw in enumerate([6.5, 4.2, 2.0]):
    ax.plot([70 - hw, 70 + hw], [31 - i * 1.9, 31 - i * 1.9], color=INK, lw=2.4, zorder=3)
label(ax, 70, 24.0, "GND  (tierra común)", INK, 9.4, weight="bold")

# the maths
ax.add_patch(FancyBboxPatch((88, 34), 45, 15, boxstyle="round,pad=0.3",
                            fc="#f4f8fb", ec=PWR, lw=1.6, zorder=2))
label(ax, 90.5, 46.0, "La cuenta", PWR, 10.5, ha="left", weight="bold")
label(ax, 90.5, 41.6, "4.5 V  ×   20 kΩ / (10 kΩ + 20 kΩ)", INK, 10.5, ha="left")
label(ax, 90.5, 38.0, "=  4.5 V  ×  0.667  =  3.0 V", INK, 10.5, ha="left", weight="bold")
label(ax, 90.5, 35.4, "cabe en el ADC y no pasa su límite", MUTED, 8.4, ha="left")

# ---- bottom info cards
cards = [
    ("Cómo las identificas",
     "Con 5 bandas (kit de 1 %):\n"
     "10 kΩ  →  café · negro · negro · rojo · café\n"
     "20 kΩ  →  rojo · negro · negro · rojo · café\n\n"
     "Con 4 bandas:\n"
     "10 kΩ  →  café · negro · naranja\n"
     "20 kΩ  →  rojo · negro · naranja",
     "#f7f7f7", MUTED),
    ("Si no traes una de 20 kΩ",
     "Pon DOS de 10 kΩ en serie, una tras otra:\n"
     "10 kΩ + 10 kΩ = 20 kΩ.\n\n"
     "Funciona igual. Lo que importa no es la\n"
     "pieza exacta, es la PROPORCIÓN entre\n"
     "R1 y R2 (que R2 sea el doble de R1).",
     "#e6f4ea", GOOD),
    ("IMPORTANTE:  no asumas 0.667",
     "Las resistencias reales traen tolerancia.\n"
     "Ya soldado, mide con el multímetro el\n"
     "voltaje que entra y el que sale, divide\n"
     "salida ÷ entrada, y ESE número lo escribes\n"
     "en divider_ratio de config.yaml.\n"
     "Si no, la presión te saldrá corrida.",
     "#fdecec", BAD),
]
for i, (title, body, fc, ec) in enumerate(cards):
    xx = 3 + i * 44.0
    ax.add_patch(FancyBboxPatch((xx, 1.5), 41.5, 19.0, boxstyle="round,pad=0.3",
                                fc=fc, ec=ec, lw=1.6, zorder=2))
    label(ax, xx + 2, 17.6, title, ec if ec != MUTED else INK, 10.2, ha="left", weight="bold")
    label(ax, xx + 2, 9.0, body, INK, 8.0, ha="left", va="center")

path2 = os.path.join(OUT, "wiring_divider.png")
fig2.savefig(path2, dpi=150, bbox_inches="tight", facecolor="white")
print("wrote", path2)
