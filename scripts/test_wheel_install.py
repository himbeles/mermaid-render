"""Install the built wheel in a separate venv and run the offline smoke test."""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('wheel', type=Path)
    opts = parser.parse_args()
    wheel = opts.wheel.resolve()
    script = Path(__file__).with_name('smoke_offline.py').resolve()
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d) / 'test-env'
        subprocess.run(['uv', 'venv', '--python', sys.executable, str(dest)], check=True)
        exe = dest / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        subprocess.run(['uv', 'pip', 'install', '--python', str(exe), str(wheel)], check=True)
        env = os.environ.copy()
        env.pop('MERMAID_DIST', None)
        env.pop('CHROMIUM_PATH', None)
        env.pop('PLAYWRIGHT_BROWSERS_PATH', None)
        # Working outside the source checkout verifies that wheel files alone suffice.
        subprocess.run([str(exe), str(script)], cwd=d, env=env, check=True)


if __name__ == '__main__':
    main()
