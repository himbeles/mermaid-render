"""Embedded runtime resources, offline behavior, isolation, and limits."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import socket
import subprocess

import pytest
from mermaid_render import convert, svg_to_vsdx
from mermaid_render.renderer import ROOT, _LOCAL


def test_runtime_is_bundled_and_offline(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("Network or external executable attempted")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setenv("PATH", "")
    _LOCAL.context = None
    for source in [
        "flowchart LR; A-->B",
        "stateDiagram-v2\n[*]-->Ready",
        "classDiagram\nA-->B",
        "sequenceDiagram\nA->>B:Hello",
    ]:
        for format in ["svg", "png", "vsdx"]:
            assert convert(source, format=format)


def test_bundle_integrity_and_licenses():
    info = json.loads((ROOT / "pele/manifest.json").read_text())
    assert (
        hashlib.sha256((ROOT / "pele/pele.global.js").read_bytes()).hexdigest()
        == info["sha256"]
    )
    assert "MIT License" in (ROOT / "pele/LICENSE").read_text()
    assert "OPEN FONT LICENSE" in (ROOT / "fonts/LICENSE").read_text()


def test_concurrent_rendering_and_error_recovery():
    def job(i):
        source = f"flowchart LR; A[Unique{i}]-->B"
        with pytest.raises(ValueError):
            convert("flowchart LR; A[")
        return convert(source).decode()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(job, range(12)))
    assert all(f"Unique{i}" in svg for i, svg in enumerate(results))
    assert "<ns0:" not in convert("flowchart LR; A-->B").decode()
    assert b"<Connects>" in __import__("zipfile").ZipFile(
        __import__("io").BytesIO(convert("flowchart LR; A-->B", format="vsdx"))
    ).read("visio/pages/page1.xml")


def test_limits_and_source_errors():
    with pytest.raises(ValueError, match="limit"):
        convert("flowchart LR\n" + "x" * 51_000)
    with pytest.raises(ValueError, match="Unknown theme"):
        convert("flowchart LR; A-->B", theme="unknown")
    assert convert("flowchart LR; A-->B")


@pytest.mark.parametrize(
    "element", ["image", "script", "foreignObject", "use", "filter"]
)
def test_svg_external_and_browser_elements_are_rejected(element):
    with pytest.raises(ValueError, match="Unsupported SVG element"):
        svg_to_vsdx(f'<svg xmlns="http://www.w3.org/2000/svg"><{element}/></svg>')
