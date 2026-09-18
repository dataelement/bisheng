"""SQL/CSV 小工具. 不连库."""

from __future__ import annotations

import csv
import json
from pathlib import Path


def tsv_none(value: str | None) -> str | None:
    """mysql -B 把 SQL NULL 打成字面量 NULL."""
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in {"", "null", "none", "nil"}:
        return None
    return text


def escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("'", "''")


def sql_str(value: str | None) -> str:
    if value is None:
        return "NULL"
    return f"'{escape(value)}'"


def sql_ident(name: str) -> str:
    """反引号包裹表名/列名. group / role / user 是 MySQL 保留字."""
    text = str(name)
    if not text or any(ch in text for ch in "`\n;"):
        raise ValueError(f"bad ident: {name!r}")
    return f"`{text}`"


def sql_int(value: str | int | None, default: str = "NULL") -> str:
    if value is None or value == "":
        return default
    return str(int(value))


def sql_json(value) -> str:
    if value is None or value == "":
        return "NULL"
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return "NULL"
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return sql_str(text)
    return sql_str(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def sql_bool(value) -> str:
    if value in (True, 1, "1", "true", "True"):
        return "1"
    return "0"


def is_truthy(value) -> bool:
    return value in (True, 1, "1", "true", "True")


def alloc_int_id(start: int, taken: set[int]) -> int:
    """分配不与 taken 冲突的下一个整数主键, 并写入 taken."""
    n = start
    while n in taken:
        n += 1
    taken.add(n)
    return n


def load_csv(path: Path, delimiter: str = ",") -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        filtered = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    if not filtered:
        return []
    return [
        {k: (v or "").strip() for k, v in row.items() if k}
        for row in csv.DictReader(filtered, delimiter=delimiter)
    ]


def load_jsonl(path: Path) -> list[dict]:
    """每行一个 JSON 对象. mysql JSON_OBJECT 导出用, 避免 TSV 截断大字段."""
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for ln in f:
            text = ln.strip()
            if not text:
                continue
            # 跳过 mysql 客户端误进 stdout 的 warning
            if not text.startswith("{") and not text.startswith("["):
                continue
            rows.append(json.loads(text))
    return rows


def load_table(path: Path) -> list[dict[str, str]]:
    delim = "\t" if path.suffix.lower() == ".tsv" else ","
    return load_csv(path, delimiter=delim)


def fusion_batch_open_sql(batch: str, phase: str) -> str:
    return (
        "INSERT INTO fusion_batch (batch_no, phase, status) VALUES ("
        f"{sql_str(batch)}, {sql_str(phase)}, 'open') "
        "ON DUPLICATE KEY UPDATE phase=VALUES(phase), status='open';"
    )


def write_csv(
    path: Path,
    fieldnames: list[str],
    rows: list[dict[str, str]],
    header_comment: str = "",
    delimiter: str = ",",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        if header_comment:
            f.write(f"# {header_comment}\n")
        writer = csv.DictWriter(
            f, fieldnames=fieldnames, extrasaction="ignore", delimiter=delimiter
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
