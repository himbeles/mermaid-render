"""Validate the universal wheel, source archive, and bundled assets."""

import sys
import tarfile
from pathlib import Path
from zipfile import ZipFile


def check(directory):
    wheels = list(directory.glob("*.whl"))
    sources = list(directory.glob("*.tar.gz"))
    if (
        len(wheels) != 1
        or len(sources) != 1
        or len([p for p in directory.iterdir() if not p.name.startswith(".")]) != 2
        or not wheels[0].name.endswith("-py3-none-any.whl")
    ):
        raise SystemExit("Expected one universal wheel and one source archive")
    if sources[0].name != wheels[0].name.removesuffix("-py3-none-any.whl") + ".tar.gz":
        raise SystemExit("Wheel and source archive versions must match")
    for artifact in wheels + sources:
        if artifact.stat().st_size > 10 * 1024**2:
            raise SystemExit(f"Unexpectedly large distribution: {artifact}")
        if artifact.suffix == ".whl":
            with ZipFile(artifact) as archive:
                names = archive.namelist()
        else:
            with tarfile.open(artifact) as archive:
                names = archive.getnames()
        for suffix in [
            "mermaid_render/pele/pele.global.js",
            "mermaid_render/pele/LICENSE",
            "mermaid_render/pele/manifest.json",
            "mermaid_render/fonts/NotoSans-Regular.ttf",
            "mermaid_render/fonts/LICENSE",
        ]:
            if not any(n.endswith(suffix) for n in names):
                raise SystemExit(f"Missing packaged asset: {suffix}")
        print(
            f"{artifact.name}: {artifact.stat().st_size / 1024:.1f} KiB; Pele/fonts included"
        )


if __name__ == "__main__":
    check(Path(sys.argv[1]))
