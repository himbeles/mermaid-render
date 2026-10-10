"""Collect Chromium's Linux library closure and fonts from the build host.

glibc and its loader remain host-provided. Build on the oldest supported
distribution; the resulting private libraries never enter Python's environment.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path


SYSTEM_LIBRARIES = {
    'libc.so.6', 'libm.so.6', 'libpthread.so.0', 'libdl.so.2',
    'librt.so.1', 'libresolv.so.2', 'libutil.so.1', 'libanl.so.1',
    'ld-linux-x86-64.so.2', 'ld-linux-aarch64.so.1',
}


def dependencies(output: str) -> dict[str, Path]:
    if '=> not found' in output:
        raise RuntimeError(f'Install Chromium build dependencies first:\n{output}')
    return {name: Path(path) for name, path in
            re.findall(r'^\s*(\S+)\s+=>\s+(/.+?)\s+\(0x[0-9a-fA-F]+\)', output, re.M)
            if name not in SYSTEM_LIBRARIES}


def _run(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def _linked(binary: Path) -> dict[str, Path]:
    try:
        return dependencies(_run('ldd', str(binary)))
    except subprocess.CalledProcessError as exc:
        # Playwright's FFmpeg helper is a static ELF binary.
        output = (exc.stdout or '') + (exc.stderr or '')
        if 'not a dynamic executable' in output or 'statically linked' in output:
            return {}
        raise


def _license(path: Path, destination: Path) -> None:
    # Debian/Ubuntu's copyright files identify the license and source location
    # for each redistributed library/font, including its upstream components.
    for candidate in dict.fromkeys((path, path.resolve())):
        try:
            matches = _run('dpkg-query', '-S', str(candidate))
            break
        except subprocess.CalledProcessError:
            continue
    else:
        raise RuntimeError(f'Cannot identify redistribution notice for {path}')
    packages = {line.rsplit(': ', 1)[0].split(':', 1)[0] for line in matches.splitlines()}
    for package in sorted(packages):
        source = Path('/usr/share/doc') / package / 'copyright'
        if not source.is_file():
            raise RuntimeError(f'Missing redistribution notice for {path}: {source}')
        shutil.copyfile(source, destination / f'{package}.copyright')


def bundle_linux(browsers: Path, executable: Path) -> None:
    root = executable.parent / 'linux-runtime'
    libraries, fonts, licenses = (root / name for name in ('lib', 'fonts', 'licenses'))
    for directory in (libraries, fonts, licenses):
        directory.mkdir(parents=True)

    # NSS loads these modules dynamically, outside the ELF dependency table.
    # Fontconfig may also be loaded dynamically by Chromium.
    available = {}
    for line in _run('ldconfig', '-p').splitlines():
        match = re.match(r'\s*(\S+).*=>\s+(/\S+)', line)
        if match:
            available.setdefault(match[1], Path(match[2]))
    extra = ['libnss3.so', 'libsoftokn3.so', 'libfreebl3.so', 'libfreeblpriv3.so',
             'libnssckbi.so', 'libfontconfig.so.1', 'libfreetype.so.6']
    missing = set(extra) - available.keys()
    if missing:
        raise RuntimeError(f'Missing Linux runtime libraries: {sorted(missing)}')
    pending = [available[name] for name in extra]
    for path in browsers.rglob('*'):
        if path.is_file():
            with path.open('rb') as stream:
                if stream.read(4) == b'\x7fELF':
                    pending.append(path)
    copied: dict[str, Path] = {}
    visited: set[Path] = set()
    while pending:
        binary = pending.pop()
        if binary in visited:
            continue
        visited.add(binary)
        resolved = _linked(binary)
        if binary in available.values():
            resolved[binary.name] = binary
        for soname, source in resolved.items():
            if soname in copied:
                if copied[soname].resolve() != source.resolve():
                    raise RuntimeError(f'Conflicting Linux library: {soname}')
                continue
            copied[soname] = source
            shutil.copy2(source, libraries / soname)
            _license(source, licenses)
            pending.append(source)

    font_sources = sorted(Path('/usr/share/fonts/truetype/liberation').glob('*.ttf'))
    font_sources += sorted(Path('/usr/share/fonts/truetype/liberation2').glob('*.ttf'))
    font_sources += sorted(Path('/usr/share/fonts/truetype/dejavu').glob('DejaVuSans*.ttf'))
    if not font_sources:
        raise RuntimeError('Install fonts-liberation and fonts-dejavu-core before bundling')
    for source in font_sources:
        shutil.copy2(source, fonts / source.name)
        _license(source, licenses)
    (root / 'fonts.conf').write_text('''<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig>
  <dir prefix="relative">fonts</dir>
  <cachedir prefix="xdg">mermaid-render/fontconfig</cachedir>
  <alias><family>sans-serif</family><prefer><family>Liberation Sans</family></prefer></alias>
  <alias><family>serif</family><prefer><family>Liberation Serif</family></prefer></alias>
  <alias><family>monospace</family><prefer><family>Liberation Mono</family></prefer></alias>
</fontconfig>
''', encoding='utf-8')
    files = sorted(path for path in root.rglob('*') if path.is_file())
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    manifest = browsers / 'BROWSER_INFO.json'
    info = json.loads(manifest.read_text())
    info['linux_runtime'] = {
        'id': digest.hexdigest()[:16],
        'files': [path.relative_to(browsers).as_posix() for path in files],
    }
    manifest.write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')
    print(f'Bundled {len(copied)} Linux libraries and {len(font_sources)} fonts.', flush=True)
