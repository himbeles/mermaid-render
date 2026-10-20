"""Browser-free SVG geometry, CSS, and editable text capture.

External resources, scripts, foreignObject and use references are rejected rather
than fetched or silently omitted. Shapes, paths, affine transforms, basic CSS,
SVG text/tspan positioning and marker flags are supported.
"""

import math
import re
from xml.etree import ElementTree as ET

from svgelements import (
    Path,
    Matrix,
    Rect,
    Circle,
    Ellipse,
    Polygon,
    Polyline,
    Line,
    Color,
    Move,
    Close,
    CubicBezier,
    QuadraticBezier,
)
from .fonts import text_width
from .renderer import RenderError

SVG = "{http://www.w3.org/2000/svg}"
NUMBER = r"[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?"
SHAPES = {"path", "rect", "circle", "ellipse", "polygon", "polyline", "line"}
SKIP = {
    "defs",
    "marker",
    "clipPath",
    "symbol",
    "pattern",
    "mask",
    "title",
    "desc",
    "style",
    "metadata",
}
INHERIT = {
    "fill",
    "fill-opacity",
    "stroke",
    "stroke-opacity",
    "stroke-width",
    "stroke-dasharray",
    "font-size",
    "font-family",
    "font-weight",
    "font-style",
    "text-anchor",
    "visibility",
    "text-decoration",
    "color",
    "marker-start",
    "marker-end",
    "dominant-baseline",
}


def number(value, default=0):
    if value is None:
        return float(default)
    match = re.fullmatch(r"\s*(" + NUMBER + r")(px|pt|in|cm|mm)?\s*", str(value))
    if not match:
        raise RenderError(f"Unsupported SVG length: {value}")
    scale = {
        None: 1,
        "px": 1,
        "pt": 96 / 72,
        "in": 96,
        "cm": 96 / 2.54,
        "mm": 96 / 25.4,
    }[match[2]]
    result = float(match[1]) * scale
    if not math.isfinite(result):
        raise RenderError("Non-finite SVG coordinate")
    return result


def declarations(value):
    import tinycss2

    return {
        d.lower_name: (tinycss2.serialize(d.value).strip(), d.important)
        for d in tinycss2.parse_declaration_list(
            value, skip_whitespace=True, skip_comments=True
        )
        if d.type == "declaration"
    }


def color(value, background="#FFFFFF", alpha=1):
    if value in (None, "none", "transparent"):
        return None
    try:
        c = Color(value)
        if c.red is None:
            raise ValueError(value)
        opacity = alpha * (c.alpha / 255 if c.alpha is not None else 1)
        bg = Color(background)
        return "#" + "".join(
            f"{round(v * opacity + b * (1 - opacity)):02X}"
            for v, b in zip((c.red, c.green, c.blue), (bg.red, bg.green, bg.blue))
        )
    except (ValueError, TypeError) as exc:
        raise RenderError(f"Unsupported SVG color: {value}") from exc


def compose(a, b):
    return Matrix(
        a.a * b.a + a.c * b.b,
        a.b * b.a + a.d * b.b,
        a.a * b.c + a.c * b.d,
        a.b * b.c + a.d * b.d,
        a.a * b.e + a.c * b.f + a.e,
        a.b * b.e + a.d * b.f + a.f,
    )


def point(m, x, y):
    return {"x": float(m.a * x + m.c * y + m.e), "y": float(m.b * x + m.d * y + m.f)}


def bounds(items):
    points = [
        p
        for item in items
        for p in (
            item["points"]
            if item["kind"] == "poly"
            else [
                {"x": item["x"], "y": item["y"]},
                {"x": item["x"] + item["width"], "y": item["y"] + item["height"]},
            ]
        )
    ]
    if not points:
        raise RenderError("SVG element has no supported visible geometry")
    xs, ys = [p["x"] for p in points], [p["y"] for p in points]
    return dict(x=min(xs), y=min(ys), width=max(xs) - min(xs), height=max(ys) - min(ys))


