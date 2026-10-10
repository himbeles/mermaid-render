from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from mermaid_render.vsdx import CoordinateSpace, NS_MAIN, build_vsdx


def sample_list():
    return {
        "width": 200,
        "height": 120,
        "items": [
            {"kind": "poly", "points": [[10, 10], [90, 10], [90, 50], [10, 50]],
             "closed": True, "fill": "#DBEAFE", "stroke": "#1E3A8A", "strokeWidthPx": 1, "dash": False},
            {"kind": "poly", "points": [[50, 50], [50, 90]],
             "closed": False, "fill": None, "stroke": "#333333", "strokeWidthPx": 1.5, "dash": False},
            {"kind": "text", "text": "geo_key PK", "x": 14, "y": 14, "width": 60, "height": 14,
             "fontPx": 14, "fontFamily": "Arial", "bold": True, "italic": False,
             "anchor": "start", "fill": "#000000"},
        ],
    }


def test_coordinate_space():
    s = CoordinateSpace([(0, 0), (96, 192)], margin_px=0)
    assert abs(s.page_width - 1) < 1e-6
    assert abs(s.page_height - 2) < 1e-6
    assert s.point(0, 0) == (0, 2)
    assert s.point(96, 192) == (1, 0)


def test_vsdx_contains_editable_shapes():
    data = build_vsdx(sample_list(), title="Unit & Test")
    with ZipFile(BytesIO(data)) as z:
        assert z.testzip() is None
        assert len(z.namelist()) == 10
        for filename in z.namelist():
            if filename.endswith(".xml") or filename.endswith(".rels"):
                ET.fromstring(z.read(filename))
        contents = ET.fromstring(z.read("visio/pages/page1.xml"))
        shapes = contents.findall(f".//{{{NS_MAIN}}}Shape")
        assert len(shapes) == 3
        fill_cells = shapes[0].findall(f".//{{{NS_MAIN}}}Cell")
        assert any(c.get("N") == "FillForegnd" and c.get("V") == "#DBEAFE" for c in fill_cells)
        texts = shapes[2].findall(f".//{{{NS_MAIN}}}Text")
        assert len(texts) == 1 and texts[0].text == "geo_key PK"
        # Readers such as libvisio reject decimal strings in integer flags.
        for key in ['FillPattern', 'LinePattern', 'VerticalAlign', 'TextDirection', 'TextBkgnd']:
            assert shapes[2].find(f"{{{NS_MAIN}}}Cell[@N='{key}']").get('V').isdigit()
        assert z.read("docProps/core.xml").find(b"Unit &amp; Test") >= 0
        assert b"image/png" not in b"".join(z.read(n) for n in z.namelist())


def test_skip_invalid_empty_items():
    data = build_vsdx({"width": 10, "height": 10, "items": [
        {"kind": "text", "text": " ", "x": 0, "y": 0, "width": 1, "height": 1},
        {"kind": "poly", "points": [[0, 0]], "closed": False},
    ]})
    with ZipFile(BytesIO(data)) as z:
        contents = ET.fromstring(z.read("visio/pages/page1.xml"))
        assert not contents.findall(f".//{{{NS_MAIN}}}Shape")


def test_supports_xml_special_characters():
    data = build_vsdx({"width": 1, "height": 1, "items": [
        {"kind": "text", "text": "A < B & C", "x": 0, "y": 0,
         "width": 10, "height": 10, "fontPx": 12, "fill": "#FF0000"},
    ]})
    with ZipFile(BytesIO(data)) as z:
        xml = z.read("visio/pages/page1.xml")
        assert b"A &lt; B &amp; C" in xml
        ET.fromstring(xml)
