"""Exercise the renamed Python module entry point and CLI output selection."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from test_formats import BROWSER, stub_dist


@pytest.mark.parametrize("extension,signature", [
    ("svg", b"<svg"),
    ("png", b"\x89PNG\r\n\x1a\n"),
    ("pdf", b"%PDF-"),
    ("vsdx", b"PK\x03\x04"),
])
def test_cli_format_inference(extension, signature, stub_dist, tmp_path):
    input_path = tmp_path / "diagram.mmd"
    input_path.write_text("flowchart LR; A-->B", encoding="utf-8")
    output = tmp_path / f"diagram.{extension}"
    args = [
        sys.executable, "-m", "mermaid_render", str(input_path),
        "-o", str(output), "--mermaid-dist", str(stub_dist),
    ]
    if BROWSER:
        args += ["--chromium", BROWSER]
    result = subprocess.run(args, capture_output=True, text=True, env=os.environ)
    assert result.returncode == 0, result.stderr
    assert signature in output.read_bytes()
