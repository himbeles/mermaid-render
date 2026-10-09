"""Pure-Python equivalent of FBklyra/mermaid-to-visio's VSDX writer.

A display list is a mapping with ``width``, ``height`` and ``items`` keys.
The items are ``kind: poly`` or ``kind: text`` dictionaries. This preserves
an exchange format independent of the browser capture implementation.
"""

from __future__ import annotations

from io import BytesIO
from math import isfinite
from typing import Any, Mapping
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

NS_MAIN = "http://schemas.microsoft.com/office/visio/2012/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
ET.register_namespace("", NS_MAIN)
ET.register_namespace("r", NS_R)
PX_TO_IN = 1 / 96
MIN_LINE_WEIGHT_IN = 0.0069


def tag(name: str) -> str:
    return f"{{{NS_MAIN}}}{name}"


def number(value: float) -> str:
    if not isfinite(float(value)):
        raise ValueError("Coordinates and dimensions must be finite")
    return str(round(float(value), 6))


def cell(parent: ET.Element, name: str, value: Any) -> ET.Element:
    return ET.SubElement(parent, tag("Cell"), {"N": name, "V": str(value)})


def xml_bytes(root: ET.Element) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


class CoordinateSpace:
    def __init__(self, points: list[tuple[float, float]], margin_px: float = 16):
        if not points:
            points = [(0, 0), (1, 1)]
        self.min_x = min(x for x, _ in points) - margin_px
        self.max_y = max(y for _, y in points) + margin_px
        self.page_width = (max(x for x, _ in points) - min(x for x, _ in points) + 2 * margin_px) * PX_TO_IN
        self.page_height = (max(y for _, y in points) - min(y for _, y in points) + 2 * margin_px) * PX_TO_IN

    def point(self, x: float, y: float) -> tuple[float, float]:
        return (round((x - self.min_x) * PX_TO_IN, 6), round((self.max_y - y) * PX_TO_IN, 6))


def _space_for(items: list[dict], width: float, height: float) -> CoordinateSpace:
    points = []
    for item in items:
        if item["kind"] == "poly":
            points.extend((float(p["x"]), float(p["y"])) if isinstance(p, dict) else (float(p[0]), float(p[1])) for p in item["points"])
        elif item["kind"] == "text":
            x, y = float(item["x"]), float(item["y"])
            points.extend(((x, y), (x + float(item["width"]), y + float(item["height"]))))
    return CoordinateSpace(points if points else [(0, 0), (width or 1, height or 1)])


def _shape_geometry(parent: ET.Element, item: dict, space: CoordinateSpace) -> None:
    p = [space.point(pt["x"], pt["y"]) if isinstance(pt, dict) else space.point(*pt) for pt in item["points"]]
    x0, x1 = min(x for x, _ in p), max(x for x, _ in p)
    y0, y1 = min(y for _, y in p), max(y for _, y in p)
    width, height = max(x1 - x0, 0.001), max(y1 - y0, 0.001)

    for n, v in (("PinX", (x0 + x1) / 2), ("PinY", (y0 + y1) / 2),
                 ("Width", width), ("Height", height),
                 ("LocPinX", width / 2), ("LocPinY", height / 2), ("Angle", 0)):
        cell(parent, n, number(v))

    fill, stroke = item.get("fill"), item.get("stroke")
    if fill:
        cell(parent, "FillForegnd", fill)
        cell(parent, "FillPattern", "1")
    else:
        cell(parent, "FillPattern", "0")
    if stroke:
        cell(parent, "LineColor", stroke)
        w = max(float(item.get("strokeWidthPx", item.get("stroke_width", 1))) * PX_TO_IN, MIN_LINE_WEIGHT_IN)
        cell(parent, "LineWeight", number(w))
        cell(parent, "LinePattern", "2" if item.get("dash") else "1")
        if item.get("beginArrow"):
            cell(parent, "BeginArrow", "13")
        if item.get("endArrow"):
            cell(parent, "EndArrow", "13")
    else:
        cell(parent, "LinePattern", "0")

    section = ET.SubElement(parent, tag("Section"), {"N": "Geometry", "IX": "0"})
    cell(section, "NoFill", "0" if fill else "1")
    cell(section, "NoLine", "0" if stroke else "1")
    for i, (x, y) in enumerate(p):
        row = ET.SubElement(section, tag("Row"), {"T": "MoveTo" if i == 0 else "LineTo", "IX": str(i + 1)})
        cell(row, "X", number(x - x0))
        cell(row, "Y", number(y - y0))
    if item.get("closed"):
        row = ET.SubElement(section, tag("Row"), {"T": "LineTo", "IX": str(len(p) + 1)})
        cell(row, "X", number(p[0][0] - x0))
        cell(row, "Y", number(p[0][1] - y0))


def _shape_text(parent: ET.Element, item: dict, space: CoordinateSpace) -> None:
    left, top = space.point(float(item["x"]), float(item["y"]))
    right, bottom = space.point(float(item["x"]) + float(item["width"]), float(item["y"]) + float(item["height"]))
    width, height = max(abs(right - left), 0.02), max(abs(top - bottom), 0.02)
    for n, v in (("PinX", (left + right) / 2), ("PinY", (top + bottom) / 2),
                 ("Width", width), ("Height", height), ("LocPinX", width / 2),
                 ("LocPinY", height / 2), ("Angle", 0), ("FillPattern", 0),
                 ("LinePattern", 0), ("VerticalAlign", 1), ("TextDirection", 0)):
        cell(parent, n, number(v))

    char_section = ET.SubElement(parent, tag("Section"), {"N": "Character"})
    char_row = ET.SubElement(char_section, tag("Row"), {"IX": "0"})
    cell(char_row, "Color", item.get("fill") or "#000000")
    cell(char_row, "Size", number(float(item.get("fontPx", 12)) * PX_TO_IN))
    cell(char_row, "Style", str(int(bool(item.get("bold"))) | (int(bool(item.get("italic"))) << 1)))
    para_section = ET.SubElement(parent, tag("Section"), {"N": "Paragraph"})
    para_row = ET.SubElement(para_section, tag("Row"), {"IX": "0"})
    cell(para_row, "HorzAlign", {"start": "0", "middle": "1", "end": "2"}.get(item.get("anchor", "start"), "0"))
    ET.SubElement(parent, tag("Text")).text = item["text"]


