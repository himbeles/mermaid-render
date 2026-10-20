"""Pinned Pele in embedded QuickJS, with no browser, subprocess, or network access."""

import hashlib
import json
from pathlib import Path
import re
import threading
from xml.etree import ElementTree as ET

from .fonts import metrics

ROOT = Path(__file__).parent
THEMES = {
    "redux-color": {
        "bg": "#FFFFFF",
        "fg": "#172D4A",
        "muted": "#596579",
        "line": "#000000",
        "surface": "#E5EFFA",
        "surface-alt": "#F0F4FA",
        "border": "#4472C4",
        "accent": "#4472C4",
    },
    "default": {
        "bg": "#FFFFFF",
        "fg": "#333333",
        "muted": "#666666",
        "line": "#333333",
        "surface": "#ECECFF",
        "surface-alt": "#FFFFDE",
        "border": "#9370DB",
        "accent": "#9370DB",
    },
    "dark": {
        "bg": "#1F2020",
        "fg": "#EEEEEE",
        "muted": "#BBBBBB",
        "line": "#CCCCCC",
        "surface": "#303640",
        "surface-alt": "#252A32",
        "border": "#8A9BB5",
        "accent": "#8AAEED",
    },
    "neutral": {
        "bg": "#FFFFFF",
        "fg": "#222222",
        "muted": "#666666",
        "line": "#444444",
        "surface": "#F3F3F3",
        "surface-alt": "#E6E6E6",
        "border": "#888888",
        "accent": "#555555",
    },
    "forest": {
        "bg": "#FFFFFF",
        "fg": "#153C20",
        "muted": "#53765A",
        "line": "#32583B",
        "surface": "#DDEED8",
        "surface-alt": "#EFF6E8",
        "border": "#528C50",
        "accent": "#528C50",
    },
}
_LOCAL = threading.local()


class RenderError(ValueError):
    """A source, resource-limit, or unsupported export error."""


def _context():
    if getattr(_LOCAL, "context", None) is None:
        import quickjs

        bundle = (ROOT / "pele/pele.global.js").read_bytes()
        manifest = json.loads((ROOT / "pele/manifest.json").read_text())
        if hashlib.sha256(bundle).hexdigest() != manifest["sha256"]:
            raise RuntimeError(
                "Bundled Pele checksum mismatch; reinstall mermaid-render"
            )
        ctx = quickjs.Context()
        ctx.set_memory_limit(256 * 1024 * 1024)
        ctx.set_time_limit(10)
        ctx.eval(bundle.decode("utf-8"))
        ctx.eval(
            "const fontMetrics = " + json.dumps(metrics(), ensure_ascii=True) + ";"
        )
        ctx.eval((ROOT / "renderer.js").read_text(encoding="utf-8"))
        _LOCAL.context = ctx
    return _LOCAL.context


def render(source, theme="redux-color"):
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Mermaid source must not be empty")
    if theme not in THEMES:
        raise ValueError(f"Unknown theme {theme!r}; choose {', '.join(THEMES)}")
    try:
        reply = json.loads(
            _context().eval("renderRequest(" + json.dumps(source) + ",{})")
        )
    except Exception as exc:
        # Terminated/OOM contexts must not poison subsequent requests on this thread.
        _LOCAL.context = None
        raise RenderError(f"Pele execution failed: {exc}") from exc
    if "error" in reply:
        error = reply["error"]
        raise RenderError(
            f"{error['code']} at {error['line']}:{error['column']}: {error['message']}"
        )
    reply["result"]["svg"] = standalone_svg(reply["result"]["svg"], theme)
    return reply


def standalone_svg(svg, theme):
    root = ET.fromstring(svg)
    variables = {"--pele-" + k: v for k, v in THEMES[theme].items()}
    variables.update(
        {
            "--pele-font": "Noto Sans",
            "--pele-font-mono": "Noto Sans",
            "--pele-radius": "4px",
        }
    )
    variables.update(
        {
            k.strip(): v.strip()
            for part in root.get("style", "").split(";")
            if ":" in part
            for k, v in [part.split(":", 1)]
            if k.strip().startswith("--_")
        }
    )
    pattern = re.compile(r"var\((--[\w-]+)(?:,([^()]*))?\)")
    for el in root.iter():
        for key, value in list(el.attrib.items()):
            for _ in range(30):
                if "var(" not in value:
                    break
                updated = pattern.sub(lambda m: variables.get(m[1], m[2] or ""), value)
                if updated == value:
                    raise RenderError(f"Unsupported CSS variable {value}")
                value = updated
            if "var(" in value:
                raise RenderError("Cyclic CSS variable")
            el.set(key, value)
    # Namespace registration is process-global in ElementTree. Do not replace
    # the Visio writer's namespace (or race with other rendering threads).
    serialized = ET.tostring(root, encoding="unicode")
    match = re.match(r"<([\w]+):svg\b", serialized)
    if match:
        prefix = match[1]
        serialized = re.sub(r"(<\/?)" + prefix + ":", r"\1", serialized)
        serialized = serialized.replace("xmlns:" + prefix + "=", "xmlns=")
    return serialized
