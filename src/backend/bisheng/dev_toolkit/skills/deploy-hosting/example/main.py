"""最小托管应用样例 —— 零第三方依赖,直接可 `bisheng deploy`。

四条托管运行契约(见 SKILL.md §1)都体现在这几行里,每一条在本地
`python main.py` 时都是无害的默认值,所以本地验过的行为在平台上成立:

* 铁律①  监听平台注入的 PORT。
* 铁律②  绑 0.0.0.0,不是 127.0.0.1。
* 铁律③  只往 /data 写(这里落一个 SQLite 计数器演示)。
* 铁律④  对外链接带 BISHENG_APP_BASE_PATH。

本地跑:``python main.py`` 然后开 http://127.0.0.1:8080
"""

from __future__ import annotations

import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 铁律①:读平台注入的端口,取不到用本地默认。别写死。
PORT = int(os.environ.get("PORT") or os.environ.get("BISHENG_APP_PORT") or 8080)

# 铁律④:对外基路径。平台上是 /apps/{slug},本地是空串。所有对外链接都过 url()。
BASE_PATH = (os.environ.get("BISHENG_APP_BASE_PATH") or "").rstrip("/")

# 铁律③:只往 /data 写。平台用 BISHENG_APP_DB_PATH 告诉应用数据库在哪;本地退回当前目录。
DB_PATH = os.environ.get("BISHENG_APP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.db")


def url(path: str) -> str:
    """把应用内部路径拼成对外可点的地址(漏一处那处就跳到平台根路径)。"""
    return f"{BASE_PATH}{path}"


def bump_and_read() -> int:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS hits (id INTEGER PRIMARY KEY AUTOINCREMENT)")
    conn.execute("INSERT INTO hits DEFAULT VALUES")
    total = conn.execute("SELECT COUNT(*) FROM hits").fetchone()[0]
    conn.commit()
    conn.close()
    return total


class Handler(BaseHTTPRequestHandler):
    server_version = "bisheng-hello/1.0"

    def do_GET(self) -> None:
        path = self.path.rstrip("/") or "/"
        if path == "/healthz":
            # 平台默认探 `/`;这条只是给运维一个不渲染页面的探针。
            self._send(200, b'{"status":"ok"}', "application/json")
            return
        total = bump_and_read()
        body = (
            "<!doctype html><meta charset='utf-8'>"
            "<title>你好,托管应用</title>"
            "<h1>你好,托管应用 👋</h1>"
            f"<p>这是第 {total} 次访问(计数落在应用自己的 /data 数据卷里)。</p>"
            f"<p><a href='{url('/')}'>刷新一下</a></p>"
        ).encode()
        self._send(200, body)

    def _send(self, status: int, body: bytes, content_type: str = "text/html; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    # 铁律②:绑 0.0.0.0,不是 127.0.0.1。
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
