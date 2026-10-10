# mermaid-render

Render Mermaid diagrams to **SVG, PNG, PDF**, or **editable, connected Visio VSDX** on Linux, Windows, and macOS. Uses the official Mermaid.js renderer; no Node.js or Microsoft Visio installation is required. Python 3.10+ is supported.

## Install from PyPI

Install the command-line tool with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install mermaid-render
```

Mermaid.js and Chromium support files install automatically on the first render. To prepare them in advance, run `mermaid-render setup`.

### Command-line usage

```bash
mermaid-render diagram.mmd                  # Creates diagram.svg
mermaid-render diagram.mmd -o diagram.png   # PNG at scale 2 (192 dpi)
mermaid-render diagram.mmd -o diagram.pdf
mermaid-render diagram.mmd -o diagram.vsdx
```

The output extension selects the format; use `--format` to select it explicitly. SVG is the default. The default theme is `redux-color`; use `--theme` to change it.

- **PNG:** Defaults to twice the SVG's pixel dimensions. Use `--scale 1` for 96 dpi, or `--background transparent` for a transparent background.
- **PDF:** A single diagram-sized vector page. Scale applies only to PNG.
- **VSDX:** Flowcharts and sequence diagrams, with editable shapes and glued connectors. Flowchart subgraphs become native Visio containers with member relationships, including nested subgraphs and internal connectors. Flowcharts default to right-angle connectors; choose `--visio-connectors straight` or `--visio-connectors mermaid` for direct lines or detailed Mermaid curves. Mermaid attachment positions, standard shape connection points, and rendered border widths are retained.

Sequence diagrams preserve participants and actors, lifelines, nested activations, message labels and numbering, notes, interaction frames, and participant creation/destruction. Each participant's artwork forms one movable group, with messages attached at their chronological positions. Messages use straight lines and simple rectangular self-loops; `--visio-connectors` applies to flowcharts. Try `examples/sequence.mmd`:

```bash
mermaid-render examples/sequence.mmd -o sequence.vsdx
```

Other Mermaid diagram types currently support SVG, PNG, and PDF output.

### Python usage

Install into your project with `uv add mermaid-render`, or into an existing environment with `uv pip install mermaid-render`.

```python
from mermaid_render import convert

source = """flowchart LR
    A[Input] --> B{Valid?}
    B -->|Yes| C[Process]
    B -->|No| D[Reject]
"""

convert(source, "diagram.svg")
convert(source, "diagram.png", background="transparent")  # scale=2 by default
convert(source, "diagram.pdf")
convert(source, "diagram.vsdx", visio_connectors="right-angle")
svg_bytes = convert(source)  # Without an output path, returns SVG bytes
```

`convert` returns bytes for every format and writes them when an output path is supplied. Use `theme=`, `scale=`, and `background=` to customize rendering.

### Runtime support files

Support files persist in user application data, rather than a temporary cache:

| OS | Location |
|---|---|
| macOS | `~/Library/Application Support/mermaid-render` |
| Linux | `$XDG_DATA_HOME/mermaid-render`, or `~/.local/share/mermaid-render` |
| Windows | `%LOCALAPPDATA%\mermaid-render` |

The package checks version-matched user support files first, then bundled files. Setup copies bundled files into the support directory when needed, or downloads missing files. Existing valid files are reused. Paths are managed automatically.

For a normal PyPI installation on Linux, install Chromium's system libraries on a connected machine with:

```bash
uvx --from playwright==1.63.0 playwright install-deps chromium
```

## Install in an offline environment

Download a **bundled wheel** from [GitHub Releases](https://github.com/himbeles/mermaid-render/releases), matching the target operating system and architecture:

| Platform | Wheel filename suffix |
|---|---|
| Linux x86-64 | `linux_x86_64.whl` |
| Windows x86-64 | `win_amd64.whl` |
| macOS Apple Silicon | `macosx_*_arm64.whl` |
| macOS Intel | `macosx_*_x86_64.whl` |

Transfer the wheel to the target machine and install it using its full filename, for example:

```bash
uv tool install ./mermaid_render-0.10.0-py3-none-macosx_13_0_arm64.whl
mermaid-render diagram.mmd -o diagram.vsdx
```

Bundled wheels include Mermaid.js and Chromium, so rendering requires no runtime downloads. Linux bundles also include the browser's shared libraries, fonts, and license notices; no browser system-library installation is needed. Optional `mermaid-render setup` copies the complete bundle into the user support directory.

Linux x86-64 wheels target glibc 2.39 or newer (Ubuntu 24.04 or compatible) and are tested in a minimal Ubuntu container with networking disabled. The host provides glibc and the ELF loader; Alpine/musl is not supported. They are not manylinux wheels. macOS wheels encode the minimum OS version required by their binaries; CI tests on macOS 15.

GitHub Releases also contain the lightweight PyPI wheel and source archive. Choose a platform-specific wheel for the bundled runtime.

## Contribute

Clone the repository and use uv to install dependencies and run tests:

```bash
git clone https://github.com/himbeles/mermaid-render.git
cd mermaid-render
uv sync --locked
uv run pytest -q
uv run mermaid-render examples/example.mmd -o diagram.vsdx
```

Rendering and browser tests automatically prepare missing support files. On Linux, install browser system libraries first with `uv run python -m playwright install-deps chromium`.

The rendering API lives in `src/mermaid_render/api.py`; connected VSDX generation in `semantic.py` (flowcharts) and `sequence.py`; Mermaid semantics and artwork capture in the `*_capture.js` files and `capture.js`; runtime installation in `assets.py`. Add regression tests for rendering or connector changes. Visual checks in an independent VSDX viewer are useful alongside automated tests.

### Build and release

Build lightweight PyPI distributions:

```bash
uv build --out-dir dist/pypi
uv run python scripts/check_lightweight_dist.py dist/pypi
```

Build and test a bundled wheel on its target OS/architecture:

```bash
uv run python scripts/build_platform_wheel.py --outdir dist/bundled
uv run python scripts/test_wheel_install.py dist/bundled/*.whl
```

[GitHub Actions](.github/workflows/bundled-wheels.yml) builds and tests lightweight distributions plus four platform-specific wheels. To release, update `project.version` in `pyproject.toml`, run `uv lock`, commit, and push a matching `v<version>` tag. The workflow publishes lightweight distributions to PyPI through Trusted Publishing and attaches all distributions to GitHub Releases. Main-branch pushes, pull requests, and manual runs build without publishing.

## License

MIT; see [LICENSE](LICENSE). Adapted from [FBklyra/mermaid-to-visio](https://github.com/FBklyra/mermaid-to-visio). Bundled Mermaid, Chromium, and Playwright retain their upstream licenses and notices.
