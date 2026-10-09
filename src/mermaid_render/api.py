"""Mermaid rendering in bundled Chromium: SVG, PNG, PDF and connected Visio."""
from __future__ import annotations

import math
from importlib.resources import files
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .assets import ensure_browser, ensure_mermaid
from .semantic import build_connected_vsdx
from .vsdx import build_vsdx

LOCAL_MERMAID_ORIGIN = "https://mermaid-render.local"


def _serve_local_mermaid(page, dist: Path) -> str:
    """Resolve virtual HTTPS ES module URLs to runtime files (offline)."""
    dist = dist.resolve()

    def serve(route):
        relative = unquote(urlsplit(route.request.url).path).lstrip("/")
        target = (dist / relative).resolve()
        try:
            target.relative_to(dist)
        except ValueError:
            route.abort("blockedbyclient")
            return
        if not target.is_file():
            route.fulfill(status=404, body="Module not found", headers={"Access-Control-Allow-Origin": "*"})
            return
        content_type = (
            "text/javascript" if target.suffix in (".js", ".mjs") else
            "application/json" if target.suffix == ".json" else
            "application/octet-stream"
        )
        route.fulfill(path=str(target), content_type=content_type,
                      headers={"Access-Control-Allow-Origin": "*"})

    page.route(f"{LOCAL_MERMAID_ORIGIN}/**", serve)
    return f"{LOCAL_MERMAID_ORIGIN}/mermaid.esm.min.mjs"


def _browser(playwright):
    return playwright.chromium.launch(headless=True, executable_path=str(ensure_browser()))


