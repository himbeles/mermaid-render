"""Run in a clean environment after installing the built wheel.

Only local files are allowed: any external HTTP request is rejected by the
converter's browser request routing when the bundled Mermaid runtime is present.
"""
import importlib.metadata
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from mermaid_render import convert
from mermaid_render.api import _bundled_chromium

root = Path(importlib.metadata.distribution('mermaid-render').locate_file('mermaid_render'))
manifest = json.loads((root / 'browsers' / 'BROWSER_INFO.json').read_text())
assert _bundled_chromium() is not None
assert manifest['playwright_version'] == importlib.metadata.version('playwright')
assert (root / 'runtime' / 'mermaid.esm.min.mjs').is_file()

src = 'flowchart LR\n A[Alpha] --> B[Beta]\n B --> C[Gamma]'
svg = convert(src, format='svg')
assert b'<svg' in svg
png = convert(src, format='png', scale=2)
assert png.startswith(b'\x89PNG\r\n\x1a\n')
pdf = convert(src, format='pdf')
assert pdf.startswith(b'%PDF-')
vsdx = convert(src, format='vsdx')
with ZipFile(BytesIO(vsdx)) as z:
    assert z.testzip() is None
    page = z.read('visio/pages/page1.xml')
    assert b'<Connects>' in page and b'<Connect ' in page
print('Offline wheel smoke test passed: SVG, PNG, PDF and connected VSDX.')
