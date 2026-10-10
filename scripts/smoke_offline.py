"""Run in a clean environment after installing the built wheel.

Only local files are allowed: any external HTTP request is rejected by the
converter's browser request routing when the bundled Mermaid runtime is present.
"""
import importlib.metadata
import os
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from mermaid_render import convert
import sys
import mermaid_render.assets as assets

root = Path(importlib.metadata.distribution('mermaid-render').locate_file('mermaid_render'))
lightweight = '--lightweight' in sys.argv
support = tempfile.TemporaryDirectory()
assets.data_root = lambda: Path(support.name) / "support"
if lightweight:
    assert not (root / 'browsers' / 'BROWSER_INFO.json').exists()
    assert not (root / 'runtime' / 'mermaid.esm.min.mjs').exists()
else:
    assert assets.bundled_browser() is not None
    assert (root / 'runtime' / 'mermaid.esm.min.mjs').is_file()
    if os.environ.get('MERMAID_RENDER_TEST_PRIVATE_LINUX'):
        executable = assets.bundled_browser()
        bare = os.environ.copy()
        bare.pop('LD_LIBRARY_PATH', None)
        unconfigured = subprocess.run(['ldd', str(executable)], env=bare, capture_output=True, text=True)
        assert '=> not found' in unconfigured.stdout, 'Test image already has browser system libraries'
        configured = subprocess.run(['ldd', str(executable)], env=assets.browser_environment(executable),
                                    capture_output=True, text=True, check=True)
        assert '=> not found' not in configured.stdout, configured.stdout
        assert 'linux-runtime/lib/' in configured.stdout


def no_download(*args, **kwargs):
    raise AssertionError('Rendering tried to download already available runtime assets')


if not lightweight:
    assets.download_mermaid = assets.install_browser = no_download

src = 'flowchart LR\n A[Alpha] --> B[Beta]\n B --> C[Gamma]'
svg = convert(src, format='svg')
assert b'<svg' in svg
# The first lightweight render installs missing assets. All later renders must
# work without any setup downloads, just like a bundled installation.
assets.download_mermaid = assets.install_browser = no_download
png = convert(src, format='png', scale=2)
assert png.startswith(b'\x89PNG\r\n\x1a\n')
pdf = convert(src, format='pdf')
assert pdf.startswith(b'%PDF-')
vsdx = convert(src, format='vsdx')
with ZipFile(BytesIO(vsdx)) as z:
    assert z.testzip() is None
    page = z.read('visio/pages/page1.xml')
    assert b'<Connects>' in page and b'<Connect ' in page
sequence = convert('sequenceDiagram\n participant A as Alice\n participant B as Bob\n A->>+B: Request\n B-->>-A: Reply', format='vsdx')
with ZipFile(BytesIO(sequence)) as z:
    assert z.testzip() is None
    page = z.read('visio/pages/page1.xml')
    assert b'Participant.A' in page and b'Type="Group"' in page
    assert page.count(b'<Connect ') == 4
print('Offline wheel smoke test passed: SVG, PNG, PDF, flowchart and sequence VSDX.')

if not lightweight:
    # setup must copy the complete browser, libraries, fonts and notices; render
    # again from persistent support data, outside the installed wheel's paths.
    _, persisted = assets.setup_runtime()
    assert persisted.is_relative_to(Path(support.name).resolve())
    assert assets.ensure_browser() == persisted
    assert convert(src, format='png').startswith(b'\x89PNG\r\n\x1a\n')

support.cleanup()
