#!/usr/bin/env python
"""Check, export or convert a PPTD project with the PPTD engine, and print a short report.

    python skills/bisheng-pptx/scripts/pptd.py env
    python skills/bisheng-pptx/scripts/pptd.py check   scratch/deck
    python skills/bisheng-pptx/scripts/pptd.py render  scratch/deck output/名称.pptx
    python skills/bisheng-pptx/scripts/pptd.py convert 上传的.pptx scratch/deck

Everything goes to stdout and the script always exits 0: the code executor returns
only stderr for a non-zero exit, which would throw this report away. The verdict is
the「结论:」line.

On top of the engine's own check this adds a font-size floor (readability on a
projector) and, after render, rewrites CJK typefaces to Microsoft YaHei so the
deck opens with the intended font on Windows.
"""

import io
import json
import os
import re
import subprocess
import sys
import zipfile

RUNTIME = os.environ.get("PPTD_RUNTIME", "/opt/pptd-runtime")
NODE = os.path.join(RUNTIME, "bin", "node")
CLI = os.path.join(RUNTIME, "engine", "lib", "bin.js")
BODY_MIN = 11  # 正文（超过 LONG_TEXT 字）与表格正文下限
NOTE_MIN = 9  # 短标签、注释、来源、页脚、表头下限
LONG_TEXT = 24  # 超过这么多字的文本按正文对待
WIN_EA = "Microsoft YaHei"
MAC_LINUX_EA = (
    "PingFang SC",
    "Noto Sans CJK SC",
    "Noto Sans SC",
    "HarmonyOS Sans SC",
    "Source Han Sans SC",
    "Source Han Sans CN",
    "Hiragino Sans GB",
)
PASS = "结论: 通过，可以 render"
FAIL = "结论: 需要修改"


