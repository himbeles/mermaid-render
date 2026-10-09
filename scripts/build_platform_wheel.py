"""Build a platform wheel with Mermaid.js + Chromium Headless Shell inside.

Run with `uv run python scripts/build_platform_wheel.py` on
EACH corresponding native platform. No Node.js, npm, or system Visio required.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

PROJECT = Path(__file__).resolve().parents[1]
PACKAGE = PROJECT / "src" / "mermaid_render"
MERMAID = PACKAGE / "runtime"
BROWSERS = PACKAGE / "browsers"

# Matches the documented Playwright Chromium Headless Shell layouts.
SHELL_NAMES = {"chrome-headless-shell", "chrome-headless-shell.exe", "headless_shell"}


def find_shell(browsers: Path) -> Path:
    candidates = sorted(
        p for p in browsers.glob("chromium_headless_shell-*/*/*")
        if p.is_file() and p.name in SHELL_NAMES
    )
    if len(candidates) != 1:
        raise RuntimeError(f"Expected exactly one Chromium Headless Shell in {browsers}, got: {candidates}")
    return candidates[0]


def build(version: str, outdir: Path) -> Path:
    from mermaid_render.vendor import download_mermaid
    from wheel_platform import platform_tag as detect_platform_tag

    print(f"Downloading Mermaid {version}...", flush=True)
    download_mermaid(MERMAID, version=version)
    print("Installing Chromium Headless Shell with Playwright...", flush=True)
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSERS)
    env["PLAYWRIGHT_SKIP_BROWSER_GC"] = "1"
    subprocess.run([sys.executable, "-m", "playwright", "install", "--only-shell", "chromium"],
                   cwd=PROJECT, env=env, check=True)
    executable = find_shell(BROWSERS)
    # A wheel installed through an installer should preserve the executable mode,
    # but explicitly ensure it is executable before packaging on POSIX.
    if os.name != "nt":
        executable.chmod(executable.stat().st_mode | 0o111)
    platform_tag = detect_platform_tag(BROWSERS)
    relative = executable.relative_to(BROWSERS).as_posix()
    (BROWSERS / "BROWSER_INFO.json").write_text(json.dumps({
        "executable": relative,
        "playwright_version": importlib.metadata.version("playwright"),
        "platform_tag": platform_tag,
        "mermaid_version": version,
    }, indent=2) + "\n", encoding="utf-8")

    outdir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(outdir)], cwd=PROJECT, check=True)
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
    parser.add_argument("--mermaid-version", default="12.1.0")
    parser.add_argument("--outdir", type=Path, default=PROJECT / "dist")
    opts = parser.parse_args()
    build(opts.mermaid_version, opts.outdir.resolve())


if __name__ == "__main__":
    main()
