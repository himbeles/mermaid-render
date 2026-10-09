"""Write platform wheel metadata directly when a browser is bundled."""
from __future__ import annotations

import sys
import os
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        # Default builds remain lightweight even in a populated checkout.
        staging = os.environ.get('MERMAID_RENDER_BUNDLE_DIR')
        if not staging:
            return
        staging = Path(staging).resolve()
        browsers = staging / 'browsers'
        runtime = staging / 'runtime'
        if not (browsers / 'BROWSER_INFO.json').is_file() or not (runtime / 'VERSION.json').is_file():
            raise RuntimeError('Bundled build requires complete staged browser and Mermaid assets')
        sys.path.insert(0, str(Path(self.root) / 'scripts'))
        try:
            from wheel_platform import platform_tag
            tag = platform_tag(browsers)
        finally:
            sys.path.pop(0)
        build_data['pure_python'] = False
        build_data['tag'] = f'py3-none-{tag}'
        build_data['force_include'][str(browsers)] = 'mermaid_render/browsers'
        build_data['force_include'][str(runtime)] = 'mermaid_render/runtime'
