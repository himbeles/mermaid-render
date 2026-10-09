"""Cross-platform wheel metadata, included assets, and Chromium discovery."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import mermaid_render.api as api
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_platform_wheel import find_shell
from wheel_platform import macos_minimum, platform_tag


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



def test_macos_tag_uses_highest_binary_minimum(tmp_path, monkeypatch):
    import wheel_platform
    from types import SimpleNamespace

    for name in ('shell', 'library.dylib'):
        (tmp_path / name).write_bytes(bytes.fromhex('cffaedfe'))
    (tmp_path / 'notice.txt').write_text('license')

    def otool(command, **kwargs):
        minimum = '13.0' if command[-1].endswith('shell') else '14.0'
        return SimpleNamespace(stdout=f'Load command 1\n cmd LC_BUILD_VERSION\n minos {minimum}\n sdk 26.5\n')

    monkeypatch.setattr(wheel_platform.subprocess, 'run', otool)
    monkeypatch.setattr(wheel_platform.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(wheel_platform.platform, 'machine', lambda: 'arm64')
    assert platform_tag(tmp_path) == 'macosx_14_0_arm64'


def test_legacy_macos_load_command(tmp_path, monkeypatch):
    import wheel_platform
    from types import SimpleNamespace

    (tmp_path / 'shell').write_bytes(bytes.fromhex('feedfacf'))
    monkeypatch.setattr(wheel_platform.subprocess, 'run', lambda *a, **kw: SimpleNamespace(
        stdout='Load command 1\n cmd LC_VERSION_MIN_MACOSX\n version 10.15\n sdk 11.0\n'))
    assert macos_minimum(tmp_path) == (10, 15)


def test_macos_payload_without_version_is_rejected(tmp_path, monkeypatch):
    import pytest
    import wheel_platform
    from types import SimpleNamespace

    (tmp_path / 'shell').write_bytes(bytes.fromhex('cffaedfe'))
    monkeypatch.setattr(wheel_platform.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=''))
    with pytest.raises(RuntimeError, match='Cannot determine'):
        macos_minimum(tmp_path)


def test_non_macos_tags(tmp_path, monkeypatch):
    import wheel_platform

    monkeypatch.setattr(wheel_platform.platform, 'machine', lambda: 'AMD64')
    for system, tag in [('Windows', 'win_amd64'), ('Linux', 'linux_x86_64')]:
        monkeypatch.setattr(wheel_platform.platform, 'system', lambda: system)
        assert platform_tag(tmp_path) == tag
