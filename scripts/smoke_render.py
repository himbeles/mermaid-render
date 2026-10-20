"""Verify installed-wheel rendering without network or executable access."""

import os
from io import BytesIO
import socket
import subprocess
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from mermaid_render import convert, svg_to_vsdx

os.environ["PATH"] = ""


def forbidden(*args, **kwargs):
    raise AssertionError(
        "Rendering attempted network access or started an external executable"
    )


socket.socket.connect = forbidden
socket.create_connection = forbidden
subprocess.Popen = forbidden
SOURCES = {
    "flowchart": "flowchart LR; A[Input] -->|Process| B{Valid?}; B --> C(Done)",
    "state": "stateDiagram-v2\n[*] --> Idle\nIdle --> Running : start\nRunning --> [*]",
    "class": 'classDiagram\nclass A {\n+String name\n}\nA "1" --> "*" B : uses',
    "sequence": "sequenceDiagram\nparticipant A as Alice\nparticipant B as Bob\nA->>+B: Request\nB-->>-A: Reply",
}
NS = {"v": "http://schemas.microsoft.com/office/visio/2012/main"}
for kind, source in SOURCES.items():
    svg = convert(source)
    assert ET.fromstring(svg).tag.endswith("svg")
    assert convert(source, format="png").startswith(b"\x89PNG\r\n\x1a\n")
    with ZipFile(BytesIO(convert(source, format="vsdx"))) as archive:
        assert archive.testzip() is None
        page = ET.fromstring(archive.read("visio/pages/page1.xml"))
        assert len(page.findall("v:Connects/v:Connect", NS)) >= 2
assert svg_to_vsdx(
    '<svg xmlns="http://www.w3.org/2000/svg"><rect width="50" height="30"/></svg>'
).startswith(b"PK")
try:
    convert(SOURCES["flowchart"], format="gif")
except ValueError as exc:
    assert "format must" in str(exc)
else:
    raise AssertionError("Unsupported format was accepted")
print(
    "Installed-wheel rendering smoke test passed: SVG/PNG and all four connected VSDX types; no network, Node, browser, or subprocess."
)
