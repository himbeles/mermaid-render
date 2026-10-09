from io import BytesIO
from math import cos, sin
from pathlib import Path
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


def test_mermaid_subgraphs_export_with_connected_nodes():
    """Exercise Mermaid's real prefixed cluster IDs and retain every glue record."""
    from mermaid_render import convert

    source = '''flowchart LR
      subgraph Inputs["Inputs"]
        A["Input"]
      end
      A -->|motion| B["Process"]
      B --> C["Check"]
      subgraph Output-group["Outputs"]
        B
        C
      end
    '''
    data = convert(source, format='vsdx')
    with ZipFile(BytesIO(data)) as archive:
        assert archive.testzip() is None
        page = ET.fromstring(archive.read('visio/pages/page1.xml'))
    labels = [el.text for el in page.findall(f'.//{{{NS_MAIN}}}Text')]
    assert set(labels) == {'Inputs', 'Outputs', 'Input', 'Process', 'Check', 'motion'}
    shapes = page.findall(f'{{{NS_MAIN}}}Shapes/{{{NS_MAIN}}}Shape')
    assert len(shapes) == 7  # Two subgraphs, three nodes, two connectors.
    connects = page.findall(f'{{{NS_MAIN}}}Connects/{{{NS_MAIN}}}Connect')
    assert len(connects) == 4
    node_ids = {shape.get('ID') for shape in shapes
                if shape.find(f'{{{NS_MAIN}}}Text') is not None
                and shape.find(f'{{{NS_MAIN}}}Text').text in {'Input', 'Process', 'Check'}}
    assert all(connection.get('ToSheet') in node_ids for connection in connects)


def test_mermaid_visio_visual_regressions():
    from mermaid_render import convert

    source = Path(__file__).with_name('fixtures').joinpath('visio-regressions.mmd').read_text()
    with ZipFile(BytesIO(convert(source, format='vsdx', theme='default'))) as archive:
        page = ET.fromstring(archive.read('visio/pages/page1.xml'))
    ns = {'v': NS_MAIN}
    shapes = page.findall('v:Shapes/v:Shape', ns)
    labels = {s.findtext('v:Text', namespaces=ns): s for s in shapes}
    for label, shape in labels.items():
        if label:
            connector = shape.get('NameU').startswith('Connector')
            background = shape.find("v:Cell[@N='TextBkgnd']", ns).get('V')
            assert background != '0' if connector else background == '0'
            assert shape.find("v:Cell[@N='TextBkgndTrans']", ns).get('V') == ('0' if connector else '1')
    assert 'First\nline' in labels
    start = labels['Start']
    assert start.find("v:Cell[@N='FillForegnd']", ns).get('V') == '#ECECFF'
    assert start.find("v:Section[@N='Character']/v:Row/v:Cell[@N='Color']", ns).get('V') == '#333333'
    group = labels['Inputs']
    assert shapes[0] is group
    title_y = float(group.find("v:Cell[@N='TxtPinY']", ns).get('V'))
    height = float(group.find("v:Cell[@N='Height']", ns).get('V'))
    assert title_y > height * 0.8
    assert len(labels['Database'].findall("v:Section[@N='Geometry']", ns)) == 2
    assert len(labels['Hexagon'].findall("v:Section[@N='Geometry']/v:Row", ns)) == 7
    links = page.findall('v:Connects/v:Connect', ns)
    assert len(links) == 8
    retry_id = labels['retry'].get('ID')
    retry_links = [link for link in links if link.get('FromSheet') == retry_id]
    assert len(retry_links) == 2
    assert {link.get('ToSheet') for link in retry_links} == {labels['Hexagon'].get('ID')}
    # Self-loop labels belong outside the box rather than over its own text.
    cells = {c.get('N'): float(c.get('V')) for c in labels['retry'].findall('v:Cell', ns)
             if c.get('N') in {'TxtPinX', 'TxtPinY', 'PinY', 'LocPinX', 'LocPinY', 'Angle'}}
    label_page_y = (cells['PinY'] + (cells['TxtPinX']-cells['LocPinX'])*sin(cells['Angle'])
                    + (cells['TxtPinY']-cells['LocPinY'])*cos(cells['Angle']))
    hexagon = labels['Hexagon']
    hex_top = (float(hexagon.find("v:Cell[@N='PinY']", ns).get('V'))
               + float(hexagon.find("v:Cell[@N='Height']", ns).get('V')) / 2)
    assert label_page_y > hex_top


