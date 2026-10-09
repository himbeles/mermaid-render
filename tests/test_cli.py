"""Exercise the renamed Python module entry point and CLI output selection."""
from __future__ import annotations

import sys

import pytest

from test_formats import stub_dist
from mermaid_render.cli import main


@pytest.mark.parametrize("extension,signature", [
    ("svg", b"<svg"),
    ("png", b"\x89PNG\r\n\x1a\n"),
    ("pdf", b"%PDF-"),
    ("vsdx", b"PK\x03\x04"),
])
def test_cli_format_inference(extension, signature, stub_dist, tmp_path, monkeypatch):
    input_path = tmp_path / "diagram.mmd"
    input_path.write_text("flowchart LR; A-->B", encoding="utf-8")
    output = tmp_path / f"diagram.{extension}"
    monkeypatch.setattr(sys, "argv", ["mermaid-render", str(input_path), "-o", str(output)])
    main()
    assert signature in output.read_bytes()
    if extension == 'png':
        import struct
        assert struct.unpack('>II', output.read_bytes()[16:24]) == (800, 260)


@pytest.mark.parametrize("option", ["--mermaid-dist", "--chromium"])
def test_cli_rejects_manual_runtime_paths(option, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["mermaid-render", "example.mmd", option, str(tmp_path)])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


def test_cli_defaults_to_svg(stub_dist, tmp_path, monkeypatch):
    source = tmp_path / 'diagram.mmd'
    source.write_text('flowchart LR; A-->B', encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['mermaid-render', str(source)])
    main()
    assert b'<svg' in source.with_suffix('.svg').read_bytes()
    assert not source.with_suffix('.vsdx').exists()


@pytest.mark.parametrize('routing', [None, 'right-angle', 'straight', 'mermaid'])
def test_cli_visio_connector_routing(routing, tmp_path, monkeypatch):
    source = tmp_path / 'diagram.mmd'
    source.write_text('flowchart LR; A-->B')
    calls = []
    monkeypatch.setattr('mermaid_render.cli.convert', lambda *args, **kwargs: calls.append(kwargs))
    argv = ['mermaid-render', str(source), '-f', 'vsdx']
    if routing:
        argv += ['--visio-connectors', routing]
    monkeypatch.setattr(sys, 'argv', argv)
    main()
    assert calls[0]['visio_connectors'] == (routing or 'right-angle')
