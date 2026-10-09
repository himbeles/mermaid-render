from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import pytest

from mermaid_render import build_connected_vsdx
from mermaid_render.vsdx import NS_MAIN


def test_cross_platform_vsdx_graph_writer():
    nodes = [
        {"id": "A", "x": 10, "y": 10, "width": 90, "height": 50, "text": "Input"},
        {"id": "B", "x": 180, "y": 10, "width": 100, "height": 50, "text": "Output"},
    ]
    data = build_connected_vsdx(nodes, [{"source": "A", "target": "B"}], title="Test")
    with ZipFile(BytesIO(data)) as z:
        assert z.testzip() is None
        for filename in z.namelist():
            if filename.endswith(".xml") or filename.endswith(".rels"):
                ET.fromstring(z.read(filename))
        root = ET.fromstring(z.read("visio/pages/page1.xml"))
        shapes = root.findall(f".//{{{NS_MAIN}}}Shape")
        assert len(shapes) == 3
        links = root.findall(f".//{{{NS_MAIN}}}Connect")
        assert len(links) == 2
        assert {(x.get("FromCell"), x.get("ToSheet"), x.get("ToCell")) for x in links} == {
            ("BeginX", "1", "Connections.X1"),
            ("EndX", "2", "Connections.X3"),
        }
        connector = shapes[2]
        cell_by_name = {x.get("N"): x for x in connector.findall(f"{{{NS_MAIN}}}Cell")}
        assert cell_by_name["ObjType"].get("V") == "2.0"
        assert "Sheet.1!Connections.X1" in cell_by_name["BeginX"].get("F")
        assert "Sheet.2!Connections.X3" in cell_by_name["EndX"].get("F")
        assert len(shapes[0].findall(f".//{{{NS_MAIN}}}Section[@N='Connection']/{{{NS_MAIN}}}Row")) == 4


def test_abstract_graph_bad_links_rejected():
    nodes = [{"id": "one", "x": 0, "y": 0, "width": 80, "height": 40}]
    with pytest.raises(ValueError, match="Unknown edge"):
        build_connected_vsdx(nodes, [{"source": "one", "target": "missing"}])
    with pytest.raises(ValueError, match="Self loops"):
        build_connected_vsdx(nodes, [{"source": "one", "target": "one"}])


def test_uses_svg_y_direction_for_ports():
    nodes = [
        {"id": "a", "x": 30, "y": 10, "width": 80, "height": 40},
        {"id": "b", "x": 30, "y": 150, "width": 80, "height": 40},
    ]
    with ZipFile(BytesIO(build_connected_vsdx(nodes, [{"source": "a", "target": "b"}]))) as z:
        root = ET.fromstring(z.read("visio/pages/page1.xml"))
        links = root.findall(f".//{{{NS_MAIN}}}Connect")
        # Downwards in SVG means bottom-to-top glue.
        assert links[0].get("ToCell") == "Connections.X4"
        assert links[1].get("ToCell") == "Connections.X2"
