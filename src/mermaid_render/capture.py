"""Join pinned Pele semantic identities to browser-free SVG geometry."""

from .svg import SvgDocument, SVG, SHAPES, bounds, number, color
from .renderer import RenderError, THEMES


def text_rows(items):
    rows = []
    for item in items:
        if item["kind"] != "text":
            continue
        row = next((r for r in rows if abs(r["y"] - item["y"]) < 1), None)
        if row is None:
            rows.append(
                {
                    **{k: item[k] for k in ["x", "y", "width", "height", "text"]},
                    "font_size": item["fontPx"],
                    "color": item["fill"],
                    "bold": item["bold"],
                    "italic": item["italic"],
                    "underline": item.get("underline", False),
                    "align": 1 if item["anchor"] == "middle" else 0,
                }
            )
        else:
            row["text"] += item["text"]
            row["width"] = max(row["width"], item["x"] + item["width"] - row["x"])
            row["bold"] |= item["bold"]
            row["italic"] |= item["italic"]
            row["underline"] |= item.get("underline", False)
    return rows


def _state_model(doc):
    nodes = {}
    edges = []
    counter = 0

    def visit(item, parent):
        nonlocal counter
        id_ = item["id"]
        old = nodes.setdefault(id_, {})
        old.update(
            {k: v for k, v in item.items() if k not in {"description", "doc", "note"}}
        )
        if parent is not None:
            old["parent_id"] = parent
        if item.get("doc") is not None:
            old["is_group"] = True
        if item.get("note"):
            note = item["note"]
            note_id = f"{id_}----note-{counter}"
            counter += 1
            nodes[note_id] = {"note_for": id_}
            start, end = (
                (note_id, id_) if note["position"] == "left of" else (id_, note_id)
            )
            edges.append(
                {"id": start + "-" + end, "start": start, "end": end, "note": True}
            )

    def walk(items, parent=None):
        nonlocal counter
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("stmt") == "state":
                visit(item, parent)
                if item.get("doc") is not None:
                    walk(item["doc"], item["id"])
            elif item.get("stmt") == "relation":
                visit(item["state1"], parent)
                visit(item["state2"], parent)
                edges.append(
                    {
                        "id": f"edge{counter}",
                        "start": item["state1"]["id"],
                        "end": item["state2"]["id"],
                    }
                )
                counter += 1

    walk(doc)
    for node in nodes.values():
        if "note_for" in node:
            node["parent_id"] = nodes[node["note_for"]].get("parent_id")
    return nodes, edges


def model_graph(model):
    kind = model["type"]
    meta = {}
    edges = []
    if kind == "flowchart":
        meta = {k: {} for k in model["nodes"]}
        for sub in model["subgraphs"]:
            meta.setdefault(sub["id"], {})["is_group"] = True
            for child in sub["nodes"]:
                meta.setdefault(child, {})["parent_id"] = sub["id"]
        edges = model["edges"]
    elif kind == "state":
        meta, edges = _state_model(model["rootDoc"])
    elif kind == "class":
        meta = {
            id_: {"parent_id": c.get("parent"), "class": True}
            for id_, c in model["classes"].items()
        }
        for interface in model.get("interfaces", []):
            meta[interface["id"]] = {}
        for id_, ns in model["namespaces"].items():
            meta[id_] = {"is_group": True, "parent_id": ns.get("parent")}
        markers = {
            0: "aggregation",
            1: "extension",
            2: "composition",
            3: "dependency",
            4: "lollipop",
            "none": "none",
        }
        for i, r in enumerate(model["relations"], 1):
            edges.append(
                dict(
                    id=f"id_{r['id1']}_{r['id2']}_{i}",
                    start=r["id1"],
                    end=r["id2"],
                    begin_marker=markers[r["relation"]["type1"]],
                    end_marker=markers[r["relation"]["type2"]],
                    source_label=r.get("relationTitle1"),
                    target_label=r.get("relationTitle2"),
                )
            )
        for id_, note in model["notes"].items():
            meta[id_] = {}
            if note.get("class"):
                edges.insert(
                    0,
                    dict(
                        id=f"edgeNote{note['index']}",
                        start=id_,
                        end=note["class"],
                        note=True,
                        begin_marker="none",
                        end_marker="none",
                    ),
                )
    else:
        raise RenderError(
            f"Connected VSDX supports flowcharts, sequence diagrams, state diagrams, and class diagrams, not {kind}"
        )
    return meta, edges


