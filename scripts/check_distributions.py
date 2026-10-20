"""Validate the universal wheel and its bundled Pele and font assets."""

import sys
from pathlib import Path
from zipfile import ZipFile


def check(directory):
    wheels = list(directory.glob("*.whl"))
    if (
        len(wheels) != 1
        or len([p for p in directory.iterdir() if not p.name.startswith(".")]) != 1
        or not wheels[0].name.endswith("-py3-none-any.whl")
    ):
        raise SystemExit("Expected exactly one universal wheel")
    for artifact in wheels:
        if artifact.stat().st_size > 10 * 1024**2:
            raise SystemExit(f"Unexpectedly large distribution: {artifact}")
        with ZipFile(artifact) as archive:
            names = archive.namelist()
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
