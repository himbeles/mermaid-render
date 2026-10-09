"""Cross-platform wheel metadata, included assets, and Chromium discovery."""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import mermaid_render.api as api
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_platform_wheel import find_shell
from retag_wheel import retag


def test_find_headless_shell(tmp_path):
    executable = tmp_path / 'chromium_headless_shell-1234' / 'chrome-headless-shell-linux64' / 'chrome-headless-shell'
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'fake executable')
    assert find_shell(tmp_path) == executable


def test_finds_manifest_bundled_executable(tmp_path, monkeypatch):
    fake_package_dir = tmp_path / 'mermaid_render'
    fake_package_dir.mkdir()
    monkeypatch.setattr(api, '__file__', str(fake_package_dir / 'api.py'))
    browsers = fake_package_dir / 'browsers'
    browsers.mkdir()
    exe = browsers / 'chromium_headless_shell-123' / 'chrome-headless-shell-mac-arm64' / 'chrome-headless-shell'
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b'stub')
    (browsers / 'BROWSER_INFO.json').write_text(json.dumps({'executable': exe.relative_to(browsers).as_posix()}))
    assert api._bundled_chromium() == exe


def test_disallows_manifest_path_escape(tmp_path, monkeypatch):
    fake_package = tmp_path / 'mermaid_render'
    fake_package.mkdir()
    monkeypatch.setattr(api, '__file__', str(fake_package / 'api.py'))
    browsers = fake_package / 'browsers'
    browsers.mkdir()
    (browsers / 'BROWSER_INFO.json').write_text(json.dumps({'executable':'../../etc/passwd'}))
    try:
        api._bundled_chromium()
    except ValueError as e:
        assert 'Invalid' in str(e)
    else:
        raise AssertionError('Unsafe path not rejected')


def test_retag_preserves_executable_bits_and_record(tmp_path):
    filename = tmp_path / 'mermaid_render-0.6.0-py3-none-any.whl'
    wheel = 'mermaid_render-0.6.0.dist-info/WHEEL'
    record = 'mermaid_render-0.6.0.dist-info/RECORD'
    with ZipFile(filename, 'w') as z:
        z.writestr(wheel, 'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
        z.writestr(record, '')
        from zipfile import ZipInfo
        exe = ZipInfo('mermaid_render/browsers/chrome-headless-shell')
        exe.create_system = 3
        exe.external_attr = 0o100755 << 16
        z.writestr(exe, b'chromium fake')
    dest = retag(filename, 'macosx_15_0_arm64')
    with ZipFile(dest) as z:
        meta = z.read(wheel).decode()
        assert 'Tag: py3-none-macosx_15_0_arm64' in meta
        assert 'Root-Is-Purelib: false' in meta
        assert (z.getinfo(exe.filename).external_attr >> 16) & 0o111 == 0o111
        entries = {row[0]: row[1:] for row in csv.reader(io.StringIO(z.read(record).decode()))}
        for name in (wheel, exe.filename):
            blob = z.read(name)
            signature = base64.urlsafe_b64encode(hashlib.sha256(blob).digest()).rstrip(b'=').decode()
            assert entries[name] == [f'sha256={signature}', str(len(blob))]