def connected_graph(reply, theme):
    model = reply["graph"]
    kind = model["type"]
    doc = SvgDocument(reply["result"]["svg"], THEMES[theme]["bg"])
    meta, semantic_edges = model_graph(model)
    groups = {**doc.by_id("pele-node"), **doc.by_id("pele-cluster")}
    if kind == "state":
        groups.update(
            {e.get("data-id"): e for e in doc.find("pele-note") if e.get("data-id")}
        )
    nodes = []
    for id_, el in groups.items():
        if id_ not in meta:
            raise RenderError(f"Unknown Pele node mapping: {id_}")
        items = doc.items(el)
        polys = [i for i in items if i["kind"] == "poly"]
        texts = [i for i in items if i["kind"] == "text"]
        if not polys and not (
            kind == "class" and doc.has(el, "pele-interface") and texts
        ):
            raise RenderError(f"No shape geometry for {id_}")
        dim = bounds(polys or texts)
        w, h = dim["width"], dim["height"]
        if w <= 0 or h <= 0:
            raise RenderError(f"Invalid shape dimensions for {id_}")
        first = (
            polys[0]
            if polys
            else {"fill": None, "stroke": None, "strokeWidthPx": 0, "dash": False}
        )
        rows = text_rows(texts)
        is_group = bool(meta[id_].get("is_group"))
        node = dict(
            id=id_,
            **dim,
            text="\n".join(r["text"] for r in rows),
            is_group=is_group,
            parent_id=meta[id_].get("parent_id"),
            fill=first["fill"] or doc.background,
            stroke=first["stroke"] or "#000000",
            stroke_width=first["strokeWidthPx"],
            dash=first["dash"],
            font_color=rows[0]["color"] if rows else "#000000",
            font_size=rows[0]["font_size"] if rows else 16,
            shape="captured",
            outlines=[],
        )
        for p in polys:
            node["outlines"].append(
                {
                    "points": [
                        {"x": (v["x"] - dim["x"]) / w, "y": 1 - (v["y"] - dim["y"]) / h}
                        for v in p["points"]
                    ],
                    "closed": p["closed"],
                    "fill": bool(p["fill"]),
                    "stroke": bool(p["stroke"]),
                }
            )
        if texts:
            node["label_bounds"] = bounds(texts)
        shape = next(
            (
                c[11:]
                for c in el.get("class", "").split()
                if c.startswith("pele-shape-")
            ),
            "",
        )
        native = {
            "rect": "rect",
            "rounded": "roundedrect",
            "diam": "diamond",
            "hex": "hexagon",
            "cyl": "cylinder",
            "circle": "circle",
            "dbl-circ": "doublecircle",
            "stadium": "stadium",
        }
        if shape in native:
            node["shape"] = native[shape]
        if is_group:
            node["shape"] = "roundedrect"
        if is_group and kind == "state":
            node["shape"] = "captured"
        if kind == "class" and meta[id_].get("class"):
            node["shape"] = "classBox"
        if doc.has(el, "pele-state-start"):
            node["shape"] = "state-start"
            node["text"] = ""
        if doc.has(el, "pele-state-end"):
            node["shape"] = "state-end"
            node["text"] = ""
            node["fill"] = node["stroke"]
        if doc.has(el, "pele-state-choice"):
            node["shape"] = "diamond"
            node["text"] = ""
        if doc.has(el, "pele-state") and len(rows) == 1:
            node["shape"] = "roundedrect"
        if kind == "state" and (meta[id_].get("type") in {"fork", "join"}):
            node["text"] = ""
        rect = next((e for e in el if e.tag == SVG + "rect"), None)
        if rect is not None:
            node["corner_radius"] = number(doc.styles[rect].get("rx", rect.get("rx")))
            if node["shape"] == "rect" and node["corner_radius"]:
                node["shape"] = "roundedrect"
        if rows:
            if (
                node["shape"] == "classBox"
                or node["shape"] == "captured"
                and (
                    len(rows) > 1
                    or any(r["bold"] or r["italic"] or r["underline"] for r in rows)
                )
            ):
                node["text_rows"] = rows
                # Some importers use row zero for every run. Keep its fallback
                # at body size, while explicit character rows retain title sizes.
                node["font_size"] = min(r["font_size"] for r in rows)
            elif len(rows) > 1:
                node["text_rows"] = [
                    {k: v for k, v in r.items() if k != "align"} for r in rows
                ]
        # Ports for captured outlines meet the rendered silhouette, not its bounding box.
        if node["shape"] == "captured" and node["outlines"]:
            ports = {}
            pts = node["outlines"][0]["points"]
            for name, axis, extreme in [
                ("left", "y", min),
                ("right", "y", max),
                ("bottom", "x", min),
                ("top", "x", max),
            ]:
                intersections = []
                other = "x" if axis == "y" else "y"
                for a, b in zip(pts, pts[1:]):
                    delta = b[axis] - a[axis]
                    if delta and min(a[axis], b[axis]) <= 0.5 <= max(a[axis], b[axis]):
                        intersections.append(
                            a[other] + (0.5 - a[axis]) / delta * (b[other] - a[other])
                        )
                if intersections:
                    ports[name] = (
                        [extreme(intersections), 0.5]
                        if axis == "y"
                        else [0.5, extreme(intersections)]
                    )
            node["connection_points"] = ports
        nodes.append(node)
    # Pele draws concurrent region separators without semantic wrapper IDs.
    # Recover a native region container from its positioned members.
    missing = set(meta) - set(groups)
    while missing:
        progress = False
        for id_ in list(missing):
            if kind != "state" or meta[id_].get("type") != "divider":
                continue
            children = [n for n in nodes if n.get("parent_id") == id_]
            if not children:
                continue
            d = bounds(
                [
                    dict(
                        kind="text", **{k: n[k] for k in ["x", "y", "width", "height"]}
                    )
                    for n in children
                ]
            )
            nodes.append(
                dict(
                    id=id_,
                    x=d["x"] - 8,
                    y=d["y"] - 8,
                    width=d["width"] + 16,
                    height=d["height"] + 16,
                    shape="rect",
                    text="",
                    is_group=True,
                    parent_id=meta[id_].get("parent_id"),
                    fill=doc.background,
                    stroke=THEMES[theme]["border"],
                )
            )
            missing.remove(id_)
            progress = True
        if not progress:
            break
    if missing:
        raise RenderError("Cannot map Pele nodes to SVG: " + ", ".join(sorted(missing)))
    index = {n["id"]: n for n in nodes}
    # Composite alpha over the actual parent, not always the white page.
    painted = {}

    def paint(id_, seen=frozenset()):
        if id_ in painted:
            return painted[id_]
        if id_ in seen:
            raise RenderError("Cyclic node membership")
        n = index[id_]
        el = groups.get(id_)
        parent = n.get("parent_id")
        bg = paint(parent, seen | {id_}) if parent else doc.background
        if el is not None:
            glyph = next(
                (e for e in el.iter() if e.tag.removeprefix(SVG) in SHAPES), None
            )
            if glyph is not None:
                style = doc.styles[glyph]
                n["fill"] = (
                    color(
                        style.get("fill"),
                        bg,
                        style["_opacity"] * number(style.get("fill-opacity", "1")),
                    )
                    or bg
                )
        if n["shape"] == "state-end":
            n["fill"] = n["stroke"]
        painted[id_] = n["fill"]
        return n["fill"]

    for id_ in index:
        paint(id_)
    edge_elements = doc.by_id("pele-edge")
    labels = doc.by_id("pele-edge-label")
    edges = []
    cards = iter(doc.find("pele-cardinality"))
    for e in semantic_edges:
        source, target = e["start"], e["end"]
        el = edge_elements.get(e["id"])
        label = labels.get(e["id"])
        path = (
            next((p for p in el if p.tag == SVG + "path"), None)
            if el is not None
            else None
        )
        if path is None:
            if kind == "flowchart" and e.get("stroke") == "invisible":
                a, b = index[source], index[target]
                route = [
                    {"x": n["x"] + n["width"] / 2, "y": n["y"] + n["height"] / 2}
                    for n in (a, b)
                ]
                segments = None
                style = {}
                stroke_width = 0
            else:
                raise RenderError(f"Cannot map Pele edge to SVG: {e['id']}")
        else:
            route, segments = doc.route(path)
            style = doc.styles[path]
            stroke_width = number(style.get("stroke-width", "1"))
        items = doc.items(label) if label is not None else []
        label_rows = text_rows(items)
        rect = next((i for i in items if i["kind"] == "poly" and i["fill"]), None)
        arrow = not e.get("note") and e.get("type", "arrow_point") != "arrow_open"
        edge = dict(
            source=source,
            target=target,
            route=route,
            segments=segments,
            text="\n".join(r["text"] for r in label_rows),
            arrow=arrow,
            start_arrow=e.get("type", "").startswith("double_"),
            open_arrow=kind == "state",
            stroke=doc.paint(path, "stroke") if path is not None else "#000000",
            stroke_width=stroke_width,
            dash=style.get("stroke-dasharray", "none") not in {"none", "0"},
            font_color=label_rows[0]["color"] if label_rows else "#000000",
            font_size=label_rows[0]["font_size"] if label_rows else 14,
            label_background=rect["fill"] if rect else None,
            label_bounds=bounds(items) if items else None,
        )
        if kind == "state":
            edge["preserve_label_position"] = True
        markers = [m for m in el if doc.has(m, "pele-marker")] if el is not None else []
        # Triangle point markers start at the actual outline tip. Restore shortened paths.
        if kind != "class" and markers:
            ends = ([0] if edge["start_arrow"] else []) + (
                [-1] if edge["arrow"] else []
            )
            for at, marker in zip(ends, markers):
                p = doc.path(marker)
                tip = p[0].end
                route[at] = {"x": float(tip.x), "y": float(tip.y)}
                if segments:
                    segments[0 if at == 0 else -1]["points"][0 if at == 0 else -1] = (
                        route[at]
                    )
        if kind == "class":
            edge.update(
                begin_marker=e["begin_marker"],
                end_marker=e["end_marker"],
                terminal_labels=[],
                preserve_route=source == target,
            )
            # Match marker anchors at node borders, extending the trimmed centerline.
            for at, field in [(0, "begin_marker"), (-1, "end_marker")]:
                if e[field] != "none" and markers:
                    marker = markers.pop(0)
                    p = doc.path(marker)
                    tip = p[0].end
                    route[at] = {"x": float(tip.x), "y": float(tip.y)}
                    segments[0 if at == 0 else -1]["points"][0 if at == 0 else -1] = (
                        route[at]
                    )
            for side in ["source", "target"]:
                text = e.get(side + "_label")
                if text and text != "none":
                    card = next(cards, None)
                    if card is None:
                        raise RenderError("Class multiplicity mapping is incomplete")
                    captured = doc.texts(card)
                    if "".join(i["text"] for i in captured) != text:
                        raise RenderError("Class multiplicity identity mismatch")
                    edge["terminal_labels"].append(
                        dict(
                            **bounds(captured),
                            text=text,
                            side=side,
                            fontPx=captured[0]["fontPx"],
                            fill=captured[0]["fill"],
                        )
                    )
        edges.append(edge)
    return nodes, edges


