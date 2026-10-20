"""Bundled font metrics shared by Pele layout and SVG capture."""

from functools import lru_cache
from pathlib import Path
import unicodedata

ROOT = Path(__file__).with_name("fonts")
FONT_FAMILY = "Noto Sans"


@lru_cache(maxsize=1)
def metrics():
    from fontTools.ttLib import TTFont

    result = []
    for suffix in ["Regular", "Bold", "Italic", "BoldItalic"]:
        with TTFont(ROOT / f"NotoSans-{suffix}.ttf") as font:
            units = font["head"].unitsPerEm
            cmap = font.getBestCmap()
            widths = font["hmtx"].metrics
            result.append(
                {chr(code): widths[name][0] / units for code, name in cmap.items()}
            )
    return result


def text_width(text, size=16, bold=False, italic=False):
    table = metrics()[int(bold) + 2 * int(italic)]
    return size * sum(
        table.get(
            c,
            0
            if unicodedata.combining(c)
            else 1
            if unicodedata.east_asian_width(c) in {"W", "F"}
            else 0.6,
        )
        for c in text
    )
