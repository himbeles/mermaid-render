"""Platform-independent Visio ShapeSheet connector writer.

Accepts positioned Mermaid flowchart nodes and semantic source/target edges;
creates native Visio 2D shapes, 1D connector shapes and glue records.
Visio desktop behavior on opening/editing generated files is not yet verified.
No Office, COM, or platform-specific API is used.
"""

from __future__ import annotations

from io import BytesIO
from math import atan2, hypot, isfinite
from typing import Any, Mapping, Sequence
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from .vsdx import CoordinateSpace, PX_TO_IN, _parts, cell, number, tag, xml_bytes


# Sections are enumerated starting at zero; Visio displays them as X1..X4.
# Right, top, left, bottom in the node's local coordinate system.
_PORTS = {
    "right": (0, 1.0, 0.5),
    "top": (1, 0.5, 1.0),
    "left": (2, 0.0, 0.5),
    "bottom": (3, 0.5, 0.0),
}


def _cell(parent: ET.Element, name: str, value: float | int | str, formula: str | None = None) -> None:
    attrs = {"N": name, "V": number(value) if isinstance(value, (int, float)) else value}
    if formula is not None:
        attrs["F"] = formula
    ET.SubElement(parent, tag("Cell"), attrs)


def _validate(nodes: Sequence[Mapping[str, Any]], edges: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    indexed = {}
    for node in nodes:
        key = str(node["id"])
        if not key or key in indexed:
            raise ValueError(f"Node ID empty or duplicated: {key!r}")
        if (not all(isfinite(float(node[k])) for k in ("x", "y", "width", "height"))
                or float(node["width"]) <= 0 or float(node["height"]) <= 0):
            raise ValueError(f"Node dimensions invalid: {key}")
        indexed[key] = node
    for edge in edges:
        a, b = str(edge["source"]), str(edge["target"])
        if a not in indexed or b not in indexed:
            raise ValueError(f"Unknown edge endpoint: {a!r} -> {b!r}")
        if a == b:
            raise ValueError("Self loops not yet supported")
    return indexed


def _node_shape(parent: ET.Element, index: int, node: Mapping[str, Any], space: CoordinateSpace) -> None:
    x, y, w, h = (float(node[k]) for k in ("x", "y", "width", "height"))
    cx, cy = space.point(x + w / 2, y + h / 2)
    w, h = w * PX_TO_IN, h * PX_TO_IN
    shape = ET.SubElement(parent, tag("Shape"), {"ID": str(index), "NameU": f"Node{index}", "Type": "Shape"})
    for key, value in (("PinX", cx), ("PinY", cy), ("Width", w), ("Height", h),
                       ("LocPinX", w / 2), ("LocPinY", h / 2),
                       ("Angle", 0), ("FillForegnd", str(node.get("fill", "#E5EFFA"))),
                       ("FillPattern", 1), ("LineColor", str(node.get("stroke", "#4472C4"))),
                       ("LineWeight", 0.012), ("LinePattern", 1),
                       ("VerticalAlign", 1), ("ObjType", 1)):
        _cell(shape, key, value)
    geometry = ET.SubElement(shape, tag("Section"), {"N": "Geometry", "IX": "0"})
    kind = str(node.get("shape", "rect")).lower()
    if kind in {"decision", "diamond", "rhombus", "question"}:
        outline = ((w/2, 0), (w, h/2), (w/2, h), (0, h/2), (w/2, 0))
    elif kind in {"circle", "ellipse", "doublecircle", "start", "end"}:
        from math import cos, sin, pi
        outline = tuple((w/2+(w/2)*cos(2*pi*i/48), h/2+(h/2)*sin(2*pi*i/48)) for i in range(49))
    else:
        outline = ((0, 0), (w, 0), (w, h), (0, h), (0, 0))
    for i, (xx, yy) in enumerate(outline):
        row = ET.SubElement(geometry, tag("Row"), {"IX": str(i + 1), "T": "MoveTo" if i == 0 else "LineTo"})
        _cell(row, "X", xx)
        _cell(row, "Y", yy)

    ports = ET.SubElement(shape, tag("Section"), {"N": "Connection"})
    for port, (ix, fx, fy) in _PORTS.items():
        row = ET.SubElement(ports, tag("Row"), {"IX": str(ix)})
        _cell(row, "X", w * fx, f"Width*{fx}" if fx != 0 else "0")
        _cell(row, "Y", h * fy, f"Height*{fy}" if fy != 0 else "0")
        _cell(row, "DirX", 0)
        _cell(row, "DirY", 0)
        _cell(row, "Type", 0)

    text = str(node.get("text", node["id"]))
    if text:
        char = ET.SubElement(shape, tag("Section"), {"N": "Character"})
        row = ET.SubElement(char, tag("Row"), {"IX": "0"})
        _cell(row, "Color", str(node.get("font_color", "#172D4A")))
        _cell(row, "Size", float(node.get("font_size", 14)) * PX_TO_IN)
        para = ET.SubElement(shape, tag("Section"), {"N": "Paragraph"})
        row = ET.SubElement(para, tag("Row"), {"IX": "0"})
        _cell(row, "HorzAlign", 1)
        ET.SubElement(shape, tag("Text")).text = text


def _port(a: Mapping[str, Any], b: Mapping[str, Any]) -> tuple[str, str]:
    ax = float(a["x"]) + float(a["width"]) / 2
    ay = float(a["y"]) + float(a["height"]) / 2
    bx = float(b["x"]) + float(b["width"]) / 2
    by = float(b["y"]) + float(b["height"]) / 2
    if abs(bx - ax) >= abs(by - ay):
        return ("right", "left") if bx >= ax else ("left", "right")
    return ("bottom", "top") if by >= ay else ("top", "bottom")


def _anchor(node: Mapping[str, Any], side: str) -> tuple[float, float]:
    _, px, py = _PORTS[side]
    return float(node["x"]) + float(node["width"]) * px, float(node["y"]) + float(node["height"]) * (1 - py)


def _connector(parent: ET.Element, connects: ET.Element, id: int, edge: Mapping[str, Any],
               ids: Mapping[str, int], nodes: Mapping[str, Mapping[str, Any]], space: CoordinateSpace) -> None:
    source, target = str(edge["source"]), str(edge["target"])
    s_side, t_side = _port(nodes[source], nodes[target])
    x0, y0 = space.point(*_anchor(nodes[source], s_side))
    x1, y1 = space.point(*_anchor(nodes[target], t_side))
    dist = hypot(x1 - x0, y1 - y0)
    angle = atan2(y1 - y0, x1 - x0)
    shape = ET.SubElement(parent, tag("Shape"), {"ID": str(id), "NameU": f"Connector{id}", "Type": "Shape"})
    for field, xy, node, side in (("Begin", (x0, y0), source, s_side),
                                  ("End", (x1, y1), target, t_side)):
        ix = _PORTS[side][0] + 1
        # Visio uses a point expression in the X/Y endpoint cells for a glued 1D shape.
        ref = f"Sheet.{ids[node]}!Connections"
        formula = f"PAR(PNT({ref}.X{ix},{ref}.Y{ix}))"
        _cell(shape, field + "X", xy[0], formula)
        _cell(shape, field + "Y", xy[1], formula)
        ET.SubElement(connects, tag("Connect"), {
            "FromSheet": str(id), "FromCell": field + "X", "FromPart": "9" if field == "Begin" else "12",
            "ToSheet": str(ids[node]), "ToCell": f"Connections.X{ix}",
        })
    for key, value in (("PinX", (x0 + x1) / 2), ("PinY", (y0 + y1) / 2),
                       ("LocPinX", dist / 2), ("LocPinY", 0),
                       ("Width", dist), ("Height", 0), ("Angle", angle),
                       ("ObjType", 2), ("FillPattern", 0),
                       ("LinePattern", 1), ("LineColor", str(edge.get("stroke", "#4472C4"))),
                       ("LineWeight", 0.012), ("LinePattern", 2 if edge.get("dash") else 1),
                       ("BeginArrow", 13 if edge.get("start_arrow") else 0),
                       ("EndArrow", 13 if edge.get("arrow", True) else 0)):
        _cell(shape, key, value)
    label = str(edge.get("text", "")).strip()
    if label:
        char = ET.SubElement(shape, tag("Section"), {"N": "Character"})
        row = ET.SubElement(char, tag("Row"), {"IX": "0"})
        _cell(row, "Color", "#172D4A")
        _cell(row, "Size", 12 * PX_TO_IN)
        para = ET.SubElement(shape, tag("Section"), {"N": "Paragraph"})
        row = ET.SubElement(para, tag("Row"), {"IX": "0"})
        _cell(row, "HorzAlign", 1)
        ET.SubElement(shape, tag("Text")).text = label
    geo = ET.SubElement(shape, tag("Section"), {"N": "Geometry", "IX": "0"})
    _cell(geo, "NoFill", 1)
    row = ET.SubElement(geo, tag("Row"), {"T": "MoveTo", "IX": "1"})
    _cell(row, "X", 0)
    _cell(row, "Y", 0)
    row = ET.SubElement(geo, tag("Row"), {"T": "LineTo", "IX": "2"})
    _cell(row, "X", dist, "Width")
    _cell(row, "Y", 0)


def build_connected_vsdx(nodes: Sequence[Mapping[str, Any]], edges: Sequence[Mapping[str, Any]],
                         *, title: str = "Connected Visio Diagram") -> bytes:
    """Generate a Visio VSDX with glued 1D connectors and positioned nodes.

    Node coordinates are in SVG pixels with top-left origin:
      {"id":"a", "x":10, "y":10, "width":120, "height":50, "text":"A"}
    Edges: {"source":"a", "target":"b"}. Output is OS-independent.
    Visio connector behavior remains untested with the actual Visio application.
    """
    indexed = _validate(nodes, edges)
    points = [(float(n["x"]), float(n["y"])) for n in nodes]
    points += [(float(n["x"]) + float(n["width"]), float(n["y"]) + float(n["height"])) for n in nodes]
    space = CoordinateSpace(points)
    contents = ET.Element(tag("PageContents"), {"{http://www.w3.org/XML/1998/namespace}space": "preserve"})
    shapes = ET.SubElement(contents, tag("Shapes"))
    connects = ET.Element(tag("Connects"))
    ids = {str(n["id"]): i for i, n in enumerate(nodes, start=1)}
    for i, node in enumerate(nodes, start=1):
        _node_shape(shapes, i, node, space)
    for i, edge in enumerate(edges, start=len(nodes) + 1):
        _connector(shapes, connects, i, edge, ids, indexed, space)
    if len(connects):
        contents.append(connects)
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in _parts(xml_bytes(contents), space.page_width, space.page_height, title).items():
            archive.writestr(name, data)
    return output.getvalue()
