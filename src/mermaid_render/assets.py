"""Resolve bundled runtimes or install them in persistent per-user support data."""
from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Callable

from filelock import FileLock
from platformdirs import user_data_path

from .vendor import DEFAULT_VERSION, download_mermaid

RELEASES_URL = 'https://github.com/himbeles/mermaid-render/releases'
SHELL_NAMES = {'chrome-headless-shell', 'chrome-headless-shell.exe', 'headless_shell'}


class RuntimeSetupError(RuntimeError):
    """Runtime installation failed, with an actionable offline alternative."""


def data_root() -> Path:
    return user_data_path('mermaid-render', appauthor=False)


def package_root() -> Path:
    return Path(__file__).resolve().parent


def browser_version() -> str:
    return importlib.metadata.version('playwright')


def find_shell(browsers: Path) -> Path:
    candidates = sorted(p for p in browsers.glob('chromium_headless_shell-*/*/*')
                        if p.is_file() and p.name in SHELL_NAMES)
    if len(candidates) != 1:
        raise RuntimeError(f'Expected exactly one Chromium Headless Shell in {browsers}, got: {candidates}')
    return candidates[0]


def browser_in(directory: Path) -> Path | None:
    manifest = directory / 'BROWSER_INFO.json'
    if not manifest.is_file():
        return None
    info = json.loads(manifest.read_text(encoding='utf-8'))
    relative = Path(info['executable'])
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Invalid Chromium executable path')
    executable = (directory / relative).resolve()
    executable.relative_to(directory.resolve())
    if info.get('playwright_version') != browser_version() or not executable.is_file():
        return None
    if os.name != 'nt' and not os.access(executable, os.X_OK):
        return None
    return executable


def bundled_browser() -> Path | None:
    return browser_in(package_root() / 'browsers')


def mermaid_in(directory: Path) -> Path | None:
    manifest = directory / 'VERSION.json'
    if not manifest.is_file() or not (directory / 'mermaid.esm.min.mjs').is_file():
        return None
    info = json.loads(manifest.read_text(encoding='utf-8'))
    return directory if info.get('version') == DEFAULT_VERSION else None


def install_browser(destination: Path) -> None:
    env = os.environ.copy()
    env['PLAYWRIGHT_BROWSERS_PATH'] = str(destination)
    env['PLAYWRIGHT_SKIP_BROWSER_GC'] = '1'
    result = subprocess.run(
        [sys.executable, '-m', 'playwright', 'install', '--only-shell', 'chromium'],
        env=env, capture_output=True, text=True, timeout=300,
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip() or 'Playwright browser download failed')
    shell = find_shell(destination)
    if os.name != 'nt':
        shell.chmod(shell.stat().st_mode | 0o111)
    (destination / 'BROWSER_INFO.json').write_text(json.dumps({
        'executable': shell.relative_to(destination).as_posix(),
        'playwright_version': browser_version(),
    }, indent=2) + '\n', encoding='utf-8')


def _ensure(name: str, bundled: Path, target: Path, ready: Callable, install: Callable,
            *, persist: bool = False) -> Path:
    try:
        found = ready(target) or (None if persist else ready(bundled))
        if found:
            return found
        root = data_root()
        root.mkdir(parents=True, exist_ok=True)
        with FileLock(str(root / '.setup.lock'), timeout=360):
            # Another process may have finished while we waited for its lock.
            found = ready(target) or (None if persist else ready(bundled))
            if found:
                return found
            target.parent.mkdir(parents=True, exist_ok=True)
            print(f'Installing {name} support files in {target}...', file=sys.stderr)
            with tempfile.TemporaryDirectory(prefix='.install-', dir=target.parent) as temporary:
                staged = Path(temporary) / 'payload'
                staged.mkdir()
                if persist and ready(bundled):
                    shutil.copytree(bundled, staged, dirs_exist_ok=True)
                else:
                    install(staged)
                if not ready(staged):
                    raise RuntimeError(f'{name} installation is incomplete')
                # Only an incomplete installation can reach this point. Keep it
                # until the replacement is fully downloaded and validated.
                if target.exists():
                    shutil.rmtree(target)
                staged.replace(target)
            return ready(target)
    except (OSError, RuntimeError, ValueError, KeyError, tarfile.TarError, subprocess.SubprocessError) as exc:
        raise RuntimeSetupError(
            f'Could not prepare {name}: {exc}\n'
            f'For offline use, download the bundled wheel for your OS from {RELEASES_URL} '
            'and install it with: uv tool install --force /path/to/bundled.whl'
        ) from exc


def ensure_mermaid(*, persist: bool = False) -> Path:
    return _ensure('Mermaid', package_root() / 'runtime',
                   data_root() / 'mermaid' / DEFAULT_VERSION, mermaid_in, download_mermaid, persist=persist)


def ensure_browser(*, persist: bool = False) -> Path:
    key = f'playwright-{browser_version()}-{platform.system().lower()}-{platform.machine().lower()}'
    return _ensure('Chromium', package_root() / 'browsers',
                   data_root() / 'browsers' / key, browser_in, install_browser, persist=persist)


def setup_runtime() -> tuple[Path, Path]:
    """Populate persistent support data, copying valid bundled assets offline."""
    return ensure_mermaid(persist=True), ensure_browser(persist=True)
