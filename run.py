#!/usr/bin/env python3
"""Entry point.

    python run.py web      [--config config.yaml] [--host 0.0.0.0] [--port 8000] [--sim|--hardware]
    python run.py cli      [--config config.yaml] [--sim|--hardware]
    python run.py analyze  <data.csv> [--area-cm2 0.64] [--thickness-mm 0.117] [--viscosity 1e-3] [--out plot.png]

`web` launches the local web UI; `cli` runs the configured sequence headless
(both honour `mode:`; --sim/--hardware override it). `analyze` fits Q vs ΔP from
an existing CSV of (pressure, flow) and writes the plot — no rig needed.
"""
import sys


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("web", "cli", "analyze"):
        print(__doc__)
        return 1
    which, rest = sys.argv[1], sys.argv[2:]
    if which == "web":
        from src.ui.web import main as web_main
        return web_main(rest)
    if which == "analyze":
        from src.ui.cli import analyze_main
        return analyze_main(rest)
    from src.ui.cli import main as cli_main
    return cli_main(rest)


if __name__ == "__main__":
    raise SystemExit(main())
