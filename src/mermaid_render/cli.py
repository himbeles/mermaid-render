"""Cross-platform command-line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from .api import convert


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render Mermaid as SVG, PNG or connected Visio VSDX",
        epilog="Pele and fonts are bundled. No browser, Node, or runtime downloads are needed.",
    )
    parser.add_argument("input", type=Path, help="Mermaid .mmd/.mermaid file")
    parser.add_argument(
        "-o", "--output", type=Path, help="Output .svg, .png or .vsdx file"
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["svg", "png", "visio", "vsdx"],
        help="Output format (otherwise inferred from -o, default svg)",
    )
    parser.add_argument("--title", help="Diagram title for Visio")
    parser.add_argument(
        "--theme", default="redux-color", help="Mermaid theme (default: redux-color)"
    )
    parser.add_argument(
        "--visio-connectors",
        choices=["right-angle", "straight", "mermaid"],
        default="right-angle",
        help="VSDX connector routing (default: right-angle)",
    )
    parser.add_argument(
        "--background",
        default="white",
        help="PNG background color or transparent (PNG)",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=2.0,
        help="PNG pixel density factor (default 2 = 192 dpi)",
    )
    args = parser.parse_args()
    fmt = args.format or (
        args.output.suffix.lower().lstrip(".") if args.output else "svg"
    )
    fmt = "vsdx" if fmt == "visio" else fmt
    if fmt not in {"svg", "png", "vsdx"}:
        parser.error("output extension must be .svg, .png or .vsdx")
    output = args.output or args.input.with_suffix(f".{fmt}")
    if args.input.suffix.lower() not in {".mmd", ".mermaid"}:
        parser.error("input must be Mermaid (.mmd/.mermaid)")
    try:
        convert(
            args.input.read_text(encoding="utf-8"),
            output,
            format=fmt,
            title=args.title or args.input.stem,
            theme=args.theme,
            background=args.background,
            scale=args.scale,
            visio_connectors=args.visio_connectors,
        )
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f"{exc}\n")
    print(f"Created {output}")


if __name__ == "__main__":
    main()
