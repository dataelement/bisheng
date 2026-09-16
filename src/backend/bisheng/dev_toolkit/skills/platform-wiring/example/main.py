"""平台能力接线最小样例 —— 零第三方依赖,直接可 `bisheng dev` / `bisheng deploy`。

两件事,对应 SKILL.md 的第 1、2 章:

* **身份**:不做登录,只读平台入口注入的 `X-BiSheng-*` 请求头;页面上显示「你是谁」。
* **应用数据库**:从 `BISHENG_APP_DB_PATH` 连 SQLite,`CREATE TABLE IF NOT EXISTS` 建表,
  按 `user_id` 隔离每个人的便签,并演示一次幂等加列(`ensure_column`)。

本地跑:``bisheng dev``,然后打开它打印的本地入口地址(不是应用端口——直连没有身份头)。
"""

from __future__ import annotations

import html
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote

# 部署纳管的四条铁律:读 PORT、绑 0.0.0.0、只往 /data 写、对外链接带 BASE_PATH。
PORT = int(os.environ.get("PORT") or os.environ.get("BISHENG_APP_PORT") or 8080)
BASE_PATH = (os.environ.get("BISHENG_APP_BASE_PATH") or "").rstrip("/")
# 第 2 章:数据库路径只从环境变量读;本地直跑(没经 bisheng dev)退回当前目录。
DB_PATH = os.environ.get("BISHENG_APP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.db")


def url(path: str) -> str:
    return f"{BASE_PATH}{path}"


# ---- 第 1 章:访问者身份 -------------------------------------------------------


def current_user(headers) -> dict:
    """平台入口注入的访问者。缺 User-Id 说明请求没走平台入口(或本地直连了应用端口)。"""
    user_id = headers.get("X-BiSheng-User-Id")
    if not user_id:
        return {"id": None, "name": "(未经平台入口,没有身份)", "kind": None, "dept": None}
    return {
        "id": user_id,
        # 非 ASCII 的显示名/部门名是百分号编码过的,显示前要解码。
        "name": unquote(headers.get("X-BiSheng-User-Name") or ""),
        "kind": headers.get("X-BiSheng-Subject-Kind"),
        # 没有部门时这个头不存在——按「没有部门」处理,不是报错。
        "dept": unquote(headers.get("X-BiSheng-Dept-Name") or "") or None,
    }


# ---- 第 2 章:应用数据库 -------------------------------------------------------


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """加列:幂等,启动时跑一遍。新列必须带默认值或允许 NULL,老数据才能原样活下来。"""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        conn.commit()


def init_schema() -> None:
    conn = connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()
    # 第二个版本加的列——老库自动补上,不需要任何手动迁移。
    ensure_column(conn, "notes", "pinned", "INTEGER NOT NULL DEFAULT 0")
    conn.close()


def list_notes(user_id: str) -> list[tuple[int, str, str]]:
    conn = connect()
    rows = conn.execute(
        "SELECT id, body, created_at FROM notes WHERE user_id = ? ORDER BY id DESC LIMIT 20", (user_id,)
    ).fetchall()
    conn.close()
    return rows


def add_note(user_id: str, body: str) -> None:
    conn = connect()
    conn.execute("INSERT INTO notes (user_id, body) VALUES (?, ?)", (user_id, body))
    conn.commit()
    conn.close()


# ---- HTTP ---------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "bisheng-wiring/1.0"

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/healthz":
            self._send(200, b'{"status":"ok"}', "application/json")
            return
        user = current_user(self.headers)
        notes = list_notes(user["id"]) if user["id"] else []
        items = "".join(f"<li>{html.escape(body)} <small>{created}</small></li>" for _, body, created in notes)
        who = html.escape(user["name"])
        kind = {"human": "真人", "service_account": "服务账号"}.get(user["kind"] or "", "未知")
        dept = f"(部门:{html.escape(user['dept'])})" if user["dept"] else "(没有部门)"
        body = (
            "<!doctype html><meta charset='utf-8'><title>你是谁</title>"
            f"<h1>你是 {who}</h1>"
            f"<p>主体类型:{kind} {dept};用户 ID:{html.escape(str(user['id']))}</p>"
            "<p>这个身份来自平台入口注入的请求头,应用没有登录页。"
            "本地 <code>bisheng dev</code> 时它恒为你在命令行里登记的那个服务账号;线上是真实访问者。</p>"
            f"<form method='post' action='{url('/notes')}'>"
            "<input name='body' placeholder='只有你自己看得到的便签' required> <button>存到应用数据库</button></form>"
            f"<ul>{items}</ul>"
        ).encode()
        self._send(200, body)

    def do_POST(self) -> None:
        user = current_user(self.headers)
        length = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        text = (form.get("body") or [""])[0].strip()
        if user["id"] and text:
            add_note(user["id"], text)
        self.send_response(303)
        self.send_header("Location", url("/"))
        self.end_headers()

    def _send(self, status: int, body: bytes, content_type: str = "text/html; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    init_schema()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
