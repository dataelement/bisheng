#!/usr/bin/env python
"""Generate the built-in PPT templates shipped with the task-mode ``bisheng-pptx`` skill.

Run from ``src/backend/``::

    python scripts/pptx_templates/build_templates.py            # all templates
    python scripts/pptx_templates/build_templates.py gov-red    # one template

Writes ``template.pptx`` + ``layouts.json`` per template and the shared
``catalog.json`` into ``bisheng/linsight/builtin_skills/bisheng-pptx/templates/``.
The outputs are committed; re-run only when a theme or layout changes (every run
produces a binary diff because the zip timestamps move).
"""

from __future__ import annotations

import datetime
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from builder import SLIDE_H, SLIDE_W, SlideBuilder, prepare_presentation  # noqa: E402
from layouts import COMMON_LAYOUTS  # noqa: E402
from pptx import Presentation  # noqa: E402
from themes import THEMES, Theme  # noqa: E402

_BACKEND_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
OUT_DIR = os.path.join(_BACKEND_ROOT, "bisheng", "linsight", "builtin_skills", "bisheng-pptx", "templates")
MAX_BYTES = 500 * 1024  # pre-commit check-added-large-files limit
FIXED_TIME = datetime.datetime(2026, 10, 27, 0, 0, 0)

try:  # specialty layouts are optional until they land
    from layouts_special import SPECIAL_LAYOUTS
except ImportError:  # pragma: no cover
    SPECIAL_LAYOUTS = {}


def layouts_for(theme: Theme) -> list:
    """Common layouts, with the theme's specialty layouts inserted before the closing page."""
    common = list(COMMON_LAYOUTS)
    special = list(SPECIAL_LAYOUTS.get(theme.id, []))
    return common[:-1] + special + common[-1:]


def build_one(theme: Theme) -> dict:
    prs = Presentation()
    prepare_presentation(prs, theme)
    described = []
    for index, (layout_id, family, name, use_for, draw) in enumerate(layouts_for(theme)):
        b = SlideBuilder(prs, theme, layout_id, family, name, use_for)
        draw(b)
        b.notes(f"示例版式 {layout_id}（{name}）：{use_for}。页面上的文字均为示例，使用时整体替换。")
        described.append(b.describe(index))

    props = prs.core_properties
    props.title = f"{theme.name} 模板"
    props.author = ""
    props.last_modified_by = ""
    props.created = FIXED_TIME
    props.modified = FIXED_TIME
    props.revision = 1

    target = os.path.join(OUT_DIR, theme.id)
    os.makedirs(target, exist_ok=True)
    pptx_path = os.path.join(target, "template.pptx")
    prs.save(pptx_path)
    size = os.path.getsize(pptx_path)
    if size > MAX_BYTES:
        raise SystemExit(f"{pptx_path} is {size} bytes, over the {MAX_BYTES} pre-commit limit")

    manifest = {
        "id": theme.id,
        "name": theme.name,
        "scenes": theme.scenes,
        "mood": theme.mood,
        "canvas": {"width_pt": SLIDE_W, "height_pt": SLIDE_H, "ratio": "16:9"},
        "palette": {
            "primary": theme.primary,
            "secondary": theme.secondary,
            "accent": theme.accent,
            "background": theme.bg,
            "surface": theme.surface,
            "text": theme.text,
            "muted": theme.muted,
        },
        "fonts": {"title": theme.title_font, "body": theme.body_font, "latin": theme.latin_font},
        "layouts": described,
    }
    with open(os.path.join(target, "layouts.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(f"[ok] {theme.id}: {len(described)} layouts, {size // 1024} KB")
    return {
        "id": theme.id,
        "name": theme.name,
        "scenes": theme.scenes,
        "mood": theme.mood,
        "palette": manifest["palette"],
        "fonts": manifest["fonts"],
        "layout_count": len(described),
        "layouts": [d["layout_id"] for d in described],
    }


def main(argv: list[str]) -> int:
    wanted = set(argv[1:])
    themes = [t for t in THEMES if not wanted or t.id in wanted]
    if wanted and len(themes) != len(wanted):
        print(f"[error] unknown template id in {sorted(wanted)}")
        return 1
    os.makedirs(OUT_DIR, exist_ok=True)
    entries = [build_one(t) for t in themes]
    if not wanted:
        with open(os.path.join(OUT_DIR, "catalog.json"), "w", encoding="utf-8") as fh:
            json.dump({"templates": entries}, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
