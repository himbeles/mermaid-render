"""Install the universal wheel in isolation and run the rendering smoke test."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    opts = parser.parse_args()
    wheel = opts.wheel.resolve()
    script = Path(__file__).with_name("smoke_render.py").resolve()
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d) / "environment"
        subprocess.run(
            ["uv", "venv", "--python", sys.executable, str(dest)], check=True
        )
        exe = dest / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        args = ["uv", "pip", "install", "--python", str(exe), str(wheel)]
        subprocess.run(args, check=True)
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        subprocess.run([str(exe), str(script)], cwd=d, env=env, check=True)


if __name__ == "__main__":
    main()
