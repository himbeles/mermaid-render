"""Optional stdio MCP server for Mermaid rendering."""

from __future__ import annotations

from pathlib import Path
from functools import wraps
import tempfile
from typing import Literal

from .api import convert

_MIME_TYPES = {
    "svg": "image/svg+xml",
    "png": "image/png",
    "vsdx": "application/vnd.ms-visio.drawing",
}


def render_mermaid(
    output_path: str,
    source: str | None = None,
    input_path: str | None = None,
    format: Literal["svg", "png", "vsdx", "visio"] | None = None,
    theme: str = "redux-color",
    title: str = "Mermaid Diagram",
    background: str = "white",
    scale: float = 2.0,
    visio_connectors: Literal["right-angle", "straight", "mermaid"] = "right-angle",
) -> dict[str, str]:
    """Render Mermaid code or a Mermaid file to SVG, PNG, or editable Visio.

    Supply exactly one of source (Mermaid code) or input_path (.mmd/.mermaid).
    output_path is a local destination; use an absolute path when possible.
    format defaults to the output extension, or SVG if it has no extension.
    An explicit format must match the output extension. Missing directories
    are created, and existing output is replaced only after a successful render.
    VSDX supports flowcharts, sequence diagrams, state diagrams, and class diagrams; use SVG/PNG for other
    Mermaid diagram types. scale controls PNG density (default 2). The default
    theme is redux-color. visio_connectors controls flowchart, state-diagram, and class-diagram routing.
    Pele and fonts are bundled; no browser, Node, or runtime downloads are needed.
    Returns output_path, format, and mime_type for the saved file.
    """
    if (source is None) == (input_path is None):
        raise ValueError("Supply exactly one of source or input_path")
    if not output_path.strip():
        raise ValueError("output_path must not be empty")
    destination = Path(output_path).expanduser().resolve()
    selected = format or destination.suffix.lower().lstrip(".") or "svg"
    selected = "vsdx" if selected == "visio" else selected
    if selected not in _MIME_TYPES:
        raise ValueError("Output format must be svg, png, or vsdx")
    if not destination.suffix:
        destination = destination.with_suffix("." + selected)
    if destination.suffix.lower() != "." + selected:
        raise ValueError(f"Output filename must end with .{selected}")
    if input_path is not None:
        if not input_path.strip():
            raise ValueError("input_path must not be empty")
        input_file = Path(input_path).expanduser().resolve()
        if input_file.suffix.lower() not in {".mmd", ".mermaid"}:
            raise ValueError("input_path must be a .mmd or .mermaid file")
        if input_file == destination:
            raise ValueError("Output must differ from the input file")
        source = input_file.read_text(encoding="utf-8")
    if not source or not source.strip():
        raise ValueError("Mermaid source must not be empty")

    data = convert(
        source,
        format=selected,
        theme=theme,
        title=title,
        background=background,
        scale=scale,
        visio_connectors=visio_connectors,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temporary:
        staged = Path(temporary.name)
    try:
        staged.write_bytes(data)
        staged.replace(destination)
    finally:
        staged.unlink(missing_ok=True)
    return {
        "output_path": str(destination),
        "format": selected,
        "mime_type": _MIME_TYPES[selected],
    }


def create_server():
    """Load MCP only when the optional server is requested."""
    try:
        from mcp.server import MCPServer
        from mcp.server.mcpserver.exceptions import ToolError
    except ModuleNotFoundError as exc:
        if exc.name != "mcp":
            raise
        raise RuntimeError(
            'MCP support is not installed. Run: uv tool install --upgrade "mermaid-render[mcp]"'
        ) from exc
    server = MCPServer("Mermaid renderer")

    @wraps(render_mermaid)
    def tool(*args, **kwargs):
        try:
            return render_mermaid(*args, **kwargs)
        except Exception as exc:
            # The SDK deliberately hides unexpected exception messages. Render
            # and input failures need their diagnostic text in the tool result.
            raise ToolError(str(exc)) from exc

    server.tool()(tool)
    return server


def main() -> None:
    try:
        server = create_server()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
