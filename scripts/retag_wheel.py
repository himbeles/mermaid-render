"""Retag a uv_build wheel containing a platform-specific native executable.

uv_build normally writes py3-none-any because the Python sources are pure.
When Chromium is bundled, the wheel MUST have a concrete platform tag. This
script rewrites WHEEL metadata and RECORD hashes in addition to the filename.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import re
from pathlib import Path
from zipfile import ZipFile


def retag(source: Path, platform_tag: str, *, remove: bool = False) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_]+", platform_tag):
        raise ValueError(f"Invalid platform tag: {platform_tag!r}")
    parts = source.stem.split("-")
    if len(parts) != 5 or parts[2:] != ["py3", "none", "any"]:
        raise ValueError(f"Expected a py3-none-any wheel, got {source.name}")
    output = source.with_name("-".join(parts[:4] + [platform_tag]) + ".whl")
    with ZipFile(source) as original:
        info = original.infolist()
        wheel_paths = [z.filename for z in info if z.filename.endswith(".dist-info/WHEEL")]
        records = [z.filename for z in info if z.filename.endswith(".dist-info/RECORD")]
        if len(wheel_paths) != 1 or len(records) != 1:
            raise ValueError("Invalid wheel metadata")
        wheel_path, record_path = wheel_paths[0], records[0]
        content = {}
        for item in info:
            payload = original.read(item.filename)
            if item.filename == wheel_path:
                metadata = payload.decode("utf-8")
                metadata, count = re.subn(r"(?m)^Tag: py3-none-any$", "Tag: py3-none-" + platform_tag, metadata)
                if count != 1:
                    raise ValueError("Expected one py3-none-any wheel tag")
                metadata = re.sub(r"(?m)^Root-Is-Purelib: true$", "Root-Is-Purelib: false", metadata)
                payload = metadata.encode("utf-8")
            content[item.filename] = payload
        rows = []
        for filename, data in content.items():
            if filename == record_path:
                continue
            checksum = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            rows.append((filename, f"sha256={checksum}", str(len(data))))
        rows.append((record_path, "", ""))
        sio = io.StringIO(newline="")
        csv.writer(sio, lineterminator="\n").writerows(rows)
        content[record_path] = sio.getvalue().encode("utf-8")
        with ZipFile(output, "w", allowZip64=True) as dest:
            for item in info:
                # Preserve executable bits of Linux and macOS Chromium binaries.
                dest.writestr(item, content[item.filename])
    if remove:
        source.unlink()
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--platform-tag", required=True)
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    print(retag(args.wheel, args.platform_tag, remove=args.remove))


if __name__ == "__main__":
    main()
