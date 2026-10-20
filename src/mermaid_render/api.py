"""Browser-free SVG, native PNG, and editable connected Visio exports."""

from __future__ import annotations
import math
from pathlib import Path
from .renderer import render
from .fonts import ROOT as FONT_ROOT
from .svg import SvgDocument, color
from .capture import connected_graph, sequence_graph
from .semantic import build_connected_vsdx
from .sequence import build_sequence_vsdx
from .vsdx import build_vsdx


def svg_to_vsdx(
    svg: str, output: str | Path | None = None, *, title: str = "SVG Diagram"
) -> bytes:
    """Capture supported SVG shapes/text without a browser; no semantic glue."""
    result = build_vsdx(SvgDocument(svg).display(), title=title)
    if output is not None:
        Path(output).write_bytes(result)
    return result


def convert(
    source: str,
    output: str | Path | None = None,
    *,
    format: str | None = None,
    title: str = "Mermaid Diagram",
    theme: str = "redux-color",
    background: str = "white",
    scale: float = 2.0,
    visio_connectors: str = "right-angle",
) -> bytes:
    """Render Mermaid with embedded Pele/QuickJS to SVG, PNG, or connected VSDX.

    No browser, Node installation, subprocess, or runtime downloads are needed.
    Connected VSDX supports flowchart, state,
    class and sequence diagrams. Other Pele diagram types support SVG and PNG.
    Theme names select fixed Pele palettes.
    """
    if (
        not isinstance(scale, (int, float))
        or not math.isfinite(scale)
        or not 0.1 <= scale <= 4
    ):
        raise ValueError("scale must be between 0.1 and 4")
    if visio_connectors not in {"right-angle", "straight", "mermaid"}:
        raise ValueError(
            "visio_connectors must be 'right-angle', 'straight', or 'mermaid'"
        )
    selected = (
        (format or (Path(output).suffix.lstrip(".") if output else "svg"))
        .lower()
        .lstrip(".")
    )
    if selected == "visio":
        selected = "vsdx"
    if selected not in {"svg", "png", "vsdx"}:
        raise ValueError("format must be 'svg', 'png', 'visio', or 'vsdx'")
    if output is not None and Path(output).suffix.lower() != "." + selected:
        raise ValueError(f"Output filename must end with .{selected}")
    if not isinstance(background, str) or not background.strip():
        raise ValueError("background must be a non-empty CSS color or 'transparent'")
    reply = render(source, theme)
    if selected == "svg":
        result = reply["result"]["svg"].encode("utf-8")
    elif selected == "png":
        import resvg_py

        bg = None if background.lower() == "transparent" else color(background)
        width, height = reply["result"]["width"], reply["result"]["height"]
        if width * height * scale * scale > 100_000_000:
            raise ValueError(
                "PNG exceeds the 100 megapixel render limit; use SVG or reduce scale"
            )
        result = resvg_py.svg_to_bytes(
            svg_string=reply["result"]["svg"],
            zoom=scale,
            background=bg,
            font_files=[str(p) for p in FONT_ROOT.glob("*.ttf")],
            font_family="Noto Sans",
            skip_system_fonts=False,
        )
    elif reply["graph"]["type"] == "sequence":
        result = build_sequence_vsdx(sequence_graph(reply, theme), title=title)
    else:
        nodes, edges = connected_graph(reply, theme)
        result = build_connected_vsdx(
            nodes, edges, title=title, connectors=visio_connectors
        )
    if output is not None:
        Path(output).write_bytes(result)
    return result


def mermaid_to_vsdx(source: str, output: str | Path | None = None, **kwargs) -> bytes:
    return convert(source, output, format="vsdx", **kwargs)


def mermaid_to_svg(source: str, output: str | Path | None = None, **kwargs) -> bytes:
    return convert(source, output, format="svg", **kwargs)


def mermaid_to_png(source: str, output: str | Path | None = None, **kwargs) -> bytes:
    return convert(source, output, format="png", **kwargs)
