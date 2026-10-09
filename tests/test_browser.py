from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import pytest

from mermaid_render.api import svg_to_vsdx
from mermaid_render.vsdx import NS_MAIN

SAMPLE_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" width="340" height="150" viewBox="0 0 340 150">
  <style>rect { fill: #ddeeff; stroke: #002288; stroke-width: 2; } path { stroke: #225522; fill: none; stroke-width: 2; } text { font: bold 16px Arial; fill: #000000; }</style>
  <g transform="translate(10 20)">
    <rect width="100" height="50" x="0" y="0"/>
    <text x="10" y="30">Alpha</text>
    <path d="M 100 25 C 145 25 160 85 210 85"/>
    <rect width="100" height="50" x="210" y="60"/>
    <text x="225" y="90">Beta</text>
  </g>
</svg>'''


def test_svg_end_to_end(tmp_path):
    try:
        data = svg_to_vsdx(SAMPLE_SVG, tmp_path / "diagram.vsdx")
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "BrowserType.launch" in str(exc):
            pytest.skip(f"Browser unavailable: {exc}")
        raise
    assert (tmp_path / "diagram.vsdx").read_bytes() == data
    with ZipFile(BytesIO(data)) as z:
        assert z.testzip() is None
        root = ET.fromstring(z.read("visio/pages/page1.xml"))
        shapes = root.findall(f".//{{{NS_MAIN}}}Shape")
        assert len(shapes) == 5
        labels = [x.text for x in root.findall(f".//{{{NS_MAIN}}}Text")]
        assert labels == ["Alpha", "Beta"]


def test_mermaid_browser_pipeline_offline_with_stub(tmp_path, monkeypatch):
    """Verify local ESM import, Playwright render and SVG output.

    The stub deliberately is not the official Mermaid engine, so this test
    does not claim genuine Mermaid syntax support was tested without internet.
    """
    from mermaid_render.api import mermaid_to_svg
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "mermaid.esm.min.mjs").write_text('''
        const mermaid = {
          initialize(opts) { this.opts = opts; },
          async render(id, source) {
            return {svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 80">
              <rect x="1" y="1" width="60" height="40" fill="lightblue" stroke="black"/>
              <text x="5" y="25" fill="black">${source}</text></svg>`};
          }
        };
        export default mermaid;
    ''', encoding="utf-8")
    monkeypatch.setattr("mermaid_render.api.ensure_mermaid", lambda: dist)
    data = mermaid_to_svg("From Python")
    root = ET.fromstring(data)
    assert root.find("{http://www.w3.org/2000/svg}text").text == "From Python"


def test_svg_arrowhead_becomes_visio_arrow(tmp_path):
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 110 40">
      <defs><marker id="arrow"><path d="M0,0 L10,5 L0,10"/></marker></defs>
      <line x1="0" y1="20" x2="100" y2="20" stroke="black" marker-end="url(#arrow)"/>
    </svg>'''
    data = svg_to_vsdx(svg)
    with ZipFile(BytesIO(data)) as z:
        root = ET.fromstring(z.read("visio/pages/page1.xml"))
        assert any(c.get("N") == "EndArrow" and c.get("V") == "13"
                   for c in root.findall(f".//{{{NS_MAIN}}}Cell"))
