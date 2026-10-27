#!/usr/bin/env python
"""List the built-in templates, or one template's layouts and slots, as plain text.

    python skills/bisheng-pptx/scripts/list_templates.py              # all templates
    python skills/bisheng-pptx/scripts/list_templates.py gov-red      # layouts + slots

Text only on purpose: choosing a template must not depend on looking at images.
Always exits 0; problems are printed as ``[FATAL] ...``.
"""

from __future__ import annotations

import json
import os
import sys

TEMPLATES_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))

_ROLE_NAMES = {
    "title": "标题",
    "subtitle": "副标题/小标题",
    "body": "正文",
    "caption": "注释",
    "label": "标签",
    "number": "数字",
    "footer": "页脚",
    "chart_area": "图表 deck.chart",
    "table": "表格 deck.table",
    "image_area": "图片 deck.image",
}


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def list_all() -> None:
    catalog = _load(os.path.join(TEMPLATES_DIR, "catalog.json"))
    print('内置模板（用 Deck.open("<id>") 打开；看版式与插槽：list_templates.py <id>）\n')
    for t in catalog["templates"]:
        print(f"■ {t['id']}  {t['name']}  （{t['layout_count']} 个版式）")
        print(f"  适用：{t['scenes']}")
        print(f"  气质：{t['mood']}")
        p = t["palette"]
        print(f"  配色：主色 #{p['primary']} / 辅色 #{p['secondary']} / 强调 #{p['accent']} / 底色 #{p['background']}")
        print(f"  字体：标题 {t['fonts']['title']}，正文 {t['fonts']['body']}，西文 {t['fonts']['latin']}")
        print()
    print("用户点名了风格或行业就照办；没点名时按「适用」一行挑最贴近的一套。")


def list_one(template_id: str) -> None:
    path = os.path.join(TEMPLATES_DIR, template_id, "layouts.json")
    if not os.path.exists(path):
        print(f"[FATAL] 没有模板 {template_id!r}。先不带参数运行本脚本查看可用模板。")
        return
    spec = _load(path)
    print(f"模板 {spec['id']}（{spec['name']}）：{spec['scenes']}")
    print(
        "插槽名≤N 是建议字数上限（汉字算 1，字母数字算 0.5），「·分条」表示传 list 逐条写；超了就精简或拆页，不要缩字号。"
    )
    print('带「.」的插槽属于同一分组，deck.drop(slide, "分组名") 可整组删除（例如不用第三张卡片就 drop "card3"）。\n')
    for layout in spec["layouts"]:
        print(f"● {layout['layout_id']} — {layout['name']}：{layout['use_for']}")
        parts = []
        for slot in layout["slots"]:
            if slot["role"] == "footer":
                continue  # filled by Deck.open(footer=...)
            if "capacity" in slot:
                mark = "·分条" if slot.get("bullets") else ""
                parts.append(f"{slot['name']}≤{slot['capacity']}{mark}")
            else:
                parts.append(f"{slot['name']}[{_ROLE_NAMES.get(slot['role'], slot['role'])}]")
        print("    " + "  ".join(parts))
        groups = [g for g in layout["groups"] if g not in {s["name"] for s in layout["slots"]}]
        if groups:
            print(f"    可整组删除：{', '.join(groups)}")


def main() -> int:
    try:
        if len(sys.argv) > 1:
            list_one(sys.argv[1])
        else:
            list_all()
    except Exception as exc:  # report in stdout: a non-zero exit would hide the message
        print(f"[FATAL] {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
