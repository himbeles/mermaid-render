"""Write platform wheel metadata directly when a browser is bundled."""
from __future__ import annotations

import sys
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        browsers = Path(self.root) / 'src' / 'mermaid_render' / 'browsers'
        if not (browsers / 'BROWSER_INFO.json').is_file():
            # Source-only development installs remain pure Python.
            if any(path.is_file() and path.name != 'README.txt' for path in browsers.rglob('*')):
                raise RuntimeError('Browser payload exists without BROWSER_INFO.json; run the bundling script')
            return
        sys.path.insert(0, str(Path(self.root) / 'scripts'))
        try:
            from wheel_platform import platform_tag
            tag = platform_tag(browsers)
        finally:
            sys.path.pop(0)
        build_data['pure_python'] = False
        build_data['tag'] = f'py3-none-{tag}'
        build_data['force_include'][str(browsers)] = 'mermaid_render/browsers'
        runtime = Path(self.root) / 'src' / 'mermaid_render' / 'runtime'
        build_data['force_include'][str(runtime)] = 'mermaid_render/runtime'
