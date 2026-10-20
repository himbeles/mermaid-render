from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import pytest

from mermaid_render.api import svg_to_vsdx
from mermaid_render.vsdx import NS_MAIN

SAMPLE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="340" height="150" viewBox="0 0 340 150">
  <style>rect { fill: #ddeeff; stroke: #002288; stroke-width: 2; } path { stroke: #225522; fill: none; stroke-width: 2; } text { font: bold 16px Arial; fill: #000000; }</style>
  <g transform="translate(10 20)">
    <rect width="100" height="50" x="0" y="0"/>
    <text x="10" y="30">Alpha</text>
    <path d="M 100 25 C 145 25 160 85 210 85"/>
    <rect width="100" height="50" x="210" y="60"/>
    <text x="225" y="90">Beta</text>
  </g>
</svg>"""


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


def test_svg_arrowhead_becomes_visio_arrow(tmp_path):
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 110 40">
      <defs><marker id="arrow"><path d="M0,0 L10,5 L0,10"/></marker></defs>
      <line x1="0" y1="20" x2="100" y2="20" stroke="black" marker-end="url(#arrow)"/>
    </svg>"""
    data = svg_to_vsdx(svg)
    with ZipFile(BytesIO(data)) as z:
        root = ET.fromstring(z.read("visio/pages/page1.xml"))
        assert any(
            c.get("N") == "EndArrow" and c.get("V") == "13"
            for c in root.findall(f".//{{{NS_MAIN}}}Cell")
        )


def test_mermaid_subgraphs_export_with_connected_nodes():
    """Exercise Mermaid's real prefixed cluster IDs and retain every glue record."""
    from mermaid_render import convert

    source = """flowchart LR
      subgraph Inputs["Inputs"]
        A["Input"]
      end
      A -->|motion| B["Process"]
      B --> C["Check"]
      subgraph Output-group["Outputs"]
        B
        C
      end
    """
    data = convert(source, format="vsdx")
    with ZipFile(BytesIO(data)) as archive:
        assert archive.testzip() is None
        page = ET.fromstring(archive.read("visio/pages/page1.xml"))
    labels = [el.text for el in page.findall(f".//{{{NS_MAIN}}}Text")]
    assert set(labels) == {"Inputs", "Outputs", "Input", "Process", "Check", "motion"}
    shapes = page.findall(f"{{{NS_MAIN}}}Shapes/{{{NS_MAIN}}}Shape")
    assert len(shapes) == 7  # Two subgraphs, three nodes, two connectors.
    connects = page.findall(f"{{{NS_MAIN}}}Connects/{{{NS_MAIN}}}Connect")
    assert len(connects) == 4
    node_ids = {
        shape.get("ID")
        for shape in shapes
        if shape.find(f"{{{NS_MAIN}}}Text") is not None
        and shape.find(f"{{{NS_MAIN}}}Text").text in {"Input", "Process", "Check"}
    }
    assert all(connection.get("ToSheet") in node_ids for connection in connects)


@pytest.mark.parametrize("routing", ["right-angle", "straight", "mermaid"])
def test_expanded_flowchart_shapes_keep_glue_and_ports(routing):
    from mermaid_render import convert

    source = (
        Path(__file__)
        .with_name("fixtures")
        .joinpath("application-flow.mmd")
        .read_text()
    )
    with ZipFile(
        BytesIO(convert(source, format="vsdx", visio_connectors=routing))
    ) as archive:
        root = ET.fromstring(archive.read("visio/pages/page1.xml"))
    ns = {"v": NS_MAIN}
    assert len(root.findall("v:Shapes/v:Shape", ns)) == 12
    assert len(root.findall("v:Connects/v:Connect", ns)) == 12
    # Expanded artwork stays in one connected node, with custom connection points.
    shapes = root.findall("v:Shapes/v:Shape", ns)
    for shape in shapes[:3]:
        assert len(shape.findall("v:Section[@N='Geometry']/v:Row", ns)) > 5
    node = shapes[0]
    port = float(
        node.find("v:Section[@N='Connection']/v:Row[@IX='1']/v:Cell[@N='Y']", ns).get(
            "V"
        )
    )
    height = float(node.find("v:Cell[@N='Height']", ns).get("V"))
    assert 0 < port < height


def test_nested_svg_and_rotated_text_geometry():
    from mermaid_render.svg import SvgDocument, bounds

    svg = """<svg xmlns="http://www.w3.org/2000/svg"><g transform="translate(10,20)">
    <svg x="5" y="6" width="20" height="10" viewBox="0 0 10 5"><rect width="10" height="5"/></svg>
    </g></svg>"""
    assert bounds(SvgDocument(svg).items()) == pytest.approx(
        dict(x=15, y=26, width=20, height=10)
    )
    rotated = '<svg xmlns="http://www.w3.org/2000/svg"><text x="10" y="20" transform="rotate(45)">Text</text></svg>'
    box = bounds(SvgDocument(rotated).items())
    assert box["width"] > 10 and box["height"] > 10
