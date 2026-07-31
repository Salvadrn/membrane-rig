"""Render the wiring sheets to PDF for printing at the bench.

The sheets in `docs/*.html` are HTML *fragments* — no doctype, no <html>, no
<head> — because they are written to be embedded. Printing them means wrapping
each one in a real document first, which is what this does, then driving
headless Chrome.

    ./.venv/bin/python tools/sheets_to_pdf.py              # every sheet
    ./.venv/bin/python tools/sheets_to_pdf.py wiring_ubec  # just one

Output goes to `docs/pdf/`. Regenerate after editing any sheet — nothing keeps
the PDFs in sync automatically.

Two things the wrapper has to fix, both of which come from the sheets being
designed for a screen:

  * The sheets take their surfaces and text from CSS variables supplied by the
    host page (`--text-primary`, `--surface-0`, …) and fall back to light
    values. On paper we pin the light values explicitly rather than relying on
    the fallbacks, so a sheet never prints white-on-white.
  * They also honour `prefers-color-scheme: dark`. Headless Chrome defaults to
    light, but we force it, because a dark sheet on a laser printer is a solid
    black page.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUT = DOCS / "pdf"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Landscape at a width that matches how the sheets were laid out (max-width
# 1280 px). A4 portrait would reflow the two-column blocks into a ribbon.
PAGE_CSS = """
:root {
  --text-primary:#1a1a1a; --text-secondary:#5b5b5b;
  --surface-0:#ffffff; --surface-1:#ffffff; --border:#dcdcdc;
  --font-sans:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
}
@page { size: A3 landscape; margin: 10mm; }
html,body { background:#fff; color:#1a1a1a; margin:0; padding:0; }
body { font-family: var(--font-sans); }
/* Keep blocks from splitting across a page break mid-diagram. */
svg, table, pre { break-inside: avoid; page-break-inside: avoid; }
"""

SHELL = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>{title}</title><style>{css}</style></head><body>{body}</body></html>"""


def render(name: str) -> Path | None:
    src = DOCS / f"{name}.html"
    if not src.exists():
        print(f"  {name}: no existe {src}")
        return None

    OUT.mkdir(exist_ok=True)
    dst = OUT / f"{name}.pdf"
    html = SHELL.format(title=name, css=PAGE_CSS, body=src.read_text())

    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / f"{name}.html"
        page.write_text(html)
        # --headless=new is required: the classic --headless hangs indefinitely
        # on this machine instead of exiting after writing the PDF.
        cmd = [
            CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
            "--no-pdf-header-footer", "--force-color-profile=srgb",
            f"--user-data-dir={td}/profile",
            f"--print-to-pdf={dst}",
            "--virtual-time-budget=5000",
            page.as_uri(),
        ]
        # NOT capture_output=True. Chrome spawns helpers (the updater, the crash
        # handler) that inherit the pipe and outlive the browser, so waiting for
        # EOF on a pipe hangs long after the PDF has been written. Send the
        # noise to a file and read it only if something went wrong.
        log = Path(td) / "chrome.log"
        with log.open("w") as fh:
            try:
                subprocess.run(cmd, stdout=fh, stderr=fh, timeout=120)
            except subprocess.TimeoutExpired:
                pass  # the PDF is usually already on disk; the check below decides
        err = log.read_text()[-400:]

    if not dst.exists() or dst.stat().st_size == 0:
        print(f"  {name}: FALLÓ\n{err}")
        return None
    print(f"  {name}.pdf  {dst.stat().st_size/1024:.0f} KB")
    return dst


def main() -> int:
    if not Path(CHROME).exists():
        print(f"Chrome no está en {CHROME}")
        return 1

    names = sys.argv[1:] or sorted(p.stem for p in DOCS.glob("wiring_*.html"))
    print(f"renderizando {len(names)} hoja(s) a {OUT.relative_to(ROOT)}/\n")
    ok = [render(n.removesuffix(".html")) for n in names]
    failed = sum(1 for x in ok if x is None)
    print(f"\n{len(ok) - failed}/{len(ok)} listas")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
