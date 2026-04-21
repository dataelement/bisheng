"""Compare backend errcode Code values with platform bs.json errors.* keys.

Uses AST extraction (see extract_errcodes_ast.py). After adding backend codes,
run:  python tools/extract_errcodes_ast.py --dump-en
then:  python tools/apply_missing_errcode_i18n.py  (after extending ERR_ZH / ERR_JA)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRDIR = ROOT / "src/backend/bisheng/common/errcode"
LOCALES = ROOT / "src/frontend/platform/public/locales"

sys.path.insert(0, str(ROOT / "tools"))
from extract_errcodes_ast import all_errcodes, duplicate_code_definitions  # noqa: E402


def parse_errcodes() -> dict[int, dict]:
    raw = all_errcodes()
    return {
        code: {"class": cls, "file": fn, "msg": msg[:240]}
        for code, (msg, cls, fn) in raw.items()
    }


def locale_error_numeric_keys(bs_path: Path) -> set[int]:
    data = json.loads(bs_path.read_text(encoding="utf-8"))
    errs = data.get("errors", {})
    out: set[int] = set()
    for k in errs:
        if isinstance(k, int):
            out.add(k)
        elif isinstance(k, str) and k.isdigit():
            out.add(int(k))
    return out


def export_missing_json() -> None:
    """Write tools/errcode_missing.json for translators / merge scripts."""
    codes = parse_errcodes()
    for loc in ("zh-Hans", "en-US", "ja"):
        p = LOCALES / loc / "bs.json"
        have = locale_error_numeric_keys(p)
        missing = sorted(set(codes.keys()) - have)
        out = ROOT / "tools" / f"errcode_missing_{loc}.json"
        payload = {str(k): codes[k]["msg"] for k in missing}
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {out} ({len(payload)} entries)")


def main() -> None:
    codes = parse_errcodes()
    dups = duplicate_code_definitions()
    print(f"Parsed {len(codes)} errcode entries from {ERRDIR}")
    if dups:
        print(f"WARNING: duplicate numeric Code in errcode modules ({len(dups)}):")
        for c in sorted(dups)[:30]:
            print(f"  {c}: {dups[c]}")

    for loc in ("zh-Hans", "en-US", "ja"):
        p = LOCALES / loc / "bs.json"
        have = locale_error_numeric_keys(p)
        missing = sorted(set(codes.keys()) - have)
        orphan = sorted(have - set(codes.keys()))
        print(f"\n{loc}: missing {len(missing)} keys (vs errcode files)")
        for x in missing:
            info = codes[x]
            print(f"  {x}  # {info['file']} {info['class']}: {info['msg'][:80]}")
        print(f"  (locale numeric keys not in errcode scan: {len(orphan)})")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--export-missing":
        export_missing_json()
    else:
        main()
