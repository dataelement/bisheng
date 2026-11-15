#!/usr/bin/env python3
"""List the slide themes, or one theme's layouts and slots with their capacities.

    import subprocess, sys
    r = subprocess.run([sys.executable, "skills/html-report/scripts/list_layouts.py"], capture_output=True, text=True)
    print(r.stdout); print(r.stderr[-2000:] if r.stderr else "")
    # one theme:  [..., "list_layouts.py", "operating"]

Capacity is counted in 字: a CJK or full-width character is 1, anything else 0.5.
``·分条`` marks a bullet slot (pass a list); ``≤N 条`` is its item limit.

Always exits 0 and reports on stdout — the code executor discards stdout on a non-zero exit.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from slides import LAYOUTS, THEMES


def _themes() -> None:
    print("可用主题（Deck.open 的第一个参数）：")
    for t in THEMES.values():
        print(f"- {t['id']}（{t['name']}）：{t['scenes']}。{t['mood']}")
    print("\n查看某个主题的版式与插槽：list_layouts.py <主题 id>")


def _layouts(theme_id: str) -> None:
    t = THEMES[theme_id]
    print(f"主题 {t['id']}（{t['name']}）。所有主题的版式与插槽相同，只有配色和字体不同。\n")
    for lid, layout in LAYOUTS.items():
        print(f"## {lid}（{layout['name']}）：{layout['use_for']}")
        parts = []
        for slot in layout["slots"]:
            if slot["name"] == "footer":
                continue
            role = slot["role"]
            if role == "chart":
                parts.append(f"{slot['name']}[图表 deck.chart]")
            elif role == "table":
                parts.append(f"{slot['name']}[表格 deck.table]")
            elif role == "image":
                parts.append(f"{slot['name']}[图片 deck.image，可 drop]")
            else:
                extra = f"·分条≤{slot['max_items']}条" if slot["bullets"] else ""
                parts.append(f"{slot['name']}≤{slot['capacity']:g}{extra}")
        print("   " + "，".join(parts))
    print("\n分组（如 card3、kpi4、node5）用不到时整组 deck.drop(s, '分组名')；页脚由 Deck.open(footer=...) 统一填写。")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        _themes()
    elif args[0] in THEMES:
        _layouts(args[0])
    else:
        print(f"未知主题 {args[0]!r}；可用主题：{', '.join(THEMES)}")
    # Always 0: a non-zero exit makes the code executor drop stdout.
    sys.exit(0)


if __name__ == "__main__":
    main()