def _simple_xml(xml: str) -> bytes:
    return xml.encode("utf-8")


def _parts(page_contents: bytes, page_width: float, page_height: float, title: str) -> dict[str, bytes]:
    from xml.sax.saxutils import escape
    w, h = number(page_width), number(page_height)
    title = escape(title)
    return {
        "[Content_Types].xml": _simple_xml(f'''<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="{NS_CT}">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/visio/document.xml" ContentType="application/vnd.ms-visio.drawing.main+xml"/>
<Override PartName="/visio/pages/pages.xml" ContentType="application/vnd.ms-visio.pages+xml"/>
<Override PartName="/visio/pages/page1.xml" ContentType="application/vnd.ms-visio.page+xml"/>
<Override PartName="/visio/windows.xml" ContentType="application/vnd.ms-visio.windows+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>'''),
        "_rels/.rels": _simple_xml(f'''<Relationships xmlns="{NS_REL}">
<Relationship Id="rId1" Type="http://schemas.microsoft.com/visio/2010/relationships/document" Target="visio/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>'''),
        "docProps/core.xml": _simple_xml(f'''<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{title}</dc:title><dc:creator>mermaid-render</dc:creator></cp:coreProperties>'''),
        "docProps/app.xml": _simple_xml('''<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>Mermaid Visio Export</Application></Properties>'''),
        "visio/document.xml": _simple_xml(f'''<VisioDocument xmlns="{NS_MAIN}" xmlns:r="{NS_R}" xml:space="preserve"><DocumentSettings TopPage="0" DefaultTextStyle="0" DefaultLineStyle="0" DefaultFillStyle="0" DefaultGuideStyle="0"/><Colors/><FaceNames/><StyleSheets/></VisioDocument>'''),
        "visio/_rels/document.xml.rels": _simple_xml(f'''<Relationships xmlns="{NS_REL}"><Relationship Id="rId1" Type="http://schemas.microsoft.com/visio/2010/relationships/pages" Target="pages/pages.xml"/><Relationship Id="rId2" Type="http://schemas.microsoft.com/visio/2010/relationships/windows" Target="windows.xml"/></Relationships>'''),
        "visio/windows.xml": _simple_xml(f'''<Windows xmlns="{NS_MAIN}" xmlns:r="{NS_R}" ClientWidth="1000" ClientHeight="800"/>'''),
        "visio/pages/pages.xml": _simple_xml(f'''<Pages xmlns="{NS_MAIN}" xmlns:r="{NS_R}" xml:space="preserve"><Page ID="0" NameU="Page-1" Name="Page-1" ViewScale="-1" ViewCenterX="{number(page_width / 2)}" ViewCenterY="{number(page_height / 2)}"><PageSheet><Cell N="PageWidth" V="{w}"/><Cell N="PageHeight" V="{h}"/><Cell N="ShdwOffsetX" V="0.1181"/><Cell N="ShdwOffsetY" V="-0.1181"/><Cell N="PageScale" V="1"/><Cell N="DrawingScale" V="1"/><Cell N="DrawingSizeType" V="3"/><Cell N="DrawingScaleType" V="0"/></PageSheet><Rel r:id="rId1"/></Page></Pages>'''),
        "visio/pages/_rels/pages.xml.rels": _simple_xml(f'''<Relationships xmlns="{NS_REL}"><Relationship Id="rId1" Type="http://schemas.microsoft.com/visio/2010/relationships/page" Target="page1.xml"/></Relationships>'''),
        "visio/pages/page1.xml": page_contents,
    }


def build_vsdx(display_list: Mapping[str, Any], *, title: str = "Mermaid Diagram") -> bytes:
    """Build a native Visio file from a renderer display list.

    Polygons/text become separate editable Visio ShapeSheet objects; paths are
    **not** glued semantic Visio connectors, matching the source project's
    geometry-first conversion behavior.
    """
    items = list(display_list.get("items", []))
    space = _space_for(items, float(display_list.get("width", 0)), float(display_list.get("height", 0)))
    contents = ET.Element(tag("PageContents"), {f"{{http://www.w3.org/XML/1998/namespace}}space": "preserve"})
    shapes = ET.SubElement(contents, tag("Shapes"))
    next_id = 1
    for item in items:
        if item["kind"] == "poly" and len(item.get("points", [])) >= 2:
            shape = ET.SubElement(shapes, tag("Shape"), {"ID": str(next_id), "Type": "Shape"})
            _shape_geometry(shape, item, space)
        elif item["kind"] == "text" and str(item.get("text", "")).strip():
            shape = ET.SubElement(shapes, tag("Shape"), {"ID": str(next_id), "Type": "Shape"})
            _shape_text(shape, item, space)
        else:
            continue
        next_id += 1

    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as z:
        for path, data in _parts(xml_bytes(contents), space.page_width, space.page_height, title).items():
            z.writestr(path, data)
    return output.getvalue()
