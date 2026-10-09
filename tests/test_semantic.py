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
        assert cell_by_name["ObjType"].get("V") == "2"
        assert "Sheet.1!Connections.X1" in cell_by_name["BeginX"].get("F")
        assert "Sheet.2!Connections.X3" in cell_by_name["EndX"].get("F")
        assert len(shapes[0].findall(f".//{{{NS_MAIN}}}Section[@N='Connection']/{{{NS_MAIN}}}Row")) == 4


def test_abstract_graph_bad_links_rejected():
    nodes = [{"id": "one", "x": 0, "y": 0, "width": 80, "height": 40}]
    with pytest.raises(ValueError, match="Unknown edge"):
        build_connected_vsdx(nodes, [{"source": "one", "target": "missing"}])


def test_self_loop_has_visible_route_and_two_distinct_glued_ports():
    nodes = [{"id": "one", "x": 0, "y": 0, "width": 80, "height": 40}]
    with ZipFile(BytesIO(build_connected_vsdx(nodes, [{"source": "one", "target": "one"}]))) as z:
        root = ET.fromstring(z.read('visio/pages/page1.xml'))
    ns = {'v': NS_MAIN}
    links = root.findall('v:Connects/v:Connect', ns)
    assert {c.get('ToSheet') for c in links} == {'1'}
    assert {c.get('ToCell') for c in links} == {'Connections.X1', 'Connections.X2'}
    connector = root.find('v:Shapes', ns)[-1]
    assert len(connector.findall("v:Section[@N='Geometry']/v:Row", ns)) == 5
    assert any(float(c.get('V')) != 0 for c in connector.findall("v:Section[@N='Geometry']/v:Row/v:Cell[@N='Y']", ns))


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


def test_wide_overlapping_boxes_connect_on_the_separating_axis():
    nodes = [
        {'id': 'a', 'x': 0, 'y': 0, 'width': 160, 'height': 40},
        {'id': 'b', 'x': 100, 'y': 80, 'width': 160, 'height': 40},
    ]
    with ZipFile(BytesIO(build_connected_vsdx(nodes, [{'source': 'a', 'target': 'b'}]))) as z:
        root = ET.fromstring(z.read('visio/pages/page1.xml'))
    links = root.findall(f'.//{{{NS_MAIN}}}Connect')
    assert [link.get('ToCell') for link in links] == ['Connections.X4', 'Connections.X2']


@pytest.mark.parametrize("target", [(180, 10), (-180, 10), (10, 180), (10, -180), (180, 180)])
def test_connector_transform_follows_glued_endpoints(target):
    nodes = [
        {"id": "a", "x": 10, "y": 10, "width": 80, "height": 40},
        {"id": "b", "x": target[0], "y": target[1], "width": 80, "height": 40},
    ]
    with ZipFile(BytesIO(build_connected_vsdx(nodes, [{"source": "a", "target": "b"}]))) as z:
        root = ET.fromstring(z.read("visio/pages/page1.xml"))
    ns = {"v": NS_MAIN}
    shapes = root.find("v:Shapes", ns)
    connector = shapes[-1]
    cells = {c.get("N"): c for c in connector.findall("v:Cell", ns)}
    assert len(cells) == len(connector.findall("v:Cell", ns))
    assert {name: cells[name].get("F") for name in (
        "PinX", "PinY", "LocPinX", "LocPinY", "Width", "Angle",
    )} == {
        "PinX": "(BeginX+EndX)/2", "PinY": "(BeginY+EndY)/2",
        "LocPinX": "Width*0.5", "LocPinY": "Height*0.5",
        "Width": "SQRT((EndX-BeginX)^2+(EndY-BeginY)^2)",
        "Angle": "ATAN2(EndY-BeginY,EndX-BeginX)",
    }
    # Every glue record must identify an existing connection row and use the
    # same target as both endpoint formulas; ToPart uses zero-based row indices.
    for link in root.findall("v:Connects/v:Connect", ns):
        node = next(s for s in shapes if s.get("ID") == link.get("ToSheet"))
        row_index = int(link.get("ToPart")) - 100
        row = node.find(f"v:Section[@N='Connection']/v:Row[@IX='{row_index}']", ns)
        assert row is not None
        # Match the connection-point row type emitted by Visio itself. A row
        # with coordinates alone does not fully describe a connection point.
        assert row.get("T") == "Connection"
        assert row.find("v:Cell[@N='AutoGen']", ns).get("V") == "0"
        assert row.find("v:Cell[@N='Prompt']", ns) is not None
        reference = f"Sheet.{node.get('ID')}!Connections.X{row_index + 1}"
        endpoint = link.get("FromCell")[:-1]
        assert reference in cells[endpoint + "X"].get("F")
        assert cells[endpoint + "X"].get("F") == cells[endpoint + "Y"].get("F")


def test_connector_is_unfilled_for_diagrams_net_import():
    nodes = [
        {"id": "a", "x": 0, "y": 0, "width": 80, "height": 40},
        {"id": "b", "x": 180, "y": 0, "width": 80, "height": 40},
    ]
    with ZipFile(BytesIO(build_connected_vsdx(nodes, [{"source": "a", "target": "b"}]))) as z:
        root = ET.fromstring(z.read("visio/pages/page1.xml"))
    ns = {"v": NS_MAIN}
    connector = root.find("v:Shapes", ns)[-1]
    # diagrams.net uses a literal equality check here. "1.0" makes the
    # connector a filled vertex, so its source/target relationships are lost.
    assert connector.find("v:Section[@N='Geometry']/v:Cell[@N='NoFill']", ns).get("V") == "1"
    assert connector.find("v:Cell[@N='FillPattern']", ns).get("V") == "0"