@pytest.mark.parametrize('routing', ['right-angle', 'straight', 'mermaid'])
def test_application_flow_expanded_shapes_and_theme(routing):
    from mermaid_render import convert

    source = Path(__file__).with_name('fixtures').joinpath('application-flow.mmd').read_text()
    with ZipFile(BytesIO(convert(source, format='vsdx', visio_connectors=routing))) as archive:
        page = ET.fromstring(archive.read('visio/pages/page1.xml'))
    ns = {'v': NS_MAIN}
    shapes = page.findall('v:Shapes/v:Shape', ns)
    assert len(shapes) == 12  # Every stacked glyph remains ONE editable node.
    assert len(page.findall('v:Connects/v:Connect', ns)) == 12
    for shape in shapes[:3]:
        assert len(shape.findall("v:Section[@N='Geometry']/v:Row", ns)) > 5
    # The top port of manual input meets its sloped top, not its bounding box.
    top_y = shapes[0].find("v:Section[@N='Connection']/v:Row[@IX='1']/v:Cell[@N='Y']", ns)
    height = float(shapes[0].find("v:Cell[@N='Height']", ns).get('V'))
    assert 0 < float(top_y.get('V')) < height
    labels = {s.findtext('v:Text', namespaces=ns): s for s in shapes}
    for label in ['Yes', 'No']:
        edge = labels[label]
        assert edge.find("v:Cell[@N='LineColor']", ns).get('V') == '#000000'
        background = edge.find("v:Cell[@N='TextBkgnd']", ns)
        assert background.get('V') == '#CCCCCC'
        assert background.get('F') == 'RGB(204,204,204)+1'
        assert edge.find("v:Cell[@N='TextBkgndTrans']", ns).get('V') == '0'
    # The return arrow keeps its route outside the column of boxes.
    route = labels['No'].findall("v:Section[@N='Geometry']/v:Row", ns)
    if routing == 'mermaid':
        assert len(route) > 10
        assert any(row.get('T') == 'RelQuadBezTo' for row in route)
    else:
        assert len(route) == (6 if routing == 'right-angle' else 2)
        assert all(row.get('T') in {'MoveTo', 'LineTo'} for row in route)
        assert labels['No'].find("v:Cell[@N='ShapeRouteStyle']", ns).get('V') == ('1' if routing == 'right-angle' else '2')
        for connector in shapes[6:]:
            cells = {c.get('N'): float(c.get('V')) for c in connector.findall('v:Cell', ns)
                     if c.get('N') in {'Angle', 'ConFixedCode'}}
            assert cells['ConFixedCode'] == 0
            rows = connector.findall("v:Section[@N='Geometry']/v:Row", ns)
            points = []
            for row in rows:
                x = float(row.find("v:Cell[@N='X']", ns).get('V'))
                y = float(row.find("v:Cell[@N='Y']", ns).get('V'))
                points.append((x*cos(cells['Angle'])-y*sin(cells['Angle']),
                               x*sin(cells['Angle'])+y*cos(cells['Angle'])))
            if routing == 'right-angle':
                assert all(abs(a[0]-b[0]) < 1e-5 or abs(a[1]-b[1]) < 1e-5
                           for a, b in zip(points, points[1:]))
            else:
                assert len(points) == 2
    # Both arrows at the upper diamond sides use SVG attachment points,
    # rather than being forced onto its top vertex.
    decision = next(s for label, s in labels.items() if label and label.replace('\n', ' ') == 'Application approved?')
    width = float(decision.find("v:Cell[@N='Width']", ns).get('V'))
    height = float(decision.find("v:Cell[@N='Height']", ns).get('V'))
    ports = decision.findall("v:Section[@N='Connection']/v:Row", ns)[4:]
    # Standard right/top/left/bottom connection points remain available too.
    standard = decision.findall("v:Section[@N='Connection']/v:Row", ns)[:4]
    expected = [(width, height/2), (width/2, height), (0, height/2), (width/2, 0)]
    for row, (x, y) in zip(standard, expected):
        assert float(row.find("v:Cell[@N='X']", ns).get('V')) == pytest.approx(x, abs=1e-6)
        assert float(row.find("v:Cell[@N='Y']", ns).get('V')) == pytest.approx(y, abs=1e-6)
    upper = [row for row in ports if float(row.find("v:Cell[@N='Y']", ns).get('V')) > height / 2]
    assert len(upper) == 2
    for row in upper:
        x = float(row.find("v:Cell[@N='X']", ns).get('V')) / width
        y = float(row.find("v:Cell[@N='Y']", ns).get('V')) / height
        assert abs(x - 0.5) > 0.05
        # Mermaid leaves a small gap between the arrow tip and the outline.
        assert abs(x - 0.5) + abs(y - 0.5) == pytest.approx(0.5, abs=0.04)


@pytest.mark.parametrize('theme', ['redux-color', 'default'])
def test_explicit_theme_overrides_default(theme):
    from mermaid_render import convert

    svg = convert('flowchart LR; A[Input] --> B[Output]', theme=theme).decode()
    assert ('#ECECFF' in svg) == (theme == 'default')


def test_dagre_basis_connectors_preserve_cubic_curves():
    from mermaid_render import convert

    source = '''---
config:
  layout: dagre
  flowchart:
    curve: basis
---
flowchart TD
    A --> B
    A --> C
    B --> D
    C --> D
'''
    with ZipFile(BytesIO(convert(source, format='vsdx', visio_connectors='mermaid'))) as archive:
        page = ET.fromstring(archive.read('visio/pages/page1.xml'))
    ns = {'v': NS_MAIN}
    assert page.findall("v:Shapes/v:Shape/v:Section[@N='Geometry']/v:Row[@T='RelCubBezTo']", ns)
    assert len(page.findall('v:Connects/v:Connect', ns)) == 8
