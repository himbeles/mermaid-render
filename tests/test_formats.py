"""Real embedded rendering, native PNG, and public format behavior."""

from io import BytesIO
import struct
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from mermaid_render import convert

SOURCE = "flowchart LR; A[Input] -->|Process| B{Valid?}; B -->|Yes| C(Done)"
NS = {"v": "http://schemas.microsoft.com/office/visio/2012/main"}


def test_svg_output(tmp_path):
    out = tmp_path / "diagram.svg"
    data = convert(SOURCE, out)
    assert out.read_bytes() == data
    root = ET.fromstring(data)
    assert root.tag.endswith("svg") and "pele-flowchart" in root.get("class")
    assert "var(" not in data.decode()


@pytest.mark.parametrize("id_", ["A", "A-with-dashes"])
def test_connected_vsdx_output(id_, tmp_path):
    source = SOURCE.replace("A[", id_ + "[")
    out = tmp_path / "diagram.vsdx"
    data = convert(source, out)
    with ZipFile(BytesIO(data)) as archive:
        assert archive.testzip() is None
        page = ET.fromstring(archive.read("visio/pages/page1.xml"))
    assert len(page.findall("v:Shapes/v:Shape", NS)) == 5
    assert len(page.findall("v:Connects/v:Connect", NS)) == 4
    assert {"Input", "Valid?", "Done", "Process", "Yes"} == {
        t.text for t in page.findall(".//v:Text", NS)
    }
    assert out.read_bytes() == data


@pytest.mark.parametrize("scale", [1, 2, 3])
def test_png_output_and_scale(scale, tmp_path):
    svg = ET.fromstring(convert(SOURCE))
    out = tmp_path / "diagram.png"
    data = convert(SOURCE, out, scale=scale)
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and out.read_bytes() == data
    assert struct.unpack(">II", data[16:24]) == (
        round(float(svg.get("width")) * scale),
        round(float(svg.get("height")) * scale),
    )


def test_png_backgrounds():
    from PIL import Image

    transparent = Image.open(
        BytesIO(convert(SOURCE, format="png", background="transparent"))
    ).convert("RGBA")
    white = Image.open(BytesIO(convert(SOURCE, format="png"))).convert("RGBA")
    assert transparent.getpixel((0, 0))[3] == 0
    assert white.getpixel((0, 0)) == (255, 255, 255, 255)


def test_format_validation(tmp_path):
    with pytest.raises(ValueError, match="format must"):
        convert(SOURCE, format="gif")
    with pytest.raises(ValueError, match="format must"):
        convert(SOURCE, tmp_path / "out.gif")
    with pytest.raises(ValueError, match="Output filename"):
        convert(SOURCE, tmp_path / "out.svg", format="png")
    assert convert(SOURCE, format="visio").startswith(b"PK")
    for scale in [-1, 0, 5, float("nan")]:
        with pytest.raises(ValueError, match="scale must"):
            convert(SOURCE, scale=scale)
    with pytest.raises(ValueError, match="background"):
        convert(SOURCE, format="png", background="")
    with pytest.raises(ValueError, match="visio_connectors"):
        convert(SOURCE, visio_connectors="curvy")


def test_other_diagram_formats():
    source = 'pie title Pets\n"Cats": 40\n"Dogs": 60'
    assert b"<svg" in convert(source)
    assert convert(source, format="png").startswith(b"\x89PNG")
    with pytest.raises(ValueError, match="Connected VSDX supports"):
        convert(source, format="vsdx")


def test_failed_conversion_does_not_replace_file(tmp_path):
    out = tmp_path / "existing.svg"
    out.write_bytes(b"original")
    with pytest.raises(ValueError):
        convert("flowchart LR; A[", out)
    assert out.read_bytes() == b"original"
