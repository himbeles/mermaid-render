"""The same Mermaid source can be rendered as SVG or a connected VSDX."""
import os
import shutil
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import pytest

from mermaid_render import convert
from mermaid_render.vsdx import NS_MAIN

BROWSER = os.environ.get("CHROMIUM_PATH") or shutil.which("chromium") or shutil.which("google-chrome")


@pytest.fixture
def stub_dist(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "mermaid.esm.min.mjs").write_text(r'''
        const model = {
          nodes: [
            {id:'A',label:'Input',shape:'rect'},
            {id:'B',label:'Output',shape:'decision'},
            {id:'C',label:'Done',shape:'rect'},
          ],
          edges: [
            {start:'A',end:'B',label:'process',arrowTypeEnd:'point'},
            {start:'B',end:'C',label:'yes',arrowTypeEnd:'point'}
          ]
        };
        const mermaid = {
          initialize() {},
          async render(id, source) {
            return {svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 130">
              <g class="node" id="flowchart-A-0" transform="translate(55,60)">
                <rect x="-45" y="-20" width="90" height="40" fill="#F0F4FF" stroke="#445577"/>
                <text x="0" y="5" text-anchor="middle">Input</text>
              </g>
              <g class="node" data-id="B" transform="translate(200,60)">
                <polygon points="0,-30 55,0 0,30 -55,0" fill="#FFEECC" stroke="#445577"/>
                <text x="0" y="5" text-anchor="middle">Output</text>
              </g>
              <g class="node" id="flowchart-C-2" transform="translate(345,60)">
                <rect x="-45" y="-20" width="90" height="40" fill="#F0F4FF" stroke="#445577"/>
                <text x="0" y="5" text-anchor="middle">Done</text>
              </g>
            </svg>`};
          },
          mermaidAPI: {
            async getDiagramFromText(source) {return {type:'flowchart-v2',db:{getData(){return model;}}};}
          }
        };
        export default mermaid;
    ''', encoding="utf-8")
    return dist


def test_svg_output(stub_dist, tmp_path):
    out = tmp_path / "diagram.svg"
    data = convert("flowchart LR; A-->B", out, mermaid_dist=stub_dist, chromium_executable=BROWSER)
    assert out.read_bytes() == data
    assert b'<svg' in data
    assert b'class="node"' in data


def test_connected_vsdx_output(stub_dist, tmp_path):
    out = tmp_path / "diagram.vsdx"
    data = convert("flowchart LR; A-->B", out, mermaid_dist=stub_dist, chromium_executable=BROWSER)
    with ZipFile(BytesIO(data)) as z:
        assert z.testzip() is None
        root = ET.fromstring(z.read("visio/pages/page1.xml"))
        shapes = root.findall(f".//{{{NS_MAIN}}}Shape")
        links = root.findall(f".//{{{NS_MAIN}}}Connect")
        assert len(shapes) == 5  # 3 grouped node shapes + 2 glued connectors
        assert len(links) == 4  # BeginX and EndX for each edge
        assert [x.text for x in root.findall(f".//{{{NS_MAIN}}}Text")] == [
            "Input", "Output", "Done", "process", "yes"
        ]
        ids = {shape.get("ID") for shape in shapes}
        assert all(link.get("ToSheet") in ids for link in links)
        connectors = shapes[3:]
        assert all(any(x.get('N') == 'BeginX' and 'Connections.X' in x.get('F', '')
                       for x in shape.findall(f'{{{NS_MAIN}}}Cell')) for shape in connectors)
    assert out.read_bytes() == data


def test_format_validation(stub_dist, tmp_path):
    with pytest.raises(ValueError, match="format must"):
        convert("graph LR", format="gif", mermaid_dist=stub_dist)
    assert convert("flowchart LR; A-->B", format="visio", mermaid_dist=stub_dist,
                   chromium_executable=BROWSER).startswith(b"PK")
    with pytest.raises(ValueError, match="Output filename"):
        convert("graph LR", tmp_path / "a.svg", format="vsdx", mermaid_dist=stub_dist)


def test_unsupported_diagram_fails_for_connected_visio(stub_dist, tmp_path):
    f = stub_dist / 'mermaid.esm.min.mjs'
    f.write_text(f.read_text().replace("type:'flowchart-v2'", "type:'sequence'"))
    with pytest.raises(Exception, match="Connected VSDX export supports Mermaid flowcharts"):
        convert('sequenceDiagram', format='vsdx', mermaid_dist=stub_dist, chromium_executable=BROWSER)
    assert b'<svg' in convert('sequenceDiagram', format='svg', mermaid_dist=stub_dist, chromium_executable=BROWSER)


def test_png_output_and_scale(stub_dist, tmp_path):
    import struct
    out = tmp_path / "diagram.png"
    data = convert("flowchart LR; A-->B", out, mermaid_dist=stub_dist,
                   chromium_executable=BROWSER, scale=2)
    assert out.read_bytes() == data
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (800, 260)


def test_png_transparent_background(stub_dist):
    data = convert("flowchart LR; A-->B", format="png", background="transparent",
                   mermaid_dist=stub_dist, chromium_executable=BROWSER)
    assert data.startswith(b"\x89PNG\r\n\x1a\n")


def test_pdf_output(stub_dist, tmp_path):
    out = tmp_path / "diagram.pdf"
    data = convert("flowchart LR; A-->B", out, mermaid_dist=stub_dist,
                   chromium_executable=BROWSER)
    assert out.read_bytes() == data
    assert data.startswith(b"%PDF-")
    assert len(data) > 1000


def test_image_validation(stub_dist, tmp_path):
    with pytest.raises(ValueError, match="scale must"):
        convert("flowchart LR; A-->B", format="png", scale=-1)
    with pytest.raises(ValueError, match="scale must"):
        convert("flowchart LR; A-->B", format="png", scale=float("nan"))
    with pytest.raises(ValueError, match="Output filename"):
        convert("flowchart LR; A-->B", tmp_path / "test.pdf", format="png")
