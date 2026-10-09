"""Cross-platform command-line entry point."""
from __future__ import annotations

import argparse
from pathlib import Path

from .api import convert


def main() -> None:
    parser = argparse.ArgumentParser(description="Render Mermaid as SVG, PNG, PDF or connected Visio VSDX")
    parser.add_argument("input", type=Path, help="Mermaid .mmd/.mermaid file")
    parser.add_argument("-o", "--output", type=Path, help="Output .svg, .png, .pdf or .vsdx file")
    parser.add_argument("-f", "--format", choices=["svg", "png", "pdf", "visio", "vsdx"], help="Output format (otherwise inferred from -o, default vsdx)")
    parser.add_argument("--title", help="Diagram title for Visio")
    parser.add_argument("--theme", default="default", help="Mermaid theme")
    parser.add_argument("--background", default="white", help="PNG/PDF background color or transparent (PNG)")
    parser.add_argument("--scale", type=float, default=1.0, help="PNG pixel density factor (default 1 = 96 dpi)")
    parser.add_argument("--mermaid-dist", type=Path, help="Local Mermaid runtime dist/ for offline use")
    parser.add_argument("--chromium", type=Path, help="Override the browser executable")
    args = parser.parse_args()
    fmt = args.format or (args.output.suffix.lower().lstrip(".") if args.output else "vsdx")
    fmt = "vsdx" if fmt == "visio" else fmt
    if fmt not in {"svg", "png", "pdf", "vsdx"}:
        parser.error("output extension must be .svg, .png, .pdf or .vsdx")
    output = args.output or args.input.with_suffix(f".{fmt}")
    if args.input.suffix.lower() not in {".mmd", ".mermaid"}:
        parser.error("input must be Mermaid (.mmd/.mermaid); SVG input has no semantic graph for connected VSDX")
    convert(args.input.read_text(encoding="utf-8"), output, format=fmt,
            title=args.title or args.input.stem, theme=args.theme,
            mermaid_dist=args.mermaid_dist, chromium_executable=args.chromium,
            background=args.background, scale=args.scale)
    print(f"Created {output}")


if __name__ == "__main__":
    main()
