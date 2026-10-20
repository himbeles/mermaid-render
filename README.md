# mermaid-render

Render Mermaid diagrams to **SVG, PNG, or editable, connected Visio VSDX** on Linux, Windows, and macOS. Uses Pele in embedded QuickJS and native resvg for PNG. Supports Python 3.10+.

## Install

Install as globally available tool on your path
```sh
uv tool install mermaid-render
```

Optionally, install with integrated MCP server:

```sh
uv tool install 'mermaid-render[mcp]'
``` 

## Command line

Some example usage:

```sh
mermaid-render diagram.mmd    # --> diagram.svg
mermaid-render diagram.mmd -o diagram.png
mermaid-render diagram.mmd --format png
mermaid-render diagram.mmd -o diagram.vsdx
mermaid-render examples/sequence.mmd --format visio
```

The extension chooses the format; `--format svg|png|vsdx|visio` selects it explicitly. PNG defaults to scale 2 (192 dpi); use `--scale 1` for 96 dpi or `--background transparent` for transparency. SVG keeps fixed natural dimensions and the source direction. PNG output is limited to 100 megapixels; use SVG for larger drawings.

`--theme` selects a fixed color palette: `redux-color` (default), `default`, `dark`, `neutral`, or `forest`. Text layout uses bundled Noto Sans metrics, and PNG rendering loads the same fonts. Glyphs outside the bundled font may use installed system fallback fonts; install appropriate fonts when exporting CJK or other scripts outside Noto Sans's coverage. 

## Python

```python
from mermaid_render import convert

source = """flowchart LR
  A[Input] --> B{Valid?}
  B -->|Yes| C(Process)
  B -->|No| D[Reject]
"""

convert(source, "diagram.svg")
convert(source, "diagram.png", background="transparent", scale=2)
convert(source, "diagram.vsdx", visio_connectors="right-angle")
svg_bytes = convert(source)
```

`convert()` always returns bytes and optionally writes them to the output path. Output is written only after rendering succeeds. Convenience functions are `mermaid_to_svg`, `mermaid_to_png`, and `mermaid_to_vsdx`. Supported keywords are `format`, `title`, `theme`, `background`, `scale`, and `visio_connectors`. Background and scale control PNG output.

## Editable Visio

Connected VSDX export supports **flowcharts, sequence diagrams, state diagrams, and class diagrams**. Shapes and text remain editable; connectors retain native glue records.

- **Flowcharts:** standard and expanded shapes, multiline labels, styles, nested native containers, and directed/labeled connectors. Complex glyphs are captured as geometry sections of one editable node.
- **State diagrams:** initial/final states, choices, fork/join bars, descriptions, notes, transitions, nested composites, and concurrent regions. Concurrent region containers are derived from their positioned members because Pele renders region separators without wrapper IDs.
- **Class diagrams:** compartments, stereotypes, attributes, methods, static/abstract rows, namespaces, notes, UML relationship ends, and editable multiplicities.
- **Sequence diagrams:** grouped participant artwork, actors, lifelines, activations, create/destroy artwork, notes, interaction frames, message numbering, and chronology-preserving glued messages.

Flowchart/state/class connectors default to orthogonal routing. Choose `--visio-connectors straight` or `--visio-connectors mermaid` to use direct lines or the Mermaid curves. Sequence messages use straight lines and rectangular self-loops at their timeline positions. Moving or editing a diagram in Microsoft Visio should still be checked for your workflow; validation covers XML/glue records and visual checks in an independent viewer. Automated Microsoft Visio editing is not covered.

Fill transparency is flattened for native connected Visio nodes over their container or page background. Rich Visio text retains row styles; mixed styles within one row are combined at row granularity.

Other Mermaid diagram types support SVG and PNG. Images, external icon artwork and interactive links are disabled. Unsupported semantic mappings fail explicitly rather than returning disconnected Visio artwork. The adapter is tied to the vendored Pele version; changing that version requires checking its SVG and model identities.

`svg_to_vsdx(svg)` is available for geometry-only SVG import. It captures paths (including curves and arcs), basic shapes, affine transforms, local CSS, and positioned SVG text/tspans without a browser. It does not infer graph connections. External resources, scripts, `foreignObject`, filters, and `<use>` references are rejected. This is a static SVG subset, not a full web layout engine.

## MCP server

```sh
uv tool install 'mermaid-render[mcp]'
```

Configure a stdio MCP server:

```json
{
  "mcpServers": {
    "mermaid-render": {"command": "mermaid-render-mcp"}
  }
}
```

The `render_mermaid` tool accepts either `source` or `input_path` (`.mmd`/`.mermaid`), plus `output_path`. SVG, PNG, VSDX, and the `visio` alias use the same options as the Python API. Prefer absolute paths. Missing output directories are created and existing files are replaced only after successful rendering.

```json
{"source":"flowchart LR; A-->B","output_path":"/absolute/path/diagram.png"}
```

## Development and release

```sh
uv sync --locked
uv run pytest -q
uv run mermaid-render examples/class.mmd -o /tmp/class.vsdx
uv build --out-dir dist/pypi
uv run python scripts/check_distributions.py dist/pypi
uv run python scripts/test_wheel_install.py dist/pypi/*.whl
```

`test_wheel_install.py WHEEL` installs the wheel and its dependencies in an isolated environment. Its smoke test renders SVG/PNG and all four connected VSDX types with network/subprocess calls blocked and an empty `PATH`. CI runs the suite and installed-wheel smoke test on Linux, Windows, and macOS with Python 3.10 and 3.14.

Implementation: `renderer.py`/`renderer.js` run pinned Pele; `svg.py` reads static SVG geometry and text; `capture.py` maps semantic graphs; `semantic.py`, `sequence.py`, and `vsdx.py` write Visio.

To release, update the project version, run `uv lock`, commit, and push the matching `v<version>` tag. The workflow validates the tag, tests the wheel on Linux, Windows, and macOS, publishes the universal wheel and source archive to PyPI through Trusted Publishing, and attaches both files to the GitHub Release. No release is published by a branch push.

## License

MIT; see [LICENSE](LICENSE). Adapted originally from [Freddy Beltran's mermaid-to-visio](https://github.com/FBklyra/mermaid-to-visio). Pele retains its bundled MIT/ISC notices in `src/mermaid_render/pele/LICENSE`; Noto Sans uses the SIL Open Font License in `src/mermaid_render/fonts/LICENSE`. QuickJS-NG, resvg, svgelements, and the other Python dependencies retain their upstream licenses.
