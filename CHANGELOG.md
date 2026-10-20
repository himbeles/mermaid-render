# Changelog

## 0.14.0

- Build the universal wheel with the native uv build backend.

- Replace Mermaid.js, Playwright and headless Chromium with pinned Pele 1.6.0 in embedded QuickJS-NG 0.17.0.1. Render PNG with native resvg-py 0.5.0. Rendering requires no Node installation, browser, subprocess or network access.
- Bundle licensed Pele and Noto Sans assets in a universal Python wheel. Native dependencies install as Python wheels. GitHub Releases and PyPI receive the same single universal wheel. Remove browser installers, asset downloads, platform-browser packaging and the `mermaid-render setup` command.
- Remove PDF output and the `mermaid_to_pdf` API. Unsupported formats use the standard format validation error.
- Replace browser DOM measurement with Python SVG geometry, transforms, CSS and text capture. Preserve editable connected VSDX for flowchart, state, class and sequence diagrams, plus geometry-only SVG import.
- Use Pele layouts, fixed theme palettes and bundled font metrics. Layouts, colors, text wrapping and connector routes can differ from 0.13. Connected Visio fill transparency is flattened; mixed inline text styles are combined per row.
- Select QuickJS over MiniRacer for the embedded runtime after the Pele prototype comparison. Remove the experimental runtime selector, benchmark scripts and migration notes after integrating the production renderer.
- Add isolated installed-wheel rendering checks with network/subprocess calls blocked and executable lookup unavailable. Add Linux, Windows and macOS CI coverage for Python 3.10 and 3.14.

Application-data caches from previous releases are no longer used. This release does not delete caches outside the package checkout.