def run(args):
    try:
        p = subprocess.run([NODE, CLI, *args], capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return 1, "引擎执行超过 300 秒，已中止。请减少页数分批处理。"
    return p.returncode, (p.stdout or "") + ("\n" + p.stderr if p.stderr else "")


def engine_ready():
    return os.path.exists(NODE) and os.path.exists(CLI)


def not_ready():
    print("PPT 引擎: 不可用。当前环境未安装 PPT 引擎，请联系管理员安装后重试。")
    print(FAIL)


def parse_json(text):
    try:
        return json.loads(text[text.index("{") :])
    except ValueError:
        return None


# --- font-size floor -------------------------------------------------------


def _plain_len(text):
    return len(re.sub(r"\s", "", re.sub(r"<[^>]+>", "", str(text or ""))))


def _resolve(value, table):
    """``$name`` -> table[name]; dicts pass through; anything else -> {}."""
    if isinstance(value, str) and value.startswith("$"):
        value = table.get(value[1:])
    return value if isinstance(value, dict) else {}


def _size(*candidates):
    for c in candidates:
        if isinstance(c, (int, float)) and not isinstance(c, bool):
            return c
    return None


def font_issues(project):
    """Below-floor text in the project, or None when the check cannot run here."""
    try:
        import yaml
    except ImportError:
        return None
    deck = os.path.join(project, "deck.pptd") if os.path.isdir(project) else project
    root = os.path.dirname(deck)
    try:
        with open(deck, encoding="utf-8") as f:
            manifest = yaml.safe_load(f) or {}
    except Exception as e:  # the engine check reports the details
        return [f"deck.pptd 读取失败：{e}"]
    theme = manifest.get("theme") or {}
    text_styles = theme.get("textStyles") or {}
    table_styles = theme.get("tableStyles") or {}
    out = []
    for no, rel in enumerate(manifest.get("pages") or [], 1):
        try:
            with open(os.path.join(root, rel), encoding="utf-8") as f:
                page = yaml.safe_load(f) or {}
        except Exception as e:
            out.append(f"第{no}页 {rel}: 读取失败 {e}")
            continue
        for el in page.get("elements") or []:
            if not isinstance(el, dict):
                continue
            eid = el.get("elementId")
            kind = el.get("elementType")
            if kind == "text" and isinstance(el.get("content"), dict):
                c = el["content"]
                size = _size(c.get("fontSize"), _resolve(c.get("style"), text_styles).get("fontSize"))
                n = _plain_len(c.get("text"))
                if size is None or n == 0:
                    continue
                floor = BODY_MIN if n > LONG_TEXT else NOTE_MIN
                if size < floor:
                    label = "正文" if floor == BODY_MIN else "短标签/注释"
                    out.append(f"第{no}页 {rel} 「{eid}」 {label} {size}pt < {floor}pt（{n} 字）")
            elif kind == "table":
                style = _resolve(el.get("style"), table_styles)
                cell = {**(style.get("cellStyle") or {}), **(el.get("cellStyle") or {})}
                first = {**(style.get("firstRowStyle") or {}), **(el.get("firstRowStyle") or {})}
                worst = {}
                for r, row in enumerate(el.get("rows") or []):
                    for item in row or []:
                        if not isinstance(item, dict) or _plain_len(item.get("text")) == 0:
                            continue
                        header = r == 0
                        size = _size(
                            item.get("fontSize"), first.get("fontSize") if header else None, cell.get("fontSize")
                        )
                        floor = NOTE_MIN if header else BODY_MIN
                        if size is not None and size < floor:
                            key = "表头" if header else "表格正文"
                            worst[key] = (min(size, worst.get(key, (size, floor))[0]), floor)
                for key, (size, floor) in worst.items():
                    out.append(f"第{no}页 {rel} 「{eid}」 {key} {size}pt < {floor}pt")
    return out


# --- font rewrite ----------------------------------------------------------


def fix_fonts(pptx):
    buf = io.BytesIO()
    changed = 0
    with zipfile.ZipFile(pptx) as zin, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.endswith(".xml"):
                text = data.decode("utf-8")
                for face in MAC_LINUX_EA:
                    k = text.count(f'typeface="{face}"')
                    if k:
                        changed += k
                        text = text.replace(f'typeface="{face}"', f'typeface="{WIN_EA}"')
                data = text.encode("utf-8")
            zout.writestr(item, data)
    with open(pptx, "wb") as f:
        f.write(buf.getvalue())
    return changed


# --- commands --------------------------------------------------------------


def cmd_env():
    ok = engine_ready()
    print("PPT 引擎:", "可用" if ok else "不可用。当前环境未安装 PPT 引擎，请联系管理员安装后重试。")
    print("模板目录可见:", os.path.isdir("skills/bisheng-pptx/templates"))


def cmd_check(project):
    if not engine_ready():
        return not_ready()
    rc, text = run(["check", project])
    print(text.strip()[-6000:])
    extra = font_issues(project)
    if extra is None:
        print("\n（本环境缺少 PyYAML，未做字号下限检查；请自行按 SKILL.md 的字号要求核对。）")
        extra = []
    if extra:
        print(f"\n字号低于下限（按 error 处理，共 {len(extra)} 处；放大字号，放不下就删字或拆页）:")
        print("\n".join(extra[:60]))
    print()
    print(FAIL if rc != 0 or extra else PASS)


def cmd_render(project, out):
    if not engine_ready():
        return not_ready()
    extra = font_issues(project) or []
    if extra:
        print(f"未导出：{len(extra)} 处字号低于下限，先改再 check：")
        print("\n".join(extra[:60]))
        return
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    rc, text = run(["render", project, "-o", out, "--force", "--json"])
    res = parse_json(text)
    if res is None or rc != 0 or res.get("status") == "needs_revision":
        print("未导出，检查未通过：")
        detail = res.get("issues", res) if isinstance(res, dict) else text.strip()
        print(json.dumps(detail, ensure_ascii=False)[:6000] if not isinstance(detail, str) else detail[-6000:])
        return
    n = fix_fonts(out)
    print(
        f"已导出 {out}：{res.get('pageCount')} 页，{res.get('nativeObjectCount')} 个原生元素，"
        f"{res.get('sizeBytes')} 字节，警告 {res.get('warnings')}；中文字体统一为 {WIN_EA}（改写 {n} 处）"
    )


def cmd_convert(pptx, project):
    if not engine_ready():
        return not_ready()
    rc, text = run(["convert", pptx, "-o", project, "--force", "--json"])
    res = parse_json(text)
    if res is None or rc != 0 or res.get("status") not in ("pass", "warning"):
        print("转换失败：")
        print(text.strip()[-3000:])
        return
    print(
        f"已转换为 PPTD 工程 {project}：{res.get('slideCount')} 页，{res.get('outputElementCount')} 个元素，"
        f"提取图片 {res.get('extractedAssetCount')} 个"
    )
    simplified, unsupported = {}, []
    for d in res.get("diagnostics") or []:
        if d.get("level") == "normalized":
            key = d.get("message") or d.get("feature")
            simplified.setdefault(key, set()).add(d.get("slide"))
        elif d.get("level") == "unsupported":
            unsupported.append(f"第{d.get('slide')}页 {d.get('feature')}: {d.get('message')}")
    if simplified:
        print("被简化的效果（交付时如实告诉用户）：")
        for msg, slides in simplified.items():
            print(f"- {msg}（第 {', '.join(str(s) for s in sorted(x for x in slides if x))} 页）")
    if unsupported:
        print("不支持、未转换的内容（交付时如实告诉用户）：")
        print("\n".join(unsupported[:40]))
    print("页面是平铺元素，导出的文件不带原母版。下一步：在工程上修改后 check。")


def main():
    args = sys.argv[1:]
    if args[:1] == ["env"]:
        cmd_env()
    elif args[:1] == ["check"] and len(args) >= 2:
        cmd_check(args[1])
    elif args[:1] == ["render"] and len(args) >= 3:
        cmd_render(args[1], args[2])
    elif args[:1] == ["convert"] and len(args) >= 3:
        cmd_convert(args[1], args[2])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
    sys.exit(0)  # verdict is in stdout; see module docstring
