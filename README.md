# mermaid-render

Render **Mermaid → SVG, PNG and PDF**, and **Mermaid flowcharts → connected Visio VSDX** on Linux, Windows, and macOS. Python uses the official Mermaid.js renderer inside Chromium Headless Shell, controlled through Playwright. Node.js, a browser installation, and Microsoft Visio are **not required on the target machine** when installing a platform-specific **bundled wheel**.

The converter is adapted from the MIT-licensed [FBklyra/mermaid-to-visio](https://github.com/FBklyra/mermaid-to-visio). Mermaid itself is MIT licensed; Chromium and Playwright have their own third-party notices and licenses. Keep those notices with redistributed binaries.

## Prebuilt offline wheels via GitHub Actions

The workflow [`.github/workflows/bundled-wheels.yml`](.github/workflows/bundled-wheels.yml) runs on `workflow_dispatch`, pull requests, pushes to `main`, and version tags such as `v0.6.0`. It creates **four distinct wheels**:

| CI runner | Wheel suffix | Environment |
|---|---|---|
| `ubuntu-24.04` | `py3-none-manylinux_2_39_x86_64.whl` | Linux x86-64, glibc 2.39+ |
| `windows-2022` | `py3-none-win_amd64.whl` | Windows x86-64 |
| `macos-15` | `py3-none-macosx_<derived>_arm64.whl` | macOS Apple Silicon |
| `macos-15-intel` | `py3-none-macosx_<derived>_x86_64.whl` | macOS Intel |

Each wheel includes the official Mermaid **12.1.0** ES-module distribution, the corresponding Playwright **1.63.0** Chromium Headless Shell, a browser-executable manifest, and all Python conversion code. The browser is resolved relative to the installed wheel: no system browser, Node.js, runtime fetching or custom environment variables are necessary. A wheel is **not** a standalone executable; Python and its Playwright dependencies must be installed. The build runner resolves Python dependencies and downloads the browser during CI; target execution needs no network access when the Python dependencies are already installed.

GitHub Actions uploads each wheel as an artifact. Pushing a tag `v0.6.0` also creates/updates a GitHub Release with all wheels attached and publishes the tested offline wheels to PyPI using `uv publish` and Trusted Publishing. The tag must match the version in `pyproject.toml`. **CI has to be run on GitHub to build the real browser-containing wheels**; the repository source archive does not include browser binaries.

### Building from GitHub

1. Push this repository to GitHub (including `.github/workflows/bundled-wheels.yml`).
2. Select **Actions → mermaid-render offline wheels → Run workflow**.
3. Download your platform's wheel from the run artifacts, or get all four wheels from the GitHub Release created when you push a `v*` tag.

### Install and use (after downloading your platform wheel)

```bash
uv tool install ./mermaid_render-*-py3-none-macosx_*_arm64.whl
mermaid-render diagram.mmd -o diagram.svg
mermaid-render diagram.mmd -o diagram.png --scale 2
mermaid-render diagram.mmd -o diagram.pdf
mermaid-render diagram.mmd -o diagram.vsdx
```

The example installs the macOS Apple Silicon wheel. Replace its filename with the appropriate wheel for your operating system. If Python dependencies are not cached or installed, `uv tool install` itself needs network access. For a completely air-gapped installation, download **all dependency wheels** beforehand (for example, export requirements with `uv export` and download with `pip download`) and install them using `uv pip install --no-index --find-links=...` into a virtual environment; a wheel containing Chromium does not bundle Python dependencies. The installed CLI can then be invoked from that environment.

```python
from mermaid_render import convert

source = """flowchart LR
  A[Input] --> B{Valid?}
  B -->|Yes| C[Process]
  B -->|No| D[Reject]
"""

convert(source, "diagram.svg")
convert(source, "diagram.png", scale=2, background="transparent")
convert(source, "diagram.pdf")
convert(source, "diagram.vsdx")
```

Visio VSDX generation creates editable flowchart shapes and *native connection relationships*, not generic disconnected SVG paths. Only flowcharts currently support connected VSDX export; other Mermaid diagram types can be exported as SVG, PNG or PDF. Connection behavior after editing/moving nodes in desktop Visio is not yet independently verified.

## Output formats

`mermaid-render` infers the format from the output extension; use `-f/--format`
to choose explicitly (`svg`, `png`, `pdf`, `visio`/`vsdx`). The API returns
bytes and optionally writes the output file:

```bash
mermaid-render diagram.mmd -o diagram.svg
mermaid-render diagram.mmd -o diagram.png --scale 2 --background transparent
mermaid-render diagram.mmd -o diagram.pdf --background white
mermaid-render diagram.mmd -o diagram.vsdx
```

- **SVG:** Original Mermaid-generated SVG markup, without rasterization.
- **PNG:** Chromium screenshot at the Mermaid SVG viewBox size. `--scale 2`
  doubles pixel dimensions (96 to 192 pixels per CSS inch). `--background`
  accepts a CSS color or `transparent`.
- **PDF:** Chromium print-to-PDF with a tight single diagram-sized page, zero
  margins, and vector SVG content where supported. The `--scale` option applies
  only to PNG. PDF transparency is not guaranteed by Chromium; use SVG or PNG
  when an alpha channel is needed.
- **VSDX:** Native Visio shapes and connection relationships for Mermaid flowcharts.
  Other Mermaid types deliberately fail rather than writing disconnected shapes.

All four formats use the *same official Mermaid.js runtime in headless Chromium*.
No Node.js process or installed system browser is used by the offline wheels.

## Development using uv

```bash
uv sync
uv run python -m playwright install --only-shell chromium
uv run mermaid-render-fetch ./mermaid-dist --version 12.1.0
uv run pytest -q
uv run mermaid-render examples/example.mmd --format png --mermaid-dist ./mermaid-dist -o diagram.png
```

`uv sync` creates a `.venv`. The source archive does not include a `uv.lock` because resolution needs access to PyPI; generate and commit one with `uv lock` on a network-connected machine for a fully pinned development workflow. The project uses Hatchling with a modern PEP 621 `pyproject.toml` and `src/` layout.

### Local platform-specific wheel build

On a machine with internet access, with the same OS/architecture as your intended wheel:

```bash
uv sync
uv run python scripts/build_platform_wheel.py
uv run python scripts/test_wheel_install.py dist/*.whl
```

The platform tag is detected automatically. For Linux, install `patchelf` and system browser libraries first (`uv run python -m playwright install-deps chromium`). The script downloads the pinned Mermaid distribution, installs only the matching headless shell into the package tree, writes a relative executable manifest, builds a platform-specific wheel directly with `uv build` and a Hatchling hook. The wheel retains native executable permissions and includes upstream license assets distributed in the payload.

**Linux compatibility:** After building, the script runs `auditwheel repair` for `manylinux_2_39_x86_64`, vendors non-policy shared libraries, and audits the resulting wheel. CI installs and tests that repaired wheel. Linux targets need glibc 2.39+ and the system libraries allowed by the manylinux policy. Runtime-loaded libraries and fonts can still require system packages; auditwheel cannot discover dependencies loaded only through `dlopen`.

**macOS caveat:** The wheel tag derives its minimum version from the bundled Mach-O binaries using `otool`; there is no project-defined macOS minimum. CI tests on macOS 15, so older versions are not independently tested. If Gatekeeper imposes restrictions on downloaded unsigned binaries, local signing or organizational policy may be needed.

**Wheel size:** Chromium bundles can exceed PyPI's default 100 MiB per-file limit. The publish job checks all four files before uploading any of them. If needed, request a [PyPI file-size limit increase](https://docs.pypi.org/project-management/storage-limits/), then set the repository Actions variable `PYPI_MAX_FILE_SIZE_MIB` to the approved value. This variable only controls the preflight check; it does not change PyPI's limit.

### Configure PyPI publishing

Commit and push the release changes. Set `project.version` to the intended release version, then push the matching tag, for example:

   ```bash
   git tag v0.6.0
   git push origin v0.6.0
   ```

The workflow also runs builds on pull requests and main-branch pushes, but those runs do not publish to PyPI. If a publish run stops after a partial upload, rerun the failed job: uv checks PyPI and skips identical files already uploaded. Published versions cannot be overwritten; use a new version for changed artifacts.

After the first successful publication:

```bash
uv tool install mermaid-render
mermaid-render examples/example.mmd -o diagram.vsdx
```

## Development/project structure

- `src/mermaid_render/api.py` — Python API, browser lookup, offline Mermaid loading, SVG/PNG/PDF rendering
- `src/mermaid_render/graph_capture.js` — Mermaid graph semantics and SVG geometry extraction
- `src/mermaid_render/semantic.py` — connected Visio shapes/edges with Glue formula references
- `src/mermaid_render/vsdx.py` — geometry-only VSDX exporter for arbitrary SVG
- `scripts/build_platform_wheel.py` — real platform wheel build with bundled Mermaid/Chromium
- `hatch_build.py` and `scripts/wheel_platform.py` — native wheel metadata and binary-derived platform tags
- `scripts/test_wheel_install.py` and `scripts/smoke_offline.py` — clean-venv install, offline SVG/Visio smoke test
- `.github/workflows/bundled-wheels.yml` — four-platform build/test/release workflow

## License

MIT for the Python port and its source adaptation; see `LICENSE`. Mermaid and Chromium remain third-party projects with their own notices and copyright holders.
