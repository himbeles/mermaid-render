"""Private Linux browser dependencies remain relocatable and isolated."""
import json
import os
from pathlib import Path
import sys

import pytest
import mermaid_render.assets as assets

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from bundle_linux import dependencies


def test_library_closure_excludes_host_glibc_and_rejects_missing_dependencies():
    output = '''linux-vdso.so.1 (0x0000)
    libnss3.so => /usr/lib/x86_64-linux-gnu/libnss3.so (0x00ff)
    libc.so.6 => /usr/lib/x86_64-linux-gnu/libc.so.6 (0x00ab)
    libstdc++.so.6 => /usr/lib/x86_64-linux-gnu/libstdc++.so.6 (0x00cd)
    /lib64/ld-linux-x86-64.so.2 (0x00ef)
'''
    assert set(dependencies(output)) == {'libnss3.so', 'libstdc++.so.6'}
    with pytest.raises(RuntimeError, match='Install Chromium build dependencies'):
        dependencies(output + 'libnspr4.so => not found\n')


def test_private_linux_runtime_survives_setup_and_does_not_reuse_unbundled_support(tmp_path, monkeypatch):
    package, support = tmp_path / 'package', tmp_path / 'support'
    monkeypatch.setattr(assets, 'package_root', lambda: package)
    monkeypatch.setattr(assets, 'data_root', lambda: support)
    monkeypatch.setattr(assets.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(assets.platform, 'machine', lambda: 'x86_64')
    monkeypatch.setattr(assets, 'install_browser', lambda _: pytest.fail('unexpected download'))
    browser = package / 'browsers'
    executable = browser / 'chromium_headless_shell-123' / 'chrome-headless-shell-linux64' / 'chrome-headless-shell'
    executable.parent.mkdir(parents=True)
    executable.write_text('browser')
    executable.chmod(0o755)
    runtime = executable.parent / 'linux-runtime'
    library = runtime / 'lib' / 'libnss3.so'
    library.parent.mkdir(parents=True)
    library.write_text('private library')
    config = runtime / 'fonts.conf'
    config.write_text('<fontconfig/>')
    manifest = {
        'executable': executable.relative_to(browser).as_posix(),
        'playwright_version': assets.browser_version(),
        'linux_runtime': {'id': '1234567890abcdef', 'files': [p.relative_to(browser).as_posix()
                                                           for p in [library, config]]},
    }
    (browser / 'BROWSER_INFO.json').write_text(json.dumps(manifest))
    old = support / 'browsers' / f'playwright-{assets.browser_version()}-linux-x86_64'
    old.mkdir(parents=True)
    (old / 'shell').write_text('old downloaded browser')
    (old / 'shell').chmod(0o755)
    (old / 'BROWSER_INFO.json').write_text(json.dumps({
        'executable': 'shell', 'playwright_version': assets.browser_version()}))
    assert assets.ensure_browser() == executable
    persisted = assets.ensure_browser(persist=True)
    assert persisted.is_relative_to(support)
    assert assets.ensure_browser() == persisted
    assert (persisted.parent / 'linux-runtime/lib/libnss3.so').read_text() == 'private library'
    monkeypatch.setenv('LD_LIBRARY_PATH', '/existing/libraries')
    original = os.environ.copy()
    env = assets.browser_environment(persisted)
    assert env['LD_LIBRARY_PATH'] == str(persisted.parent / 'linux-runtime/lib') + os.pathsep + '/existing/libraries'
    assert env['FONTCONFIG_FILE'] == str(persisted.parent / 'linux-runtime/fonts.conf')
    assert os.environ == original
    (persisted.parent / 'linux-runtime/lib/libnss3.so').unlink()
    assert assets.browser_in(persisted.parents[2]) is None
    assert assets.ensure_browser() == executable  # Fall back to the complete package bundle.


def test_unbundled_browser_environment_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(assets.platform, 'system', lambda: 'Linux')
    assert assets.browser_environment(tmp_path / 'shell') == os.environ.copy()


def test_static_browser_helpers_have_no_shared_dependencies(monkeypatch):
    import bundle_linux
    import subprocess
    def static(*args):
        raise subprocess.CalledProcessError(1, args, stderr='not a dynamic executable')
    monkeypatch.setattr(bundle_linux, '_run', static)
    assert bundle_linux._linked(Path('ffmpeg-linux')) == {}
