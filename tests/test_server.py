"""MCP input handling and real stdio protocol/rendering checks."""

import asyncio
import builtins
from io import BytesIO
import sys
from zipfile import ZipFile

import pytest

from mermaid_render import server


def test_default_format_and_options(tmp_path, monkeypatch):
    calls = []

    def convert(source, **options):
        calls.append((source, options))
        return b"<svg/>"

    monkeypatch.setattr(server, "convert", convert)
    result = server.render_mermaid(
        str(tmp_path / "nested" / "diagram"),
        source="flowchart LR; A-->B",
        theme="dark",
        scale=1,
        background="transparent",
        title="Example",
        visio_connectors="straight",
    )
    path = tmp_path / "nested" / "diagram.svg"
    assert result == {
        "output_path": str(path),
        "format": "svg",
        "mime_type": "image/svg+xml",
    }
    assert path.read_bytes() == b"<svg/>"
    assert calls == [
        (
            "flowchart LR; A-->B",
            {
                "format": "svg",
                "theme": "dark",
                "scale": 1,
                "background": "transparent",
                "title": "Example",
                "visio_connectors": "straight",
            },
        )
    ]


@pytest.mark.parametrize(
    "arguments,message",
    [
        ({}, "exactly one"),
        ({"source": "graph LR", "input_path": "diagram.mmd"}, "exactly one"),
        ({"source": ""}, "must not be empty"),
        ({"input_path": ""}, "input_path must not be empty"),
        ({"input_path": "diagram.md"}, ".mmd or .mermaid"),
        ({"source": "graph LR", "format": "png"}, "must end with .png"),
    ],
)
def test_invalid_inputs_do_not_render(tmp_path, monkeypatch, arguments, message):
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid input reached the renderer")

    monkeypatch.setattr(server, "convert", unexpected)
    with pytest.raises(ValueError, match=message):
        server.render_mermaid(str(tmp_path / "diagram.svg"), **arguments)


def test_failed_render_preserves_output(tmp_path, monkeypatch):
    destination = tmp_path / "diagram.svg"
    destination.write_bytes(b"original")

    def fail(*args, **kwargs):
        raise RuntimeError("Mermaid syntax error")

    monkeypatch.setattr(server, "convert", fail)
    with pytest.raises(RuntimeError, match="syntax error"):
        server.render_mermaid(str(destination), source="bad diagram")
    assert destination.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [destination]


def test_missing_mcp_extra_has_install_hint(monkeypatch):
    original = builtins.__import__

    def import_without_mcp(name, *args, **kwargs):
        if name == "mcp.server":
            raise ModuleNotFoundError("No module named 'mcp'", name="mcp")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_mcp)
    with pytest.raises(SystemExit, match=r"mermaid-render\[mcp\]"):
        server.main()


def test_stdio_discovery_rendering_and_errors(tmp_path):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def exercise():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mermaid_render.server"],
            cwd=str(tmp_path),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                assert [tool.name for tool in tools] == ["render_mermaid"]
                schema = tools[0].input_schema
                assert schema["required"] == ["output_path"]
                assert (
                    "source" in schema["properties"]
                    and "input_path" in schema["properties"]
                )
                flowchart = "flowchart LR; A[Start] -->|Proceed| B[Done]"
                input_file = tmp_path / "flowchart.mmd"
                input_file.write_text(flowchart)
                for format, signature in [
                    ("svg", b"<svg"),
                    ("png", b"\x89PNG"),
                    ("vsdx", b"PK"),
                ]:
                    arguments = {"output_path": f"diagram.{format}"}
                    if format == "vsdx":
                        arguments.update(input_path=str(input_file), format="visio")
                    else:
                        arguments["source"] = flowchart
                    result = await session.call_tool("render_mermaid", arguments)
                    assert not result.is_error, result
                    assert result.structured_content["output_path"] == str(
                        tmp_path / f"diagram.{format}"
                    )
                    assert result.structured_content["format"] == format
                    data = (tmp_path / f"diagram.{format}").read_bytes()
                    assert signature in data[:100]
                    if format == "vsdx":
                        with ZipFile(BytesIO(data)) as archive:
                            assert b"<Connects>" in archive.read(
                                "visio/pages/page1.xml"
                            )
                # Errors are visible to the client, and an existing render survives.
                destination = tmp_path / "diagram.svg"
                original = destination.read_bytes()
                error = await session.call_tool(
                    "render_mermaid",
                    {
                        "output_path": str(destination),
                        "source": "not a valid Mermaid diagram",
                    },
                )
                assert error.is_error
                assert any(
                    "diagram" in block.text.lower()
                    for block in error.content
                    if hasattr(block, "text")
                )
                assert destination.read_bytes() == original
                error = await session.call_tool(
                    "render_mermaid", {"output_path": "unused.svg"}
                )
                assert error.is_error
                assert any(
                    "exactly one" in block.text
                    for block in error.content
                    if hasattr(block, "text")
                )

    asyncio.run(exercise())
