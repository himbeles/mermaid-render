"""Render from a bundled wheel in minimal Ubuntu with networking disabled."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel', type=Path)
    opts = parser.parse_args()
    image = f'mermaid-offline-test:{uuid.uuid4().hex}'
    with tempfile.TemporaryDirectory(prefix='mermaid-linux-test-') as temporary:
        context = Path(temporary)
        shutil.copy2(opts.wheel, context / opts.wheel.name)
        shutil.copy2(Path(__file__).with_name('smoke_offline.py'), context / 'smoke_offline.py')
        (context / 'Dockerfile').write_text('''FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/test
COPY *.whl /wheels/
RUN /opt/test/bin/pip install --no-cache-dir /wheels/*.whl
COPY smoke_offline.py /smoke_offline.py
ENV MERMAID_RENDER_TEST_PRIVATE_LINUX=1
CMD ["/opt/test/bin/python", "/smoke_offline.py"]
''', encoding='utf-8')
        try:
            subprocess.run(['docker', 'build', '-t', image, str(context)], check=True)
            subprocess.run(['docker', 'run', '--rm', '--network', 'none', image], check=True)
        finally:
            subprocess.run(['docker', 'image', 'rm', image], check=False)


if __name__ == '__main__':
    main()
