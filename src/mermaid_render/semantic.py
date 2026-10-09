"""Platform-independent Visio ShapeSheet connector writer.

Accepts positioned Mermaid flowchart nodes and semantic source/target edges;
creates native Visio 2D shapes, 1D connector shapes and glue records.
Visio desktop behavior on opening/editing generated files is not yet verified.
No Office, COM, or platform-specific API is used.
"""

from __future__ import annotations

from io import BytesIO
from math import atan2, cos, hypot, isfinite, pi, sin
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
_NATIVE_KINDS = {
    'rect', 'squarerect', 'roundedrect', 'round', 'rounded', 'rounded-rectangle',
    'stadium', 'pill', 'terminal', 'decision', 'diamond', 'diam', 'rhombus', 'question',
    'hexagon', 'hex', 'prepare', 'cylinder', 'cyl', 'database',
    'circle', 'ellipse', 'doublecircle', 'start', 'end',
}


def _captured(node: Mapping[str, Any]) -> bool:
    return str(node.get('shape', 'rect')).lower() not in _NATIVE_KINDS and 'outlines' in node


def _cell(parent: ET.Element, name: str, value: float | int | str, formula: str | None = None) -> None:
    # Keep integer flags in Visio's canonical form. diagrams.net compares
    # geometry booleans such as NoFill to the literal "1", not "1.0".
    serialized = str(value) if isinstance(value, int) else number(value) if isinstance(value, float) else value
    attrs = {"N": name, "V": serialized}
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
    if kind in {"roundedrect", "round", "rounded", "rounded-rectangle"}:
        radius = float(node.get("corner_radius") or 5) * PX_TO_IN
        _cell(shape, "Rounding", min(radius, w / 2, h / 2))
    elif kind in {"stadium", "pill", "terminal"}:
        _cell(shape, "Rounding", min(w, h) / 2, "MIN(Width,Height)*0.5")
    if kind in {"decision", "diamond", "diam", "rhombus", "question"}:
        outline = ((w/2, 0), (w, h/2), (w/2, h), (0, h/2), (w/2, 0))
    elif kind in {"hexagon", "hex", "prepare"}:
        inset = min(w / 4, h / 3)
        outline = ((inset, 0), (w-inset, 0), (w, h/2), (w-inset, h), (inset, h), (0, h/2), (inset, 0))
    elif kind in {"cylinder", "cyl", "database"}:
        ry = min(h / 6, w / 8)
        bottom = tuple((w/2+w/2*cos(pi+i*pi/24), ry+ry*sin(pi+i*pi/24)) for i in range(25))
        top = tuple((w/2+w/2*cos(i*pi/24), h-ry+ry*sin(i*pi/24)) for i in range(25))
        outline = bottom + top + (bottom[0],)
    elif kind in {"circle", "ellipse", "doublecircle", "start", "end"}:
        outline = tuple((w/2+(w/2)*cos(2*pi*i/48), h/2+(h/2)*sin(2*pi*i/48)) for i in range(49))
    else:
        outline = ((0, 0), (w, 0), (w, h), (0, h), (0, 0))
    for i, (xx, yy) in enumerate(outline):
        row = ET.SubElement(geometry, tag("Row"), {"IX": str(i + 1), "T": "MoveTo" if i == 0 else "LineTo"})
        _cell(row, "X", xx)
        _cell(row, "Y", yy)

    if kind in {"cylinder", "cyl", "database"}:
        rim = ET.SubElement(shape, tag("Section"), {"N": "Geometry", "IX": "1"})
        _cell(rim, "NoFill", 1)
        for i in range(25):
            row = ET.SubElement(rim, tag("Row"), {"IX": str(i + 1), "T": "MoveTo" if i == 0 else "LineTo"})
            _cell(row, "X", w/2+w/2*cos(pi+i*pi/24))
            _cell(row, "Y", h-ry+ry*sin(pi+i*pi/24))

    captured = _captured(node)
    if captured:
        # Preserve complex Mermaid glyphs as sections of ONE editable node,
        # so decorations and stacked sheets move with their glued connectors.
        shape.remove(geometry)
        outlines = []
        for outline in node['outlines']:
            # SVG fills an open subpath implicitly but does not stroke that
            # closing segment. Separate fill/stroke to avoid cylinder diagonals.
            if outline['fill'] and outline['stroke'] and not outline['closed']:
                outlines.extend((dict(outline, stroke=False), dict(outline, fill=False)))
            else:
                outlines.append(outline)
        for ix, outline in enumerate(outlines):
            section = ET.SubElement(shape, tag('Section'), {'N': 'Geometry', 'IX': str(ix)})
            _cell(section, 'NoFill', 0 if outline['fill'] else 1)
            _cell(section, 'NoLine', 0 if outline['stroke'] else 1)
            points = list(outline['points'])
            if outline['closed'] or outline['fill']:
                points.append(points[0])
            for i, point in enumerate(points):
                row = ET.SubElement(section, tag('Row'), {'IX': str(i+1), 'T': 'MoveTo' if i == 0 else 'LineTo'})
                _cell(row, 'X', w*point['x'], f"Width*{number(point['x'])}")
                _cell(row, 'Y', h*point['y'], f"Height*{number(point['y'])}")
        if not node['outlines']:
            _cell(shape, 'FillPattern', 0)
            _cell(shape, 'LinePattern', 0)

    ports = ET.SubElement(shape, tag("Section"), {"N": "Connection"})
    for port, (ix, fx, fy) in _PORTS.items():
        if captured:
            fx, fy = node.get('connection_points', {}).get(port, (fx, fy))
        row = ET.SubElement(ports, tag("Row"), {"T": "Connection", "IX": str(ix)})
        _cell(row, "X", w * fx, f"Width*{fx}" if fx != 0 else "0")
        _cell(row, "Y", h * fy, f"Height*{fy}" if fy != 0 else "0")
        _cell(row, "DirX", 0)
        _cell(row, "DirY", 0)
        _cell(row, "Type", 0)
        _cell(row, "AutoGen", 0)
        _cell(row, "Prompt", "")
    for ix, (fx, fy) in enumerate(node.get('extra_ports', []), start=4):
        row = ET.SubElement(ports, tag('Row'), {'T': 'Connection', 'IX': str(ix)})
        for key, value, formula in (
            ('X', w*fx, f'Width*{number(fx)}'), ('Y', h*fy, f'Height*{number(fy)}'),
            ('DirX', 0, None), ('DirY', 0, None), ('Type', 0, None),
            ('AutoGen', 0, None), ('Prompt', '', None),
        ):
            _cell(row, key, value, formula)

    text = str(node.get("text", node["id"]))
    if text:
        _cell(shape, "TextBkgnd", 0)
        _cell(shape, "TextBkgndTrans", 1)
        bounds = node.get("label_bounds") if node.get("is_group") or captured else None
        if bounds:
            tw, th = float(bounds["width"]) * PX_TO_IN, float(bounds["height"]) * PX_TO_IN
            tx = (float(bounds["x"]) - x) * PX_TO_IN + tw / 2
            ty = h - (float(bounds["y"]) - y) * PX_TO_IN - th / 2
            for key, value in (("TxtPinX", tx), ("TxtPinY", ty), ("TxtWidth", tw + 0.08),
                               ("TxtHeight", th + 0.04), ("TxtLocPinX", (tw + 0.08)/2),
                               ("TxtLocPinY", (th + 0.04)/2)):
                _cell(shape, key, value)
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
    gap_x = abs(bx-ax) - (float(a["width"])+float(b["width"]))/2
    gap_y = abs(by-ay) - (float(a["height"])+float(b["height"]))/2
    # Prefer the separating axis when wide boxes overlap in the other axis.
    # Center distances alone can select a side facing through the destination.
    horizontal = gap_x > 0 if (gap_x > 0) != (gap_y > 0) else abs(bx-ax) >= abs(by-ay)
    if horizontal:
        return ("right", "left") if bx >= ax else ("left", "right")
    return ("bottom", "top") if by >= ay else ("top", "bottom")