def svg_to_vsdx(
    svg: str, output: str | Path | None = None, *, title: str = "SVG Diagram",
) -> bytes:
    """Geometry-only SVG to VSDX. SVG does not provide semantic glue relationships."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = _browser(p)
        try:
            page = browser.new_page(viewport={"width": 1600, "height": 1200})
            page.set_content("<!doctype html><html><body><div id='root'></div></body></html>")
            page.locator("#root").evaluate("(el, svg) => { el.innerHTML = svg; }", svg)
            capture = files("mermaid_render").joinpath("capture.js").read_text(encoding="utf-8")
            drawing = page.evaluate(capture)
            if not drawing or not drawing.get("items"):
                raise ValueError("SVG contained no supported visible shapes or text")
            result = build_vsdx(drawing, title=title)
        finally:
            browser.close()
    if output is not None:
        Path(output).write_bytes(result)
    return result



def _render_image(page, *, output_format: str, background: str, scale: float) -> bytes:
    """Render the Mermaid SVG using Chromium, like mermaid-cli.

    PNG is a screenshot of the SVG at the requested device pixel ratio.
    PDF uses Chromium's vector-aware print-to-PDF, sized to the SVG viewBox.
    """
    if not background or not isinstance(background, str):
        raise ValueError("background must be a non-empty CSS color or 'transparent'")
    dimensions = page.locator("#mount svg").evaluate("""svg => {
        const vb = svg.viewBox.baseVal;
        const box = svg.getBBox();
        const width = vb && vb.width > 0 ? vb.width : box.width;
        const height = vb && vb.height > 0 ? vb.height : box.height;
        if (!(width > 0 && height > 0)) throw new Error('Mermaid SVG has invalid dimensions');
        svg.setAttribute('width', width.toString());
        svg.setAttribute('height', height.toString());
        svg.style.cssText += `;display:block;width:${width}px;height:${height}px;max-width:none;`;
        return {width, height};
    }""")
    width, height = dimensions["width"], dimensions["height"]
    # Print/screenshot must not inherit Chromium's default 8px body margin.
    page.add_style_tag(content=(
        "html,body,#mount{margin:0;padding:0;overflow:visible;} "
        "*{-webkit-print-color-adjust:exact;print-color-adjust:exact;}"
    ))
    transparent = background.lower() == "transparent"
    if not transparent:
        page.locator("#mount svg").evaluate("(svg, color) => svg.style.backgroundColor = color", background)
    if output_format == "png":
        # Page context sets device_scale_factor before rendering Mermaid.
        return page.locator("#mount svg").screenshot(
            type="png", scale="device", omit_background=transparent,
            animations="disabled",
        )
    # Page size uses CSS pixels (96 CSS px/in); SVG paths stay vector in PDF.
    page.add_style_tag(content=(
        f"@page {{ size: {width}px {height}px; margin: 0; }} "
        "html,body,#mount { width: max-content; height: max-content; }"
    ))
    page.emulate_media(media="screen")
    return page.pdf(prefer_css_page_size=True, print_background=True,
                    margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})


def _render_mermaid(
    source: str, *, format: str, title: str, theme: str,
    background: str, scale: float, visio_connectors: str,
) -> bytes:
    from playwright.sync_api import sync_playwright

    dist = ensure_mermaid()
    with sync_playwright() as p:
        browser = _browser(p)
        try:
            page = browser.new_page(
                viewport={"width": 1600, "height": 1200},
                device_scale_factor=scale if format == "png" else 1.0,
            )
            page.set_content("<!doctype html><html><body><div id='mount'></div></body></html>")
            page.route("**/*", lambda route: route.abort("blockedbyclient"))
            engine = _serve_local_mermaid(page, dist)
            page.evaluate("""(moduleUrl) => {
                window.__mermaidReady = false;
                window.__mermaidLoadError = null;
                import(moduleUrl).then(m => {
                    window.__mermaid = m.default;
                    window.__mermaidReady = true;
                }).catch(e => { window.__mermaidLoadError = String(e); });
            }""", engine)
            try:
                page.wait_for_function("window.__mermaidReady || window.__mermaidLoadError", timeout=30000)
            except Exception as exc:
                raise RuntimeError("Mermaid could not load from its installed support files") from exc
            error = page.evaluate("window.__mermaidLoadError")
            if error:
                raise RuntimeError(f"Mermaid renderer failed to load: {error}.")
            svg = page.evaluate("""async ({source, theme}) => {
                const m = window.__mermaid;
                m.initialize({startOnLoad:false,securityLevel:'strict',theme,
                    htmlLabels:false,flowchart:{htmlLabels:false}});
                const {svg} = await m.render('mermaid_render_graph', source);
                document.getElementById('mount').innerHTML = svg;
                window.__mermaidSource = source;
                return svg;
            }""", {"source": source, "theme": theme})
            if format == "svg":
                result = svg.encode("utf-8")
            elif format in {"png", "pdf"}:
                result = _render_image(page, output_format=format, background=background, scale=scale)
            else:
                graph_js = files("mermaid_render").joinpath("graph_capture.js").read_text(encoding="utf-8")
                graph = page.evaluate(graph_js)
                # Do not silently emit a Visio drawing with disconnected nodes.
                if not graph.get("nodes") or not graph.get("edges"):
                    raise ValueError("Connected VSDX requires a flowchart containing nodes and edges")
                result = build_connected_vsdx(graph["nodes"], graph["edges"], title=title,
                                              connectors=visio_connectors)
        finally:
            browser.close()
    return result


def convert(
    source: str, output: str | Path | None = None, *, format: str | None = None,
    title: str = "Mermaid Diagram", theme: str = "redux-color",
    background: str = "white", scale: float = 2.0,
    visio_connectors: str = "right-angle",
) -> bytes:
    """Render Mermaid to SVG, PNG, PDF or editable connected Visio VSDX.

    The extension selects the format unless explicitly specified. Without an
    output path, SVG is the default. PNG uses ``scale`` as a
    pixel density factor (default 2 = 192 dpi; 1 = 96 dpi). PDF remains vector based.
    Connected VSDX currently supports Mermaid flowcharts only. Its connector
    routing is right-angle by default; choose straight or mermaid to override.
    """
    if not math.isfinite(scale) or not (0.1 <= scale <= 4):
        raise ValueError("scale must be between 0.1 and 4")
    if visio_connectors not in {"right-angle", "straight", "mermaid"}:
        raise ValueError("visio_connectors must be 'right-angle', 'straight', or 'mermaid'")
    if format is None:
        format = Path(output).suffix.lower().lstrip(".") if output else "svg"
    format = format.lower().lstrip(".")
    if format == "visio":
        format = "vsdx"
    if format not in {"svg", "png", "pdf", "vsdx"}:
        raise ValueError("format must be 'svg', 'png', 'pdf', 'visio', or 'vsdx'")
    if output is not None and Path(output).suffix.lower() != f".{format}":
        raise ValueError(f"Output filename must end with .{format}")
    result = _render_mermaid(source, format=format, title=title, theme=theme,
                             background=background, scale=scale, visio_connectors=visio_connectors)
    if output is not None:
        Path(output).write_bytes(result)
    return result


def mermaid_to_vsdx(source: str, output: str | Path | None = None, **kwargs) -> bytes:
    """Convert Mermaid flowchart to VSDX with glued native Visio connectors."""
    return convert(source, output, format="vsdx", **kwargs)


def mermaid_to_svg(source: str, output: str | Path | None = None, **kwargs) -> bytes:
    """Render Mermaid to SVG using the official browser-based Mermaid runtime."""
    return convert(source, output, format="svg", **kwargs)


def mermaid_to_png(source: str, output: str | Path | None = None, **kwargs) -> bytes:
    """Render Mermaid to PNG in Chromium."""
    return convert(source, output, format="png", **kwargs)


def mermaid_to_pdf(source: str, output: str | Path | None = None, **kwargs) -> bytes:
    """Render Mermaid to vector PDF via Chromium print-to-PDF."""
    return convert(source, output, format="pdf", **kwargs)
