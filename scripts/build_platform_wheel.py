"""Build a platform wheel with Mermaid.js + Chromium Headless Shell inside.

Run with `uv run python scripts/build_platform_wheel.py` on
EACH corresponding native platform. No Node.js, npm, or system Visio required.
"""
from __future__ import annotations

import argparse
import subprocess
import os
import tempfile
from pathlib import Path
from zipfile import ZipFile

PROJECT = Path(__file__).resolve().parents[1]
from mermaid_render.assets import find_shell, install_browser
from mermaid_render.vendor import DEFAULT_VERSION


def build(version: str, outdir: Path) -> Path:
    from mermaid_render.vendor import download_mermaid
    from wheel_platform import platform_tag as detect_platform_tag

    outdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mermaid-bundle-") as temporary:
        staging = Path(temporary)
        runtime = staging / "runtime"
        browsers = staging / "browsers"
        print(f"Downloading Mermaid {version}...", flush=True)
        download_mermaid(runtime, version=version)
        print("Installing Chromium Headless Shell with Playwright...", flush=True)
        install_browser(browsers)
        executable = find_shell(browsers)
        platform_tag = detect_platform_tag(browsers)
        relative = executable.relative_to(browsers).as_posix()
        env = os.environ.copy()
        env["MERMAID_RENDER_BUNDLE_DIR"] = str(staging)
        subprocess.run(["uv", "build", "--wheel", "--out-dir", str(outdir)],
                       cwd=PROJECT, env=env, check=True)
    wheels = list(outdir.glob(f"mermaid_render-*-py3-none-{platform_tag}.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"Expected exactly one newly built wheel, got: {wheels}")
    result = wheels[0]
    with ZipFile(result) as z:
        names = set(z.namelist())
        required = {
            "mermaid_render/runtime/mermaid.esm.min.mjs",
            "mermaid_render/runtime/VERSION.json",
            "mermaid_render/runtime/MERMAID_LICENSE.txt",
            "mermaid_render/browsers/BROWSER_INFO.json",
            "mermaid_render/browsers/" + relative,
        }
        missing = required - names
        if missing:
            raise RuntimeError(f"Wheel missing required runtime files: {sorted(missing)}")
        if z.testzip() is not None:
            raise RuntimeError("Corrupted output wheel")
    print(f"Built offline wheel: {result} ({result.stat().st_size / 1024**2:.1f} MiB)")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", type=Path, default=PROJECT / "dist")
    opts = parser.parse_args()
    build(DEFAULT_VERSION, opts.outdir.resolve())


if __name__ == "__main__":
    main()