def sequence_graph(reply, theme):
    doc = SvgDocument(reply["result"]["svg"], THEMES[theme]["bg"])
    model = reply["graph"]
    participants = {id_: {"id": id_, "items": []} for id_ in model["actors"]}
    decorations = []
    for cls in ["pele-actor", "pele-lifeline", "pele-activation", "pele-destroy"]:
        for el in doc.find(cls):
            id_ = el.get("data-id")
            if id_ not in participants:
                raise RenderError("Unknown sequence participant")
            participants[id_]["items"].extend(doc.items(el))
    for p in participants.values():
        if not p["items"]:
            raise RenderError(f"Missing sequence artwork for {p['id']}")
        p.update(bounds(p["items"]))
        p["width"] = max(p["width"], 1)
        p["height"] = max(p["height"], 1)
    for cls, kind in [
        ("pele-note", "note"),
        ("pele-frame", "control-structure"),
        ("pele-box", "box"),
        ("pele-rect", "background"),
    ]:
        for el in doc.find(cls):
            items = doc.items(el)
            if items:
                decorations.append({"kind": kind, "items": items})
    labels = doc.by_id("pele-edge-label")
    messages = doc.by_id("pele-message")
    edges = []
    for m in model["messages"]:
        el = messages.get("i" + str(m["id"]))
        if el is None:
            continue
        if m.get("from") not in participants or m.get("to") not in participants:
            raise RenderError("Sequence message has unknown participant")
        path = next((p for p in el if p.tag == SVG + "path"), None)
        if path is None:
            raise RenderError("Sequence message has no path")
        route, _ = doc.route(path)
        if m["from"] == m["to"]:
            extent = max(p["x"] for p in route)
            route = [
                route[0],
                {"x": extent, "y": route[0]["y"]},
                {"x": extent, "y": route[-1]["y"]},
                route[-1],
            ]
        else:
            route = [route[0], route[-1]]
        label = labels.get("i" + str(m["id"]))
        items = doc.items(label) if label is not None else []
        texts = [i for i in items if i["kind"] == "text"]
        rows = text_rows(texts)
        badges = [
            child for child in el.iter() if doc.has(child, "pele-sequence-number")
        ]
        numbers = [
            i for badge in badges for i in doc.items(badge) if i["kind"] == "text"
        ]
        t = m.get("type")
        style = doc.styles[path]
        edges.append(
            dict(
                source=m["from"],
                target=m["to"],
                route=route,
                preserve_route=True,
                text="\n".join(r["text"] for r in rows),
                label_bounds=bounds(texts) if texts else None,
                label_background=None,
                font_color=texts[0]["fill"] if texts else "#000000",
                font_size=texts[0]["fontPx"] if texts else 16,
                stroke=doc.paint(path, "stroke"),
                stroke_width=number(style.get("stroke-width", "1")),
                dash=style.get("stroke-dasharray", "none") not in {"none", "0"},
                arrow=t not in {5, 6, 3, 4},
                start_arrow=t in {33, 34},
                cross=t in {3, 4},
                open=t in {24, 25},
                numbers=numbers,
            )
        )
    if len(edges) != len(messages):
        raise RenderError("Sequence semantic message mapping is incomplete")
    return dict(
        participants=list(participants.values()),
        edges=edges,
        decorations=decorations,
        width=doc.width,
        height=doc.height,
    )
