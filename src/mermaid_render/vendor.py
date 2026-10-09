"""Fetch the *official* Mermaid JS dist from the npm registry without Node.js.

Vendor an official, pinned Mermaid distribution inside the Python package
before building an offline wheel. The runtime is subject to Mermaid's MIT
license and its upstream third-party license notices.
"""

from __future__ import annotations

import argparse
import json
import io
import tarfile
from pathlib import Path, PurePosixPath
from urllib.request import urlopen

DEFAULT_VERSION = "12.1.0"


def download_mermaid(destination: str | Path, *, version: str = DEFAULT_VERSION) -> Path:
    """Download official Mermaid npm release and extract browser runtime assets.

    Copies ESM/JS assets from the upstream dist directory, plus relevant
    runtime assets and the official MIT license. Avoids sourcemaps, generated
    typings, documentation and upstream test fixtures to keep wheels small.
    """
    if not version or any(c not in "0123456789." for c in version):
        raise ValueError("version must be an npm numeric version, such as 11.12.0")
    destination = Path(destination).resolve()
    url = f"https://registry.npmjs.org/mermaid/-/mermaid-{version}.tgz"
    with urlopen(url, timeout=120) as response:
        tar_data = response.read()
    count = 0
    with tarfile.open(fileobj=io.BytesIO(tar_data), mode="r:gz") as archive:
        for member in archive:
            if not member.isfile():
                continue
            if member.name == "package/LICENSE":
                rel = PurePosixPath("MERMAID_LICENSE.txt")
            elif member.name in {"package/THIRD-PARTY-NOTICES.md", "package/THIRD_PARTY_NOTICES.md"}:
                rel = PurePosixPath(member.name.rsplit("/", 1)[-1])
            elif member.name.startswith("package/dist/"):
                rel = PurePosixPath(member.name).relative_to("package/dist")
                is_license_notice = rel.name.endswith(".LICENSE.txt")
                if (any(part in {"__mocks__", "tests", "docs"} for part in rel.parts)
                        or (not is_license_notice and rel.suffix not in {
                            ".js", ".mjs", ".css", ".json", ".woff", ".woff2", ".ttf"
                        })):
                    continue
            else:
                continue
            if not rel.parts or any(component in {"..", "."} for component in rel.parts):
                raise ValueError(f"unsafe member name: {member.name}")
            target = (destination / Path(*rel.parts)).resolve()
            target.relative_to(destination)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as src, target.open("wb") as dst:
                while data := src.read(1024 * 1024):
                    dst.write(data)
            count += 1
    if count == 0 or not (destination / "mermaid.esm.min.mjs").is_file():
        raise RuntimeError("Mermaid npm archive lacks the expected dist/mermaid.esm.min.mjs")
    (destination / "VERSION.json").write_text(json.dumps({
        "package": "mermaid", "version": version, "source": url,
        "source_project": "https://github.com/mermaid-js/mermaid",
        "license": "MIT", "bundled_assets": count,
    }, indent=2) + "\n", encoding="utf-8")
    return destination


def main():
    parser = argparse.ArgumentParser(description="Download official Mermaid JS for offline Python rendering")
    parser.add_argument("directory", nargs="?", default="mermaid-dist")
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--bundle", action="store_true", help="Vendor directly into this source checkout before building an offline wheel")
    args = parser.parse_args()
    if args.bundle:
        destination = Path(__file__).resolve().parent / "runtime"
    else:
        destination = Path(args.directory)
    print(f"Mermaid downloaded to {download_mermaid(destination, version=args.version)}")


if __name__ == "__main__":
    main()
