"""Reject runtime payloads or platform wheels in distributions destined for PyPI."""
import sys
import tarfile
from pathlib import Path
from zipfile import ZipFile


def check(directory: Path) -> None:
    wheels = list(directory.glob('*.whl'))
    sources = list(directory.glob('*.tar.gz'))
    if len(wheels) != 1 or len(sources) != 1 or not wheels[0].name.endswith('-py3-none-any.whl'):
        raise SystemExit('Expected one universal wheel and one source archive')
    for artifact in wheels + sources:
        if artifact.stat().st_size > 10 * 1024**2:
            raise SystemExit(f'Unexpectedly large lightweight distribution: {artifact}')
        if artifact.suffix == '.whl':
            with ZipFile(artifact) as archive:
                names = archive.namelist()
        else:
            with tarfile.open(artifact) as archive:
                names = archive.getnames()
        if any('/mermaid_render/runtime/' in '/' + name or '/mermaid_render/browsers/' in '/' + name for name in names):
            raise SystemExit(f'Runtime assets leaked into {artifact}')
        print(f'{artifact.name}: {artifact.stat().st_size / 1024:.1f} KiB, no runtime payload')


if __name__ == '__main__':
    check(Path(sys.argv[1]))