@pytest.mark.parametrize("target", [(180, 10), (10, 180), (180, 180)])
def test_connector_label_has_independent_readable_text_box(target):
    nodes = [
        {"id": "a", "x": 10, "y": 10, "width": 80, "height": 40},
        {"id": "b", "x": target[0], "y": target[1], "width": 80, "height": 40},
    ]
    data = build_connected_vsdx(nodes, [{"source": "a", "target": "b", "text": "Get money"}])
    with ZipFile(BytesIO(data)) as z:
        root = ET.fromstring(z.read("visio/pages/page1.xml"))
    ns = {"v": NS_MAIN}
    connector = root.find("v:Shapes", ns)[-1]
    cells = {c.get("N"): c for c in connector.findall("v:Cell", ns)}
    assert connector.findtext("v:Text", namespaces=ns) == "Get money"
    assert float(cells["Height"].get("V")) == 0
    assert float(cells["TxtHeight"].get("V")) >= 24 / 96
    assert float(cells["TxtWidth"].get("V")) >= (len("Get money") * 7 + 8) / 96
    assert cells["TxtPinX"].get("F") == "Width*0.5"
    assert cells["TxtLocPinY"].get("F") == "TxtHeight*0.5"
    # The text rotation cancels the line rotation, including vertical edges.
    assert cells["TxtAngle"].get("F") == "-Angle"
    assert float(cells["TxtAngle"].get("V")) == -float(cells["Angle"].get("V"))


@pytest.mark.parametrize("kind,radius", [
    ("squareRect", None), ("rect", None), ("roundedRect", 5 / 96),
    ("round", 5 / 96), ("stadium", 20 / 96),
])
def test_mermaid_rectangular_shape_variants(kind, radius):
    node = {"id": "a", "x": 0, "y": 0, "width": 80, "height": 40, "shape": kind}
    with ZipFile(BytesIO(build_connected_vsdx([node], []))) as z:
        root = ET.fromstring(z.read("visio/pages/page1.xml"))
    ns = {"v": NS_MAIN}
    shape = root.find("v:Shapes/v:Shape", ns)
    rounding = shape.find("v:Cell[@N='Rounding']", ns)
    if radius is None:
        assert rounding is None
    else:
        assert float(rounding.get("V")) == pytest.approx(radius, abs=1e-6)
    assert len(shape.findall("v:Section[@N='Connection']/v:Row", ns)) == 4


def test_rendered_bezier_controls_and_glue_preserve_svg_coordinates():
    from math import cos, sin

    nodes = [
        {'id': 'a', 'x': 0, 'y': 0, 'width': 80, 'height': 40},
        {'id': 'b', 'x': 180, 'y': 120, 'width': 80, 'height': 80, 'shape': 'diam'},
    ]
    segments = [
        {'type': 'M', 'points': [{'x': 60, 'y': 40}]},
        {'type': 'Q', 'points': [{'x': 60, 'y': 70}, {'x': 100, 'y': 70}]},
        {'type': 'C', 'points': [{'x': 150, 'y': 70}, {'x': 200, 'y': 90}, {'x': 200, 'y': 140}]},
    ]
    edge = {'source': 'a', 'target': 'b', 'route': [{'x': 60, 'y': 40}, {'x': 200, 'y': 140}], 'segments': segments}
    with ZipFile(BytesIO(build_connected_vsdx(nodes, [edge], connectors='mermaid'))) as archive:
        page = ET.fromstring(archive.read('visio/pages/page1.xml'))
    ns = {'v': NS_MAIN}
    shapes = page.findall('v:Shapes/v:Shape', ns)
    cells = {c.get('N'): float(c.get('V')) for c in shapes[-1].findall('v:Cell', ns)
             if c.get('N') in {'BeginX', 'BeginY', 'Width', 'Height', 'Angle'}}
    assert cells['Height'] == cells['Width'] > 0
    rows = shapes[-1].findall("v:Section[@N='Geometry']/v:Row", ns)
    assert [r.get('T') for r in rows] == ['RelMoveTo', 'RelQuadBezTo', 'RelCubBezTo']
    for segment, row in zip(segments, rows):
        for point, (xc, yc) in zip([segment['points'][-1]] + segment['points'][:-1], [('X','Y'), ('A','B'), ('C','D')]):
            x = float(row.find(f"v:Cell[@N='{xc}']", ns).get('V')) * cells['Width']
            y = float(row.find(f"v:Cell[@N='{yc}']", ns).get('V')) * cells['Height']
            dx = x*cos(cells['Angle']) - y*sin(cells['Angle'])
            dy = x*sin(cells['Angle']) + y*cos(cells['Angle'])
            assert dx == pytest.approx((point['x'] - 60)/96, abs=1e-5)
            assert dy == pytest.approx(-(point['y'] - 40)/96, abs=1e-5)
    assert {c.get('ToCell') for c in page.findall('v:Connects/v:Connect', ns)} == {'Connections.X5'}
    target_port = shapes[1].find("v:Section[@N='Connection']/v:Row[@IX='4']", ns)
    assert float(target_port.find("v:Cell[@N='X']", ns).get('V')) == pytest.approx(20/96, abs=1e-6)
    assert float(target_port.find("v:Cell[@N='Y']", ns).get('V')) == pytest.approx(60/96, abs=1e-6)
    assert 'extra_ports' not in nodes[0]