class SvgDocument:
    def __init__(self, svg, background="#FFFFFF"):
        if len(svg) > 4_000_000 or re.search(r"<!DOCTYPE|<!ENTITY", svg, re.I):
            raise RenderError(
                "SVG is too large or contains document/entity declarations"
            )
        self.root = ET.fromstring(svg)
        if self.root.tag != SVG + "svg":
            raise RenderError("Input must be an SVG document")
        self.background = background
        self.styles = {}
        self.transforms = {}
        self.parents = {}
        self.hidden = set()
        import cssselect2
        import tinycss2

        matcher = cssselect2.Matcher()
        for element in self.root.iter(SVG + "style"):
            for rule in tinycss2.parse_stylesheet(
                element.text or "", skip_comments=True, skip_whitespace=True
            ):
                if rule.type != "qualified-rule":
                    raise RenderError("Only local SVG CSS rules are supported")
                try:
                    selectors = cssselect2.compile_selector_list(
                        tinycss2.serialize(rule.prelude)
                    )
                    for selector in selectors:
                        matcher.add_selector(selector, declarations(rule.content))
                except cssselect2.SelectorError as exc:
                    raise RenderError("Unsupported SVG CSS selector") from exc
        wrappers = {
            w.etree_element: w
            for w in cssselect2.ElementWrapper.from_xml_root(self.root).iter_subtree()
        }

        def walk(el, parent_style, matrix, hidden=False, opacity=1):
            tag = el.tag.removeprefix(SVG)
            if tag in {"script", "foreignObject", "image", "use", "filter"}:
                raise RenderError(
                    f"Unsupported SVG element: {tag}; external resources are disabled"
                )
            own = {
                k: (v, False)
                for k, v in el.attrib.items()
                if k in INHERIT or k in {"display", "opacity", "rx"}
            }
            priorities = {k: (False, (0, 0, 0), 0) for k in own}
            for specificity, order, pseudo, payload in matcher.match(wrappers[el]):
                for k, (v, important) in payload.items():
                    priority = (important, specificity, order)
                    if priority >= priorities.get(k, (False, (0, 0, 0), -1)):
                        own[k] = (v, important)
                        priorities[k] = priority
            for k, (v, important) in declarations(el.get("style", "")).items():
                if (important, (1, 0, 0), 0) >= priorities.get(
                    k, (False, (0, 0, 0), -1)
                ):
                    own[k] = (v, important)
            style = {k: v for k, v in parent_style.items() if k in INHERIT}
            style.update({k: v for k, (v, _) in own.items()})
            if "font" in own:
                font = own["font"][0]
                match = re.search("(" + NUMBER + r"(?:px|pt))\s+(.+)", font)
                if match:
                    style["font-size"] = str(number(match[1]))
                    style["font-family"] = match[2]
                    style["font-weight"] = (
                        "bold" if "bold" in font[: match.start()] else "normal"
                    )
                    style["font-style"] = (
                        "italic" if "italic" in font[: match.start()] else "normal"
                    )
            if style.get("fill") == "currentColor":
                style["fill"] = style.get("color", "#000000")
            if style.get("stroke") == "currentColor":
                style["stroke"] = style.get("color", "#000000")
            opacity *= number(style.get("opacity", "1"))
            style["_opacity"] = opacity
            hidden = (
                hidden
                or tag in SKIP
                or style.get("display") == "none"
                or style.get("visibility") == "hidden"
                or opacity == 0
            )
            if hidden:
                self.hidden.add(el)
            local = Matrix(el.get("transform", ""))
            if tag == "svg" and el is not self.root:
                view = [
                    float(v)
                    for v in re.split(r"[ ,]+", el.get("viewBox", "").strip())
                    if v
                ]
                viewport = Matrix(1, 0, 0, 1, number(el.get("x")), number(el.get("y")))
                if len(view) == 4:
                    vx, vy, vw, vh = view
                    if vw <= 0 or vh <= 0:
                        raise RenderError("Invalid nested SVG viewBox")
                    width, height = (
                        number(el.get("width"), vw),
                        number(el.get("height"), vh),
                    )
                    sx, sy = width / vw, height / vh
                    aspect = el.get("preserveAspectRatio", "xMidYMid meet")
                    dx = dy = 0
                    if aspect != "none":
                        sx = sy = max(sx, sy) if "slice" in aspect else min(sx, sy)
                        dx = (width - vw * sx) * (
                            0 if "xMin" in aspect else 1 if "xMax" in aspect else 0.5
                        )
                        dy = (height - vh * sy) * (
                            0 if "YMin" in aspect else 1 if "YMax" in aspect else 0.5
                        )
                    viewport = compose(
                        viewport, Matrix(sx, 0, 0, sy, dx - vx * sx, dy - vy * sy)
                    )
                local = compose(local, viewport)
            matrix = compose(matrix, local)
            self.styles[el] = style
            self.transforms[el] = matrix
            for child in el:
                self.parents[child] = el
                walk(child, style, matrix, hidden, opacity)

        walk(
            self.root,
            {
                "fill": "#000000",
                "stroke": "none",
                "stroke-width": "1",
                "font-size": "16",
                "font-family": "Noto Sans",
                "text-anchor": "start",
            },
            Matrix(),
        )
        view = [
            float(v)
            for v in re.split(r"[ ,]+", self.root.get("viewBox", "").strip())
            if v
        ]
        self.width = number(self.root.get("width"), view[2] if len(view) == 4 else 0)
        self.height = number(self.root.get("height"), view[3] if len(view) == 4 else 0)

    def has(self, el, cls):
        return cls in el.get("class", "").split()

    def find(self, cls):
        return [e for e in self.root.iter() if self.has(e, cls)]

    def by_id(self, cls):
        return {e.get("data-id"): e for e in self.find(cls)}

    def ancestor(self, el, cls):
        while el is not None:
            if self.has(el, cls):
                return el
            el = self.parents.get(el)
        return None

    def paint(self, el, key):
        style = self.styles[el]
        return color(
            style.get(key),
            self.background,
            style["_opacity"] * number(style.get(key + "-opacity", "1")),
        )

    def path(self, el):
        tag = el.tag.removeprefix(SVG)
        attrs = el.attrib
        if tag == "path":
            p = Path(attrs.get("d", ""))
        elif tag == "rect":
            p = Path(
                Rect(
                    x=number(attrs.get("x")),
                    y=number(attrs.get("y")),
                    width=number(attrs.get("width")),
                    height=number(attrs.get("height")),
                    rx=number(self.styles[el].get("rx", attrs.get("rx"))),
                )
            )
        elif tag == "circle":
            p = Path(
                Circle(
                    cx=number(attrs.get("cx")),
                    cy=number(attrs.get("cy")),
                    r=number(attrs.get("r")),
                )
            )
        elif tag == "ellipse":
            p = Path(
                Ellipse(
                    cx=number(attrs.get("cx")),
                    cy=number(attrs.get("cy")),
                    rx=number(attrs.get("rx")),
                    ry=number(attrs.get("ry")),
                )
            )
        elif tag in {"polygon", "polyline"}:
            p = Path(
                (Polygon if tag == "polygon" else Polyline)(attrs.get("points", ""))
            )
        elif tag == "line":
            p = Path(
                Line(
                    (number(attrs.get("x1")), number(attrs.get("y1"))),
                    (number(attrs.get("x2")), number(attrs.get("y2"))),
                )
            )
        else:
            raise RenderError(f"Unsupported SVG shape: {tag}")
        p *= self.transforms[el]
        p.reify()
        return p

    def polys(self, el):
        if el in self.hidden:
            return []
        p = self.path(el)
        style = self.styles[el]
        fill, stroke = self.paint(el, "fill"), self.paint(el, "stroke")
        if not fill and not stroke:
            return []
        result = []
        for sub in p.as_subpaths():
            points = []
            for seg in sub:
                if isinstance(seg, Move):
                    continue
                # Bound sampling for curves, including SVG arcs. No external geometry API.
                steps = 1 if type(seg).__name__ in {"Line", "Close"} else 24
                if not points and seg.start is not None:
                    points.append({"x": float(seg.start.x), "y": float(seg.start.y)})
                for i in range(1, steps + 1):
                    pt = seg.point(i / steps)
                    points.append({"x": float(pt.x), "y": float(pt.y)})
            if len(points) < 2:
                continue
            m = self.transforms[el]
            scale = math.sqrt(abs(m.a * m.d - m.b * m.c))
            result.append(
                dict(
                    kind="poly",
                    points=points,
                    closed=isinstance(sub[-1], Close),
                    fill=fill,
                    stroke=stroke,
                    strokeWidthPx=number(style.get("stroke-width", "1")) * scale,
                    dash=style.get("stroke-dasharray", "none") not in {"none", "0"},
                    beginArrow=style.get("marker-start", "none") != "none",
                    endArrow=style.get("marker-end", "none") != "none",
                    element=el,
                )
            )
        return result

    def texts(self, el):
        if el in self.hidden:
            return []
        chunks = []
        cursor = [0.0, 0.0]
        chunk = -1

        def walk(node):
            nonlocal chunk
            style = self.styles[node]
            new = chunk < 0 or "x" in node.attrib or "y" in node.attrib
            if "x" in node.attrib:
                cursor[0] = number(node.get("x"))
            if "y" in node.attrib:
                cursor[1] = number(node.get("y"))
            cursor[0] += number(node.get("dx"))
            cursor[1] += number(node.get("dy"))
            if new:
                chunk += 1

            def emit(value):
                if not value:
                    return
                size = number(style.get("font-size", "16"))
                bold = style.get("font-weight", "normal") in {
                    "bold",
                    "600",
                    "700",
                    "800",
                    "900",
                }
                italic = style.get("font-style") in {"italic", "oblique"}
                width = text_width(value, size, bold, italic)
                chunks.append(
                    dict(
                        text=value,
                        x=cursor[0],
                        y=cursor[1],
                        width=width,
                        size=size,
                        bold=bold,
                        italic=italic,
                        underline=style.get("text-decoration") == "underline",
                        chunk=chunk,
                        anchor=style.get("text-anchor", "start"),
                        fill=self.paint(node, "fill"),
                        element=node,
                    )
                )
                cursor[0] += width

            emit(node.text)
            for child in node:
                walk(child)
                emit(child.tail)

        walk(el)
        widths = {
            k: sum(c["width"] for c in chunks if c["chunk"] == k)
            for k in {c["chunk"] for c in chunks}
        }
        result = []
        for c in chunks:
            if not c["text"].strip():
                continue
            shift = widths[c["chunk"]] * {"middle": 0.5, "end": 1}.get(c["anchor"], 0)
            x, y = c["x"] - shift, c["y"]
            # The bundled font's baseline policy is shared with Pele's label layout.
            top = y - c["size"] * 0.8
            m = self.transforms[c["element"]]
            corners = [
                point(m, xx, yy)
                for xx in (x, x + c["width"])
                for yy in (top, top + c["size"] * 1.2)
            ]
            a = {axis: min(p[axis] for p in corners) for axis in ("x", "y")}
            b = {axis: max(p[axis] for p in corners) for axis in ("x", "y")}
            result.append(
                dict(
                    kind="text",
                    text=c["text"],
                    x=min(a["x"], b["x"]),
                    y=min(a["y"], b["y"]),
                    width=abs(b["x"] - a["x"]),
                    height=abs(b["y"] - a["y"]),
                    fontPx=c["size"],
                    fontFamily="Noto Sans",
                    bold=c["bold"],
                    italic=c["italic"],
                    underline=c["underline"],
                    anchor=c["anchor"],
                    fill=c["fill"] or "#000000",
                    element=el,
                )
            )
        return result

    def items(self, group=None):
        output = []
        for el in (group if group is not None else self.root).iter():
            tag = el.tag.removeprefix(SVG)
            if tag in SHAPES:
                output.extend(self.polys(el))
            elif tag == "text":
                output.extend(self.texts(el))
        return output

    def route(self, el):
        p = self.path(el)
        segments = []
        route = []
        for seg in p:
            if isinstance(seg, Move):
                value = {"x": float(seg.end.x), "y": float(seg.end.y)}
                segments.append({"type": "M", "points": [value]})
                route.append(value)
                continue
            points = []
            if isinstance(seg, CubicBezier):
                points = [seg.control1, seg.control2, seg.end]
                kind = "C"
            elif isinstance(seg, QuadraticBezier):
                points = [seg.control, seg.end]
                kind = "Q"
            elif type(seg).__name__ in {"Line", "Close"}:
                points = [seg.end]
                kind = "L"
            else:
                # Arcs have no ShapeSheet Bezier equivalent: preserve a bounded polyline.
                for j in range(1, 25):
                    pt = seg.point(j / 24)
                    q = {"x": float(pt.x), "y": float(pt.y)}
                    segments.append({"type": "L", "points": [q]})
                    route.append(q)
                continue
            segments.append(
                {
                    "type": kind,
                    "points": [{"x": float(q.x), "y": float(q.y)} for q in points],
                }
            )
            for j in range(1, 17 if kind in {"C", "Q"} else 2):
                pt = seg.point(j / (16 if kind in {"C", "Q"} else 1))
                route.append({"x": float(pt.x), "y": float(pt.y)})
        if len(route) < 2:
            raise RenderError("Connector path has no length")
        return route, segments

    def display(self):
        items = self.items()
        if not items:
            raise ValueError("SVG contained no supported visible shapes or text")
        return {"width": self.width, "height": self.height, "items": items}
