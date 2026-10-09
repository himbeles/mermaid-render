"""Cross-platform command-line entry point."""
from __future__ import annotations

import argparse
from pathlib import Path

from .api import convert
from .assets import RuntimeSetupError, setup_runtime


def main() -> None:
    import sys

    if sys.argv[1:] == ["setup"]:
        try:
            mermaid, browser = setup_runtime()
        except RuntimeSetupError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"Runtime ready: Mermaid at {mermaid}; Chromium at {browser}")
        return
    parser = argparse.ArgumentParser(description="Render Mermaid as SVG, PNG, PDF or connected Visio VSDX",
                                     epilog="Missing runtime files install automatically. Use mermaid-render setup to prepare them in advance.")
    parser.add_argument("input", type=Path, help="Mermaid .mmd/.mermaid file")
    parser.add_argument("-o", "--output", type=Path, help="Output .svg, .png, .pdf or .vsdx file")
    parser.add_argument("-f", "--format", choices=["svg", "png", "pdf", "visio", "vsdx"], help="Output format (otherwise inferred from -o, default svg)")
    parser.add_argument("--title", help="Diagram title for Visio")
    parser.add_argument("--theme", default="default", help="Mermaid theme")
    parser.add_argument("--background", default="white", help="PNG/PDF background color or transparent (PNG)")
    parser.add_argument("--scale", type=float, default=1.0, help="PNG pixel density factor (default 1 = 96 dpi)")
    args = parser.parse_args()
    fmt = args.format or (args.output.suffix.lower().lstrip(".") if args.output else "svg")
    fmt = "vsdx" if fmt == "visio" else fmt
    if fmt not in {"svg", "png", "pdf", "vsdx"}:
        parser.error("output extension must be .svg, .png, .pdf or .vsdx")
    output = args.output or args.input.with_suffix(f".{fmt}")
    if args.input.suffix.lower() not in {".mmd", ".mermaid"}:
        parser.error("input must be Mermaid (.mmd/.mermaid)")
    try:
        convert(args.input.read_text(encoding="utf-8"), output, format=fmt,
                title=args.title or args.input.stem, theme=args.theme,
                background=args.background, scale=args.scale)
    except RuntimeSetupError as exc:
        parser.exit(1, f"{exc}\n")
    print(f"Created {output}")


if __name__ == "__main__":
    main()
