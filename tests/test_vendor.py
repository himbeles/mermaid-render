import io
import tarfile
from unittest.mock import patch

from mermaid_render.vendor import download_mermaid


def test_mermaid_download_extracts_dist_without_node(tmp_path):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as tf:
        for name, content in {
            "package/dist/mermaid.esm.min.mjs": b"export default {}",
            "package/dist/chunks/one.js": b"export const x=1",
            "package/src/do_not_extract.ts": b"hidden",
        }.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    with patch("mermaid_render.vendor.urlopen") as mocked:
        mocked.return_value.__enter__.return_value.read.return_value = raw.getvalue()
        dist = download_mermaid(tmp_path / "dist")
    assert (dist / "mermaid.esm.min.mjs").read_bytes() == b"export default {}"
    assert (dist / "chunks/one.js").is_file()
    assert not (dist / "src/do_not_extract.ts").exists()


def test_vendor_includes_license_and_provenance(tmp_path):
    import json
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as tf:
        for name, content in {
            "package/LICENSE": b"Copyright Mermaid; MIT",
            "package/dist/mermaid.esm.min.mjs": b"export default {}",
            "package/dist/chunks/mermaid.esm.min/a.mjs": b"export const a=1",
            "package/dist/chunks/mermaid.esm.min/a.mjs.map": b"irrelevant",
            "package/dist/tests/spec.js": b"not runtime",
        }.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    with patch("mermaid_render.vendor.urlopen") as mocked:
        mocked.return_value.__enter__.return_value.read.return_value = raw.getvalue()
        dist = download_mermaid(tmp_path / "bundle", version="12.1.0")
    assert (dist / "MERMAID_LICENSE.txt").read_bytes().startswith(b"Copyright")
    assert (dist / "chunks/mermaid.esm.min/a.mjs").exists()
    assert not (dist / "chunks/mermaid.esm.min/a.mjs.map").exists()
    assert not (dist / "tests/spec.js").exists()
    assert json.loads((dist / "VERSION.json").read_text())["version"] == "12.1.0"