def _anchor(node: Mapping[str, Any], side: str) -> tuple[float, float]:
    _, px, py = _PORTS[side]
    # Only captured glyphs use outline-specific ports; native approximations
    # retain their own corresponding cardinal points.
    if _captured(node):
        px, py = node.get('connection_points', {}).get(side, (px, py))
    return float(node["x"]) + float(node["width"]) * px, float(node["y"]) + float(node["height"]) * (1 - py)


def _right_angle_route(edge: Mapping[str, Any], start: tuple[float, float],
                       end: tuple[float, float], space: CoordinateSpace) -> list[tuple[float, float]]:
    """Recover ELK's sparse orthogonal skeleton, removing rounded corners.

    A quadratic rounded corner's control point is the original rectangular
    bend. Cubic/custom curves instead get a short orthogonal route.
    """
    segments = edge.get('segments') or []
    points = [start]
    if segments and all(s['type'] in {'M', 'L', 'Q'} for s in segments):
        points += [space.point(float(p['x']), float(p['y']))
                   for segment in segments[1:] for p in segment['points']]
        points[-1] = end
    else:
        points.append(end)
    tolerance = 0.05 * PX_TO_IN
    if len(points) == 2 or any(abs(b[0]-a[0]) > tolerance and abs(b[1]-a[1]) > tolerance
                               for a, b in zip(points, points[1:])):
        # Follow the SVG's exit/entry axes when available; preserve attachment
        # points even when the original curve is not an orthogonal ELK route.
        sampled = edge.get('route') or []
        vertical_start = abs(end[1]-start[1]) >= abs(end[0]-start[0])
        vertical_end = vertical_start
        if len(sampled) > 1:
            a, b = sampled[0], sampled[1]
            vertical_start = abs(b['y']-a['y']) >= abs(b['x']-a['x'])
            a, b = sampled[-2], sampled[-1]
            vertical_end = abs(b['y']-a['y']) >= abs(b['x']-a['x'])
        if vertical_start != vertical_end:
            bends = [(start[0], end[1])] if vertical_start else [(end[0], start[1])]
        elif vertical_start:
            middle = (start[1]+end[1])/2
            bends = [(start[0], middle), (end[0], middle)]
        else:
            middle = (start[0]+end[0])/2
            bends = [(middle, start[1]), (middle, end[1])]
        points = [start, *bends, end]
    simplified = []
    for point in points:
        if simplified and hypot(point[0]-simplified[-1][0], point[1]-simplified[-1][1]) < tolerance:
            continue
        while len(simplified) > 1:
            a, b = simplified[-2:]
            if not ((abs(a[0]-b[0]) < tolerance and abs(b[0]-point[0]) < tolerance)
                    or (abs(a[1]-b[1]) < tolerance and abs(b[1]-point[1]) < tolerance)):
                break
            simplified.pop()
        simplified.append(point)
    return simplified


