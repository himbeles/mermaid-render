"""Determine wheel compatibility from the native bundled browser payload."""
from __future__ import annotations

import platform
import re
import subprocess
from pathlib import Path

MACHO_MAGICS = {
    bytes.fromhex(value) for value in (
        'feedface', 'cefaedfe', 'feedfacf', 'cffaedfe',
        'cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca',
    )
}


def macos_minimum(browsers: Path) -> tuple[int, int]:
    versions = []
    for path in browsers.rglob('*'):
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            if stream.read(4) not in MACHO_MAGICS:
                continue
        output = subprocess.run(
            ['otool', '-l', str(path)], check=True, capture_output=True, text=True,
        ).stdout
        matches = re.findall(
            r'cmd LC_(?:BUILD_VERSION|VERSION_MIN_MACOSX)\b(?:(?!\nLoad command)[\s\S])*?\n\s*(?:minos|version) (\d+)\.(\d+)',
            output,
        )
        if not matches:
            raise RuntimeError(f'Cannot determine macOS minimum for {path}')
        versions.extend((int(major), int(minor)) for major, minor in matches)
    if not versions:
        raise RuntimeError(f'No Mach-O binaries found in {browsers}')
    major, minor = max(versions)
    # Wheel tags use major.0 for macOS 11 and later. Round up if a binary
    # requires a later minor release, so the tag never understates its minimum.
    return (major + bool(minor), 0) if major >= 11 else (major, minor)


def platform_tag(browsers: Path) -> str:
    system = platform.system()
    machine = platform.machine().lower()
    if machine in {'amd64', 'x86_64'}:
        arch = 'x86_64'
    elif machine in {'arm64', 'aarch64'}:
        arch = 'arm64'
    else:
        raise RuntimeError(f'Unsupported architecture: {machine}')
    if system == 'Darwin':
        major, minor = macos_minimum(browsers)
        return f'macosx_{major}_{minor}_{arch}'
    if system == 'Linux' and arch == 'x86_64':
        return 'linux_x86_64'
    if system == 'Windows' and arch == 'x86_64':
        return 'win_amd64'
    raise RuntimeError(f'Unsupported platform: {system}/{machine}')
