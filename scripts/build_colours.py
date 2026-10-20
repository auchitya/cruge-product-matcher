"""Build app/data/colours.json from the XKCD colour survey (CC0): python scripts/build_colours.py rgb.txt

~950 colour names people actually use ("aubergine", "dusty rose", "sea green"), each mapped to one
of the families the matcher compares, from its RGB value -- so a colour name nobody typed into the
code still lands in the right family.
"""
from __future__ import annotations

import colorsys
import json
import pathlib
import re
import sys

OUT = pathlib.Path(__file__).resolve().parent.parent / "app" / "data" / "colours.json"


def family(hex_: str) -> str:
    r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    deg = h * 360
    if l < 0.12:
        return "black"
    if s < 0.15:  # unsaturated
        return "white" if l > 0.85 else "black" if l < 0.2 else "grey"
    if l > 0.9:
        return "white"  # the palest tint of anything reads as white ("off white")
    if 15 <= deg < 70 and l > 0.78:  # pale warm: cream / ivory vs sand / oatmeal
        return "white" if deg >= 35 and l > 0.85 else "beige"
    if 15 <= deg < 50:  # warm: beige / brown / orange
        if s < 0.5 and l > 0.55:
            return "beige"
        return "brown" if l < 0.45 or s < 0.5 else "orange"
    if 50 <= deg < 70:
        return "green" if l < 0.35 else "yellow"  # dark yellow reads as olive
    if 70 <= deg < 165:
        return "green"
    if 165 <= deg < 255:
        return "blue"
    if 255 <= deg < 290:
        return "purple"
    if 290 <= deg < 330:
        return "pink" if l > 0.5 else "purple"
    # red hues: dark = maroon/burgundy (red), soft or light = pink
    if l < 0.4:
        return "red"
    return "pink" if (s < 0.5 and l > 0.5) or l > 0.7 else "red"


def main(src: str) -> None:
    out = {}
    for line in pathlib.Path(src).read_text().splitlines():
        if line.startswith("#") or "\t" not in line:
            continue
        name, hex_ = line.split("\t")[:2]
        name = re.sub(r"[^a-z ]", "", name.lower()).strip()
        if name and re.fullmatch(r"#[0-9a-fA-F]{6}", hex_.strip()):
            out[name] = family(hex_.strip())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dict(sorted(out.items())), indent=0))
    print(f"{len(out)} colour names -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
