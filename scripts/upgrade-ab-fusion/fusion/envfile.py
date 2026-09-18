"""把 export KEY='value' 写进 env.sh. 只用于非密钥项, 禁止写 SSHPASS/密码."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def upsert_export(path: Path, key: str, value: str) -> None:
    """覆盖或追加一行 export KEY='value'. value 不得含单引号."""
    if not _KEY_RE.match(key):
        raise ValueError(f"非法环境变量名: {key}")
    if "'" in value or "\n" in value or "\r" in value:
        raise ValueError(f"{key} 含非法字符, 拒绝写入")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    line = f"export {key}='{value}'"
    pat = re.compile(rf"^export {re.escape(key)}=.*$", re.M)
    if pat.search(text):
        text = pat.sub(line, text, count=1)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="upsert env.sh export 行")
    sub = p.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("upsert")
    u.add_argument("path")
    u.add_argument("key")
    u.add_argument("value")
    args = p.parse_args(argv)
    if args.cmd == "upsert":
        upsert_export(Path(args.path), args.key, args.value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
