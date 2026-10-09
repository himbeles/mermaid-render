"""Persistent support installation and bundled precedence."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
import mermaid_render.assets as assets


def mermaid(directory):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'VERSION.json').write_text(json.dumps({'version': assets.DEFAULT_VERSION}))
    (directory / 'mermaid.esm.min.mjs').write_text('stub')


@pytest.fixture
def roots(tmp_path, monkeypatch):
    package, support = tmp_path / 'package', tmp_path / 'support'
    monkeypatch.setattr(assets, 'package_root', lambda: package)
    monkeypatch.setattr(assets, 'data_root', lambda: support)
    return package, support


def test_bundle_precedes_support_without_writing(roots, monkeypatch):
    package, support = roots
    mermaid(package / 'runtime')
    monkeypatch.setattr(assets, 'download_mermaid', lambda _: pytest.fail('unexpected download'))
    assert assets.ensure_mermaid() == package / 'runtime'
    assert not support.exists()


def test_install_once_and_reuse_concurrently(roots, monkeypatch):
    calls = []
    def install(directory):
        calls.append(directory)
        mermaid(directory)
    monkeypatch.setattr(assets, 'download_mermaid', install)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: assets.ensure_mermaid(), range(4)))
    expected = roots[1] / 'mermaid' / assets.DEFAULT_VERSION
    assert results == [expected] * 4
    assert len(calls) == 1
    assert assets.ensure_mermaid() == expected
    assert len(calls) == 1
    assert not list(expected.parent.glob('.install-*'))


def test_failed_install_is_not_exposed_and_can_retry(roots, monkeypatch):
    def broken(directory):
        (directory / 'partial').write_text('partial')
        raise OSError('network unavailable')
    monkeypatch.setattr(assets, 'download_mermaid', broken)
    with pytest.raises(assets.RuntimeSetupError, match='network unavailable') as failure:
        assets.ensure_mermaid()
    assert assets.RELEASES_URL in str(failure.value)
    assert 'uv tool install' in str(failure.value)
    target = roots[1] / 'mermaid' / assets.DEFAULT_VERSION
    assert not target.exists()
    assert not list(target.parent.glob('.install-*'))
    monkeypatch.setattr(assets, 'download_mermaid', mermaid)
    assert assets.ensure_mermaid() == target


def test_browser_install_and_version_isolation(roots, monkeypatch):
    monkeypatch.setattr(assets, 'browser_version', lambda: '1.test')
    calls = []
    def install(directory):
        calls.append(directory)
        executable = directory / 'shell'
        executable.write_text('stub')
        executable.chmod(0o755)
        (directory / 'BROWSER_INFO.json').write_text(json.dumps({
            'executable': 'shell', 'playwright_version': assets.browser_version()}))
    monkeypatch.setattr(assets, 'install_browser', install)
    first = assets.ensure_browser()
    assert assets.ensure_browser() == first
    assert len(calls) == 1
    monkeypatch.setattr(assets, 'browser_version', lambda: '2.test')
    second = assets.ensure_browser()
    assert second != first and first.is_file() and second.is_file()
    assert len(calls) == 2


def test_browser_bundle_takes_precedence(roots, monkeypatch):
    package, support = roots
    directory = package / 'browsers'
    directory.mkdir(parents=True)
    executable = directory / 'shell'
    executable.write_text('stub')
    executable.chmod(0o755)
    (directory / 'BROWSER_INFO.json').write_text(json.dumps({
        'executable': 'shell', 'playwright_version': assets.browser_version()}))
    monkeypatch.setattr(assets, 'install_browser', lambda _: pytest.fail('unexpected download'))
    assert assets.ensure_browser() == executable
    assert not support.exists()


@pytest.mark.parametrize('keyword', ['mermaid_dist', 'chromium_executable'])
def test_render_api_rejects_runtime_paths(keyword):
    from mermaid_render import convert
    with pytest.raises(TypeError, match='unexpected keyword'):
        convert('flowchart LR; A-->B', **{keyword: '/somewhere'})


@pytest.mark.parametrize('bundled', [True, False])
def test_setup_populates_support_and_reuses_existing_files(roots, monkeypatch, bundled):
    package, support = roots
    def browser(directory):
        directory.mkdir(parents=True, exist_ok=True)
        executable = directory / 'shell'
        executable.write_text('browser')
        executable.chmod(0o755)
        (directory / 'BROWSER_INFO.json').write_text(json.dumps({
            'executable': 'shell', 'playwright_version': assets.browser_version()}))
    if bundled:
        mermaid(package / 'runtime')
        browser(package / 'browsers')
        (package / 'runtime' / 'chunks').mkdir()
        (package / 'runtime' / 'chunks' / 'module.mjs').write_text('chunk')
        (package / 'browsers' / 'LICENSE').write_text('license')
        def unexpected_download(_):
            pytest.fail('setup should copy bundled files without downloading')
        monkeypatch.setattr(assets, 'download_mermaid', unexpected_download)
        monkeypatch.setattr(assets, 'install_browser', unexpected_download)
    else:
        monkeypatch.setattr(assets, 'download_mermaid', mermaid)
        monkeypatch.setattr(assets, 'install_browser', browser)
    runtime, executable = assets.setup_runtime()
    assert runtime == support / 'mermaid' / assets.DEFAULT_VERSION
    assert executable.is_relative_to(support / 'browsers')
    assert assets.mermaid_in(runtime) == runtime
    assert assets.browser_in(executable.parent) == executable
    if bundled:
        assert (runtime / 'chunks' / 'module.mjs').read_text() == 'chunk'
        assert (executable.parent / 'LICENSE').read_text() == 'license'
        assert (executable.stat().st_mode & 0o777) == ((package / 'browsers' / 'shell').stat().st_mode & 0o777)
    # Valid support files remain untouched even when the bundle is present.
    (runtime / 'mermaid.esm.min.mjs').write_text('existing runtime')
    executable.write_text('existing browser')
    assert assets.setup_runtime() == (runtime, executable)
    assert (runtime / 'mermaid.esm.min.mjs').read_text() == 'existing runtime'
    assert executable.read_text() == 'existing browser'
    # Removing the installed bundle still permits reuse without downloads.
    if bundled:
        assets.shutil.rmtree(package)
        assert assets.ensure_mermaid() == runtime
        assert assets.ensure_browser() == executable


def test_failed_bundle_copy_is_not_exposed(roots, monkeypatch):
    mermaid(roots[0] / 'runtime')
    def broken_copy(source, destination, **kwargs):
        (destination / 'partial').write_text('partial')
        raise OSError('disk full')
    monkeypatch.setattr(assets.shutil, 'copytree', broken_copy)
    with pytest.raises(assets.RuntimeSetupError, match='disk full'):
        assets.setup_runtime()
    target = roots[1] / 'mermaid' / assets.DEFAULT_VERSION
    assert not target.exists()
    assert not list(target.parent.glob('.install-*'))
