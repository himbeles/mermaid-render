"""CLI output inference, format validation, and connector options."""

import sys
import pytest
from mermaid_render.cli import main


@pytest.mark.parametrize(
    "extension,signature", [("svg", b"<svg"), ("png", b"\x89PNG"), ("vsdx", b"PK")]
)
def test_cli_format_inference(extension, signature, tmp_path, monkeypatch):
    source = tmp_path / "diagram.mmd"
    source.write_text("flowchart LR; A-->B")
    out = tmp_path / f"diagram.{extension}"
    monkeypatch.setattr(sys, "argv", ["mermaid-render", str(source), "-o", str(out)])
    main()
    assert signature in out.read_bytes()[:100]


def test_cli_defaults_to_svg(tmp_path, monkeypatch):
    source = tmp_path / "diagram.mmd"
    source.write_text("flowchart LR; A-->B")
    monkeypatch.setattr(sys, "argv", ["mermaid-render", str(source)])
    main()
    assert b"<svg" in source.with_suffix(".svg").read_bytes()


@pytest.mark.parametrize("routing", [None, "right-angle", "straight", "mermaid"])
def test_cli_visio_connector_routing(routing, tmp_path, monkeypatch):
    source = tmp_path / "diagram.mmd"
    source.write_text("flowchart LR; A-->B")
    calls = []
    monkeypatch.setattr("mermaid_render.cli.convert", lambda *a, **kw: calls.append(kw))
    argv = ["mermaid-render", str(source), "-f", "vsdx"]
    if routing:
        argv += ["--visio-connectors", routing]
    monkeypatch.setattr(sys, "argv", argv)
    main()
    assert calls[0]["visio_connectors"] == (routing or "right-angle")


def test_cli_rejects_unsupported_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["mermaid-render", "example.mmd", "-o", str(tmp_path / "out.gif")]
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