def _connector(parent: ET.Element, connects: ET.Element, id: int, edge: Mapping[str, Any],
               ids: Mapping[str, int], nodes: Mapping[str, Mapping[str, Any]], space: CoordinateSpace,
               routing: str) -> None:
    source, target = str(edge["source"]), str(edge["target"])
    loop = source == target
    s_side, t_side = ("right", "top") if loop else _port(nodes[source], nodes[target])
    rendered_route = edge.get('route') if not loop else None
    x0, y0 = space.point(*_anchor(nodes[source], s_side))
    x1, y1 = space.point(*_anchor(nodes[target], t_side))
    if rendered_route:
        x0, y0 = space.point(rendered_route[0]['x'], rendered_route[0]['y'])
        x1, y1 = space.point(rendered_route[-1]['x'], rendered_route[-1]['y'])
    dist = max(hypot(x1 - x0, y1 - y0), 0.000001)
    angle = atan2(y1 - y0, x1 - x0)
    segments = edge.get('segments') if rendered_route and routing == 'mermaid' else None
    route = [(x0, y0), (x1, y1)]
    if rendered_route:
        route = [(x0, y0)] + [space.point(float(p['x']), float(p['y'])) for p in rendered_route[1:-1]] + [(x1, y1)]
    if loop:
        offset = 32 * PX_TO_IN
        route = [(x0, y0), (x0+offset, y0), (x0+offset, y1+offset), (x1, y1+offset), (x1, y1)]
    elif routing == 'right-angle':
        route = _right_angle_route(edge, (x0, y0), (x1, y1), space)
    elif routing == 'straight':
        route = [(x0, y0), (x1, y1)]
    shape = ET.SubElement(parent, tag("Shape"), {"ID": str(id), "NameU": f"Connector{id}", "Type": "Shape"})
    for field, xy, node, side in (("Begin", (x0, y0), source, s_side),
                                  ("End", (x1, y1), target, t_side)):
        port_index = edge.get('source_port' if field == 'Begin' else 'target_port', _PORTS[side][0])
        ix = port_index + 1
        # Visio uses a point expression in the X/Y endpoint cells for a glued 1D shape.
        ref = f"Sheet.{ids[node]}!Connections"
        formula = f"PAR(PNT({ref}.X{ix},{ref}.Y{ix}))"
        _cell(shape, field + "X", xy[0], formula)
        _cell(shape, field + "Y", xy[1], formula)
        ET.SubElement(connects, tag("Connect"), {
            "FromSheet": str(id), "FromCell": field + "X", "FromPart": "9" if field == "Begin" else "12",
            "ToSheet": str(ids[node]), "ToCell": f"Connections.X{ix}",
            "ToPart": str(100 + port_index),
        })
    # The visible line's transform must depend on its glued endpoints. Cached
    # coordinates alone draw correctly once, but do not follow moved boxes.
    for key, value, formula in (
        ("PinX", (x0 + x1) / 2, "(BeginX+EndX)/2"),
        ("PinY", (y0 + y1) / 2, "(BeginY+EndY)/2"),
        ("LocPinX", dist / 2, "Width*0.5"),
        ("LocPinY", 0, "0" if segments else "Height*0.5"),
        ("Width", dist, "SQRT((EndX-BeginX)^2+(EndY-BeginY)^2)"),
        # Relative Bezier rows need a nonzero Y scale. This remains a native
        # glued 1D shape; its local origin is explicitly on the centerline.
        ("Height", dist if segments else 0, "Width" if segments else None),
        ("Angle", angle, "ATAN2(EndY-BeginY,EndX-BeginX)"),
    ):
        _cell(shape, key, value, formula)
    for key, value in (("ObjType", 2), ("FillPattern", 0),
                       ("LineColor", str(edge.get("stroke", "#4472C4"))),
                       ("LineWeight", 0.012), ("LinePattern", 2 if edge.get("dash") else 1),
                       ("BeginArrow", 13 if edge.get("start_arrow") else 0),
                       ("EndArrow", 13 if edge.get("arrow", True) else 0)):
        _cell(shape, key, value)
    if routing != 'mermaid':
        # Native ShapeSheet routing settings, deliberately left unlocked so
        # Visio can reroute the sparse line geometry when shapes are moved.
        _cell(shape, 'ShapeRouteStyle', 1 if routing == 'right-angle' or loop else 2)
        _cell(shape, 'ConFixedCode', 0)
        _cell(shape, 'ConLineRouteExt', 1)
        _cell(shape, 'GlueType', 2)
        _cell(shape, 'Rounding', 0)
    label = str(edge.get("text", "")).strip()
    if label:
        background = edge.get('label_background', '#FFFFFF')
        if background:
            # Custom TextBkgnd colors use RGB()+1, unlike ordinary fill cells.
            rgb = tuple(int(background[i:i+2], 16) for i in (1, 3, 5))
            _cell(shape, 'TextBkgnd', background, f'RGB({rgb[0]},{rgb[1]},{rgb[2]})+1')
        else:
            _cell(shape, 'TextBkgnd', 0)
        _cell(shape, 'TextBkgndTrans', 0 if background else 1)
        # A 1D line has zero Height, so its label needs an independent text
        # rectangle. Otherwise importers clip vertical/diagonal edge labels.
        lines = label.splitlines()
        text_width = max(dist, (max(map(len, lines)) * 7 + 8) * PX_TO_IN)
        text_height = (len(lines) * 16 + 8) * PX_TO_IN
        label_x, label_y = dist / 2, 0
        if rendered_route:
            # Keep the label on the routed connector rather than its chord.
            mid = route[len(route)//2]
            dx, dy = mid[0]-x0, mid[1]-y0
            label_x = dx*cos(angle)+dy*sin(angle)
            label_y = -dx*sin(angle)+dy*cos(angle)
        bounds = edge.get('label_bounds')
        if bounds:
            lx, ly = space.point(float(bounds['x'])+float(bounds['width'])/2,
                                 float(bounds['y'])+float(bounds['height'])/2)
            dx, dy = lx-x0, ly-y0
            label_x, label_y = dx*cos(angle)+dy*sin(angle), -dx*sin(angle)+dy*cos(angle)
            text_width = (float(bounds['width'])+4)*PX_TO_IN
            text_height = (float(bounds['height'])+2)*PX_TO_IN
        if routing != 'mermaid' and not loop:
            # Project the original label onto the new route; straight mode
            # must not leave a label floating on the former curved path.
            lx = x0+label_x*cos(angle)-label_y*sin(angle)
            ly = y0+label_x*sin(angle)+label_y*cos(angle)
            candidates = []
            for a, b in zip(route, route[1:]):
                dx, dy = b[0]-a[0], b[1]-a[1]
                length2 = dx*dx+dy*dy
                t = max(0, min(1, ((lx-a[0])*dx+(ly-a[1])*dy)/length2)) if length2 else 0
                candidates.append((a[0]+t*dx, a[1]+t*dy))
            if candidates:
                px, py = min(candidates, key=lambda p: hypot(p[0]-lx, p[1]-ly))
                dx, dy = px-x0, py-y0
                label_x, label_y = dx*cos(angle)+dy*sin(angle), -dx*sin(angle)+dy*cos(angle)
        if loop:
            dx, dy = (x1-x0+offset)/2, y1-y0+offset
            label_x = dx*cos(angle)+dy*sin(angle)
            label_y = -dx*sin(angle)+dy*cos(angle)
        for key, value, formula in (
            ("TxtPinX", label_x, f"Width*{number(label_x/dist)}" if loop or rendered_route else "Width*0.5"),
            ("TxtPinY", label_y, f"Width*{number(label_y/dist)}" if loop or rendered_route else "Height*0.5"),
            ("TxtWidth", text_width, f"MAX(Width,{number(text_width)})"),
            ("TxtHeight", text_height, None),
            ("TxtLocPinX", text_width / 2, "TxtWidth*0.5"),
            ("TxtLocPinY", text_height / 2, "TxtHeight*0.5"),
            ("TxtAngle", -angle, "-Angle"),
            ("VerticalAlign", 1, None),
        ):
            _cell(shape, key, value, formula)
        char = ET.SubElement(shape, tag("Section"), {"N": "Character"})
        row = ET.SubElement(char, tag("Row"), {"IX": "0"})
        _cell(row, "Color", str(edge.get('font_color', '#172D4A')))
        _cell(row, "Size", 12 * PX_TO_IN)
        para = ET.SubElement(shape, tag("Section"), {"N": "Paragraph"})
        row = ET.SubElement(para, tag("Row"), {"IX": "0"})
        _cell(row, "HorzAlign", 1)
        ET.SubElement(shape, tag("Text")).text = label
    geo = ET.SubElement(shape, tag("Section"), {"N": "Geometry", "IX": "0"})
    _cell(geo, "NoFill", 1)
    if segments:
        for i, segment in enumerate(segments):
            row = ET.SubElement(geo, tag('Row'), {'T': {
                'M': 'RelMoveTo', 'L': 'RelLineTo', 'Q': 'RelQuadBezTo', 'C': 'RelCubBezTo',
            }[segment['type']], 'IX': str(i+1)})
            points = segment['points']
            # Endpoint is X/Y; preceding controls are A/B and C/D.
            for point, (xcell, ycell) in zip([points[-1]]+points[:-1], [('X','Y'),('A','B'),('C','D')]):
                px, py = space.point(float(point['x']), float(point['y']))
                xx = ((px-x0)*cos(angle)+(py-y0)*sin(angle))/dist
                yy = (-(px-x0)*sin(angle)+(py-y0)*cos(angle))/dist
                _cell(row, xcell, xx)
                _cell(row, ycell, yy)
        return
    for i, (px, py) in enumerate(route):
        xx = (px-x0)*cos(angle)+(py-y0)*sin(angle)
        yy = -(px-x0)*sin(angle)+(py-y0)*cos(angle)
        row = ET.SubElement(geo, tag("Row"), {"T": "MoveTo" if i == 0 else "LineTo", "IX": str(i+1)})
        _cell(row, "X", xx, f"Width*{number(xx/dist)}")
        _cell(row, "Y", yy, f"Width*{number(yy/dist)}")


def build_connected_vsdx(nodes: Sequence[Mapping[str, Any]], edges: Sequence[Mapping[str, Any]],
                         *, title: str = "Connected Visio Diagram", connectors: str = "right-angle") -> bytes:
    """Generate a Visio VSDX with glued 1D connectors and positioned nodes.

    Node coordinates are in SVG pixels with top-left origin:
      {"id":"a", "x":10, "y":10, "width":120, "height":50, "text":"A"}
    Edges: {"source":"a", "target":"b"}. Output is OS-independent.
    Visio connector behavior remains untested with the actual Visio application.
    """
    if connectors not in {'right-angle', 'straight', 'mermaid'}:
        raise ValueError("connectors must be 'right-angle', 'straight', or 'mermaid'")
    nodes = [dict(node, extra_ports=list(node.get('extra_ports', []))) for node in nodes]
    edges = [dict(edge) for edge in edges]
    indexed = _validate(nodes, edges)
    for edge in edges:
        route = edge.get('route')
        if route and str(edge['source']) != str(edge['target']):
            for endpoint, point in (('source', route[0]), ('target', route[-1])):
                node = indexed[str(edge[endpoint])]
                ports = node.setdefault('extra_ports', [])
                edge[endpoint+'_port'] = 4+len(ports)
                ports.append(((float(point['x'])-float(node['x']))/float(node['width']),
                              1-(float(point['y'])-float(node['y']))/float(node['height'])))
    points = [(float(n["x"]), float(n["y"])) for n in nodes]
    points += [(float(n["x"]) + float(n["width"]), float(n["y"]) + float(n["height"])) for n in nodes]
    points += [(float(p['x']), float(p['y'])) for edge in edges for p in edge.get('route') or []]
    for edge in edges:
        if str(edge["source"]) == str(edge["target"]):
            node = indexed[str(edge["source"])]
            points.append((float(node["x"])+float(node["width"])+32, float(node["y"])-32))
    space = CoordinateSpace(points)
    contents = ET.Element(tag("PageContents"), {"{http://www.w3.org/XML/1998/namespace}space": "preserve"})
    shapes = ET.SubElement(contents, tag("Shapes"))
    connects = ET.Element(tag("Connects"))
    ids = {str(n["id"]): i for i, n in enumerate(nodes, start=1)}
    # Paint containing backgrounds first, with outer containers below inner ones.
    ordered = sorted(enumerate(nodes, start=1), key=lambda pair: (
        not pair[1].get("is_group", False),
        -float(pair[1]["width"])*float(pair[1]["height"]) if pair[1].get("is_group") else 0))
    for i, node in ordered:
        _node_shape(shapes, i, node, space)
    for i, edge in enumerate(edges, start=len(nodes) + 1):
        _connector(shapes, connects, i, edge, ids, indexed, space, connectors)
    if len(connects):
        contents.append(connects)
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in _parts(xml_bytes(contents), space.page_width, space.page_height, title).items():
            archive.writestr(name, data)
    return output.getvalue()
