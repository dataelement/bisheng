#!/usr/bin/env python3
"""Self-check a slide deck built with slides.py, from its manifest.

    import subprocess, sys
    r = subprocess.run([sys.executable, "skills/html-report/scripts/check_slides.py", "output/名称.html"],
                       capture_output=True, text=True)
    print(r.stdout); print(r.stderr[-2000:] if r.stderr else "")

Reads ``scratch/<名称>.manifest.json`` written by ``Deck.save``. These checks are about
content, not rendering: whether a page really fits is measured afterwards by
``check_html``. Every finding here is WARN (a capacity is an estimate; the browser
measurement is the authority). Only a missing file or manifest is an ERROR.

Always exits 0 and reports on stdout — the code executor discards stdout on a non-zero exit.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from slides import LAYOUTS

# The verdict strings the model watches for. Only this script prints them.
PASS_VERDICT = "幻灯片自检：通过"
FAIL_VERDICT = "幻灯片自检：有 ERROR，修复后重新运行"

_PLACEHOLDER = re.compile(r"示例|占位|待补充|待填写|lorem|ipsum|\bTODO\b|X{3,}|x{3,}", re.IGNORECASE)
_TITLE_ROLES = {"title"}


def check(html_path: str, manifest_dir: str = "scratch") -> tuple[list[tuple[str, str]], int]:
    findings: list[tuple[str, str]] = []
    stem = os.path.splitext(os.path.basename(html_path))[0]
    manifest_path = os.path.join(manifest_dir, f"{stem}.manifest.json")
    if not os.path.exists(html_path):
        return [("ERROR", f"{html_path} 不存在：先运行构建脚本 deck.save(...)")], 0
    if not os.path.exists(manifest_path):
        return [("ERROR", f"{manifest_path} 不存在：本自检只适用于用 slides.py 生成的文稿")], 0
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    with open(html_path, encoding="utf-8") as fh:
        doc = fh.read()
    pages = manifest.get("pages") or []
    if doc.count('<section class="slide ') != len(pages):
        findings.append(("ERROR", "网页里的页数和清单对不上：网页被手工改过，请改构建脚本后重新生成"))

    run_layout, run_len = None, 0
    for no, page in enumerate(pages, start=1):
        lid = page["layout_id"]
        layout = LAYOUTS.get(lid, {"slots": []})
        for entry in page.get("over_capacity", []):
            unit = entry.get("unit", "行" if entry["slot"] == "table" else "字")
            findings.append(
                (
                    "WARN",
                    f"第{no}页 {entry['slot']}：{entry['used']:g} {unit}，超过容量 {entry['capacity']:g} {unit} → 精简或拆页",
                )
            )
        dropped = set(page.get("dropped", []))
        filled = set(page.get("filled", {})) | set(page.get("objects", {}))
        for slot in layout["slots"]:
            name = slot["name"]
            if slot["role"] in _TITLE_ROLES and name not in filled and name not in dropped:
                findings.append(("WARN", f"第{no}页 {name}：标题没有填写 → 填一句结论"))
            if slot["role"] == "chart" and name not in page.get("objects", {}) and name not in dropped:
                findings.append(
                    ("WARN", f"第{no}页 {name}：图表区没有放图表 → deck.chart(...)，或换一个不带图表的版式")
                )
        for slot, text in (page.get("texts") or {}).items():
            if slot != "footer" and _PLACEHOLDER.search(text or ""):
                findings.append(("WARN", f"第{no}页 {slot}：像是占位文字（{text[:20]}…）→ 换成真实内容"))
        for slot in page.get("raw_html", []):
            findings.append(("WARN", f"第{no}页 {slot}：用了 html 片段，确认版式确实表达不了这部分内容"))
        if lid == run_layout:
            run_len += 1
        else:
            run_layout, run_len = lid, 1
        if run_len == 3:
            findings.append(("WARN", f"第{no - 2}–{no}页连续三页都是 {lid} → 换一种版式"))
    return findings, len(pages)


def main() -> None:
    if len(sys.argv) < 2:
        print("用法：check_slides.py output/名称.html [manifest 目录，默认 scratch]")
        sys.exit(0)
    findings, n = check(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "scratch")
    errors = [f for f in findings if f[0] == "ERROR"]
    warns = [f for f in findings if f[0] == "WARN"]
    print(f"幻灯片自检：{sys.argv[1]}（{n} 页）")
    for level, msg in errors + warns:
        print(f"- {level} {msg}")
    print(FAIL_VERDICT if errors else PASS_VERDICT + (f"（{len(warns)} 条 WARN 请逐条复核）" if warns else ""))
    print("接着调用 check_html 逐页测量是否装得下。")
    # Always 0: a non-zero exit makes the code executor drop stdout.
    sys.exit(0)


if __name__ == "__main__":
    main()
