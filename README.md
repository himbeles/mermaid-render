# mermaid-render

Render **Mermaid → SVG, PNG and PDF**, and **Mermaid flowcharts → connected Visio VSDX** on Linux, Windows, and macOS. Python uses the official Mermaid.js renderer inside Chromium Headless Shell, controlled through Playwright. Node.js, a browser installation, and Microsoft Visio are **not required on the target machine** when installing a platform-specific **bundled wheel**.

The converter is adapted from the MIT-licensed [FBklyra/mermaid-to-visio](https://github.com/FBklyra/mermaid-to-visio). Mermaid itself is MIT licensed; Chromium and Playwright have their own third-party notices and licenses. Keep those notices with redistributed binaries.

## Prebuilt offline wheels via GitHub Actions

The workflow [`.github/workflows/bundled-wheels.yml`](.github/workflows/bundled-wheels.yml) builds two distributions using uv:

- **PyPI:** a small universal Python wheel and source archive, without Mermaid.js or browser binaries. The first render automatically installs the pinned runtime support files.
- **GitHub Releases:** the exact PyPI artifacts plus four bundled wheels for Linux x86-64, Windows x86-64, macOS Apple Silicon, and macOS Intel. Bundled wheels contain Mermaid **12.1.0** and the Chromium Headless Shell matching Playwright **1.63.0**, so rendering needs no runtime downloads.

A matching version tag (for example `v0.8.0`) attaches all six artifacts to a GitHub Release and publishes only the lightweight artifacts to PyPI through Trusted Publishing. Pull requests, pushes to `main`, and manual runs build and test without publishing.

### Runtime support files

Each asset is resolved independently: first from valid, version-matched persistent per-user application data, then from its bundled location inside the installed package (`mermaid_render/runtime` and `mermaid_render/browsers`). Support directories are:

| OS | Support directory |
|---|---|
| macOS | `~/Library/Application Support/mermaid-render` |
| Linux | `$XDG_DATA_HOME/mermaid-render`, default `~/.local/share/mermaid-render` |
| Windows | `%LOCALAPPDATA%\mermaid-render` |

These are support files, not temporary or cache files. Mermaid uses a versioned `mermaid/<version>` subdirectory; Chromium uses `browsers/playwright-<version>-<os>-<architecture>`. Upgrades keep versions separate. Downloads are staged and validated before installation, and concurrent processes share an installation lock. Rendering reuses existing files without downloading them again.

Missing assets install automatically on render. Optionally run `mermaid-render setup` beforehand. Setup always populates the user support directory: it copies valid bundled assets if available, otherwise downloads them. Existing valid support files are reused without being overwritten. Runtime paths are managed internally; the CLI and rendering API have no Mermaid or browser path overrides. If automatic setup fails, the error links directly to the [GitHub Releases](https://github.com/himbeles/mermaid-render/releases) bundled wheels and explains how to install one for offline use.

### Building from GitHub

1. Push this repository to GitHub (including `.github/workflows/bundled-wheels.yml`).
2. Select **Actions → mermaid-render distributions → Run workflow**.
3. Download your platform's wheel from the run artifacts, or get all four wheels from the GitHub Release created when you push a `v*` tag.

### Install and use (after downloading your platform wheel)

```bash
uv tool install ./mermaid_render-*-py3-none-macosx_*_arm64.whl
mermaid-render diagram.mmd -o diagram.svg
mermaid-render diagram.mmd -o diagram.png --scale 2
mermaid-render diagram.mmd -o diagram.pdf
mermaid-render diagram.mmd -o diagram.vsdx
```

The example installs the macOS Apple Silicon wheel. Choose the wheel matching your operating system and architecture.

For the lightweight PyPI installation:

```bash
uv tool install mermaid-render
mermaid-render diagram.mmd -o diagram.vsdx
```

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
to choose explicitly (`svg`, `png`, `pdf`, `visio`/`vsdx`). Without an output filename or explicit format, SVG is the default; the CLI writes beside the input file with a `.svg` extension. The API returns
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
uv run pytest -q
uv run mermaid-render examples/example.mmd --format png -o diagram.png
```

`uv sync` creates a `.venv` from the committed lockfile. Rendering and browser tests automatically prepare missing runtime support files. The project uses Hatchling with a PEP 621 `pyproject.toml` and `src/` layout.

Default builds are always lightweight, even if the checkout contains old bundled files:

```bash
uv build --out-dir dist/pypi
uv run python scripts/check_lightweight_dist.py dist/pypi
```

### Local platform-specific wheel build

On a machine with internet access, with the same OS/architecture as your intended wheel:

```bash
uv sync
uv run python scripts/build_platform_wheel.py --outdir dist/bundled
uv run python scripts/test_wheel_install.py dist/bundled/*.whl
```

The platform tag is detected automatically. For Linux, install system browser libraries first (`uv run python -m playwright install-deps chromium`). The script downloads the pinned Mermaid distribution, installs the matching headless shell into temporary staging, writes a relative executable manifest, and builds a platform-specific wheel directly with `uv build` and a Hatchling hook. Staging is removed afterward and the source tree is never populated with runtime assets. The wheel retains native executable permissions and includes upstream license assets distributed in the payload.

**Linux compatibility:** Linux wheels are available through GitHub Releases only. They use the `linux_x86_64` tag and bundle Chromium without vendoring its system libraries. Install compatible browser dependencies on the target system (`python -m playwright install-deps chromium`). The wheel is tested on Ubuntu 24.04 and is not audited for manylinux compatibility.

**macOS caveat:** The wheel tag derives its minimum version from the bundled Mach-O binaries using `otool`; there is no project-defined macOS minimum. CI tests on macOS 15, so older versions are not independently tested. If Gatekeeper imposes restrictions on downloaded unsigned binaries, local signing or organizational policy may be needed.

### Configure PyPI publishing

Commit and push the release changes. Set `project.version` to the intended release version, then push the matching tag, for example:

   ```bash
   git tag v0.8.0
   git push origin v0.8.0
   ```

The workflow also runs builds on pull requests and main-branch pushes, but those runs do not publish to PyPI. If a publish run stops after a partial upload, rerun the failed job: uv checks PyPI and skips identical files already uploaded. Published versions cannot be overwritten; use a new version for changed artifacts.

After the first successful publication, on any supported operating system:

```bash
uv tool install mermaid-render
mermaid-render examples/example.mmd -o diagram.vsdx
```

## Development/project structure

- `src/mermaid_render/api.py` — Python API and SVG/PNG/PDF rendering
- `src/mermaid_render/assets.py` — bundled lookup and persistent runtime support installation
- `src/mermaid_render/graph_capture.js` — Mermaid graph semantics and SVG geometry extraction
- `src/mermaid_render/semantic.py` — connected Visio shapes/edges with Glue formula references
- `src/mermaid_render/vsdx.py` — geometry-only VSDX exporter for arbitrary SVG
- `scripts/build_platform_wheel.py` — real platform wheel build with bundled Mermaid/Chromium
- `hatch_build.py` and `scripts/wheel_platform.py` — native wheel metadata and binary-derived platform tags
- `scripts/test_wheel_install.py` and `scripts/smoke_offline.py` — clean-venv install, offline SVG/Visio smoke test
- `.github/workflows/bundled-wheels.yml` — four-platform build/test/release workflow

## License

MIT for the Python port and its source adaptation; see `LICENSE`. Mermaid and Chromium remain third-party projects with their own notices and copyright holders.
