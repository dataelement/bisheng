"""Extract (Code, Msg) from errcode modules using AST (handles multiline Msg)."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRDIR = ROOT / "src/backend/bisheng/common/errcode"
SKIP = {"base.py", "__init__.py", "README.md"}


def _literal_concat(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            else:
                parts.append("")
        return "".join(parts)
    return None


def extract_from_file(path: Path) -> list[tuple[int, str, str]]:
    """Return list of (code, msg, class_name)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: list[tuple[int, str, str]] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(
            isinstance(b, ast.Name) and b.id == "BaseErrorCode"
            or isinstance(b, ast.Attribute) and b.attr == "BaseErrorCode"
            for b in node.bases
        ):
            continue
        code_val: int | None = None
        msg_val: str | None = None
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and stmt.target is not None:
                if isinstance(stmt.target, ast.Name):
                    name = stmt.target.id
                    if name == "Code" and isinstance(stmt.value, ast.Constant):
                        if isinstance(stmt.value.value, int):
                            code_val = stmt.value.value
                    elif name == "Msg":
                        joined = _literal_concat(stmt.value)
                        if joined is not None:
                            msg_val = joined
            elif isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if not isinstance(target, ast.Name):
                        continue
                    if target.id == "Code" and isinstance(stmt.value, ast.Constant):
                        if isinstance(stmt.value.value, int):
                            code_val = stmt.value.value
                    elif target.id == "Msg":
                        joined = _literal_concat(stmt.value)
                        if joined is not None:
                            msg_val = joined
        if code_val is not None and msg_val is not None:
            msg_val = re.sub(r"\s+", " ", msg_val).strip()
            out.append((code_val, msg_val, node.name))
    return out


def duplicate_code_definitions() -> dict[int, list[str]]:
    """Same numeric Code declared in more than one class (backend design debt)."""
    from collections import defaultdict

    hits: dict[int, list[str]] = defaultdict(list)
    for path in sorted(ERRDIR.glob("*.py")):
        if path.name in SKIP:
            continue
        for code, _msg, cls in extract_from_file(path):
            hits[code].append(f"{path.name}:{cls}")
    return {c: v for c, v in hits.items() if len(v) > 1}


def all_errcodes() -> dict[int, tuple[str, str, str]]:
    """code -> (msg, class_name, file) last file wins on duplicate code."""
    codes: dict[int, tuple[str, str, str]] = {}
    for path in sorted(ERRDIR.glob("*.py")):
        if path.name in SKIP:
            continue
        for code, msg, cls in extract_from_file(path):
            codes[code] = (msg, cls, path.name)
    return codes


if __name__ == "__main__":
    import json
    import sys

    c = all_errcodes()
    if len(sys.argv) > 1 and sys.argv[1] == "--dump-en":
        out = {str(k): {"en": v[0], "class": v[1], "file": v[2]} for k, v in sorted(c.items())}
        p = ROOT / "tools" / "errcode_en_from_ast.json"
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Wrote", p, len(out))
        sys.exit(0)

    print("total codes", len(c))
    real_dups = duplicate_code_definitions()
    print("duplicate definitions", len(real_dups))
    for code in sorted(real_dups)[:25]:
        print(code, real_dups[code])
