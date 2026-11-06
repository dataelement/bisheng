"""表单问卷 —— BiSheng 托管应用示例（零第三方依赖）。

这个示例存在的理由是验证一条最小闭环：本地写的应用 → `bisheng deploy` →
平台托管上线 → 所有人在应用广场里访问它。它刻意只用标准库，因为演示要验的是
部署链路本身，不是依赖解析——「构建卡在 pip 拉不到包」在 114 和信创基线上是
最常见、也最容易被误判成平台故障的失败。

它同时是托管运行契约（PRD-1 DEV-04）的一份可执行说明。四条约定，缺一条就会在
平台上出问题，而每一条在本地直接 `python main.py` 时都恰好是无害的默认值：

* **监听 PORT**。平台按 manifest 的 `port` 注入 `PORT` 与 `BISHENG_APP_PORT`。
  硬编码端口的应用探活必失败。
* **绑 0.0.0.0**。绑 127.0.0.1 的进程在容器里只有自己能连上，健康探针会一直
  失败，而日志里什么错都没有——这是最难查的一种"应用起来了但不健康"。
* **外链带 BISHENG_APP_BASE_PATH**。平台把应用挂在 `/apps/{slug}` 下，
  app-proxy 会把前缀剥掉再转发，所以应用**收到的**是根路径；但应用**发出的**
  链接（form action、跳转、静态资源）必须自己带上前缀，否则点一下就跳到平台
  根路径上去了。本地跑时这个变量为空，拼出来就是原来的根路径。
* **只往 /data 写**。容器根文件系统是只读的（AC-17），/data 是唯一的可写卷，
  平台通过 BISHENG_APP_DB_URL / BISHENG_APP_DB_PATH 告诉应用它在哪。往别处写
  会在运行期才炸，而不是在构建期。

本地跑：``python main.py`` 然后开 http://127.0.0.1:8080
"""

from __future__ import annotations

import html
import json
import os
import sqlite3
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 平台注入的四个变量，每个都给了本地可用的默认值。这不是"兜底"——本地与平台
# 跑的是同一份代码同一条路径，差别只在变量取值，所以本地验过的行为在平台上成立。
PORT = int(os.environ.get("PORT") or os.environ.get("BISHENG_APP_PORT") or 8080)
BASE_PATH = (os.environ.get("BISHENG_APP_BASE_PATH") or "").rstrip("/")
DB_PATH = os.environ.get("BISHENG_APP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "survey.db")

QUESTIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("role", "你的角色是？", ("业务人员", "开发者", "管理员")),
    ("channel", "你从哪里知道这个平台？", ("同事推荐", "搜索", "会议或文章")),
    ("useful", "这次部署体验如何？", ("顺利", "还行", "遇到了问题")),
)


def url(path: str) -> str:
    """把应用内部路径拼成对外可点的地址。

    平台上 BASE_PATH 是 ``/apps/form-survey``，本地是空串。所有 form action 与
    跳转都必须过这里——漏一处，那一处在平台上就会跳到平台根路径。
    """
    return f"{BASE_PATH}{path}"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS response (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            answers TEXT NOT NULL,
            comment TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()
    return conn


PAGE = """<!doctype html>
<html lang="zh-Hans"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 16px/1.6 -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         max-width: 42rem; margin: 0 auto; padding: 2rem 1.25rem; }}
  h1 {{ font-size: 1.5rem; margin-bottom: .25rem; }}
  .sub {{ opacity: .65; margin-top: 0; }}
  fieldset {{ border: 1px solid rgba(128,128,128,.35); border-radius: 8px;
              margin: 0 0 1rem; padding: .75rem 1rem 1rem; }}
  legend {{ padding: 0 .35rem; font-weight: 600; }}
  label {{ display: block; padding: .2rem 0; }}
  textarea {{ width: 100%; box-sizing: border-box; padding: .5rem;
              border-radius: 6px; border: 1px solid rgba(128,128,128,.35);
              background: transparent; color: inherit; font: inherit; }}
  button {{ font: inherit; padding: .55rem 1.4rem; border-radius: 6px;
            border: 0; background: #2563eb; color: #fff; cursor: pointer; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ text-align: left; padding: .4rem .6rem;
            border-bottom: 1px solid rgba(128,128,128,.25); }}
  .bar {{ display: inline-block; height: .7rem; background: #2563eb;
          border-radius: 3px; vertical-align: middle; }}
  a {{ color: #2563eb; }}
</style></head><body>{body}</body></html>
"""


def render(title: str, body: str) -> bytes:
    return PAGE.format(title=html.escape(title), body=body).encode("utf-8")


def form_page() -> bytes:
    blocks = []
    for key, label, options in QUESTIONS:
        choices = "".join(
            f'<label><input type="radio" name="{key}" value="{html.escape(opt)}" required> {html.escape(opt)}</label>'
            for opt in options
        )
        blocks.append(f"<fieldset><legend>{html.escape(label)}</legend>{choices}</fieldset>")
    return render(
        "表单问卷",
        f"""
        <h1>表单问卷</h1>
        <p class="sub">一个跑在 BiSheng 托管运行时上的示例应用。</p>
        <form method="post" action="{url("/submit")}">
          {"".join(blocks)}
          <fieldset><legend>还想说点什么？（选填）</legend>
            <textarea name="comment" rows="3" maxlength="500"></textarea>
          </fieldset>
          <button type="submit">提交</button>
        </form>
        <p><a href="{url("/results")}">看看大家怎么答的 →</a></p>
        """,
    )


def thanks_page() -> bytes:
    return render(
        "已收到",
        f"""
        <h1>已收到，谢谢</h1>
        <p class="sub">你的回答已经存进这个应用自己的数据卷里。</p>
        <p><a href="{url("/results")}">查看统计</a> · <a href="{url("/")}">再答一次</a></p>
        """,
    )


def results_page() -> bytes:
    with connect() as conn:
        rows = conn.execute("SELECT answers FROM response").fetchall()
    total = len(rows)
    tally: dict[str, dict[str, int]] = {key: dict.fromkeys(opts, 0) for key, _, opts in QUESTIONS}
    for (payload,) in rows:
        try:
            answers = json.loads(payload)
        except json.JSONDecodeError:
            continue
        for key, value in answers.items():
            if key in tally and value in tally[key]:
                tally[key][value] += 1

    sections = []
    for key, label, options in QUESTIONS:
        rows_html = ""
        for opt in options:
            count = tally[key][opt]
            width = 0 if total == 0 else round(count * 100 / total)
            rows_html += (
                f"<tr><td>{html.escape(opt)}</td>"
                f'<td><span class="bar" style="width:{width * 2}px"></span> {count}</td></tr>'
            )
        sections.append(f"<h2>{html.escape(label)}</h2><table>{rows_html}</table>")

    return render(
        "问卷统计",
        f"""
        <h1>问卷统计</h1>
        <p class="sub">共 {total} 份回答。</p>
        {"".join(sections)}
        <p><a href="{url("/")}">← 回到问卷</a></p>
        """,
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "bisheng-form-survey/1.0"

    def _send(self, status: int, body: bytes, content_type: str = "text/html; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
        if path == "/":
            self._send(200, form_page())
        elif path == "/thanks":
            self._send(200, thanks_page())
        elif path == "/results":
            self._send(200, results_page())
        elif path == "/healthz":
            # 平台默认探 `/`，这条只是给运维一个不渲染页面的探针。
            self._send(200, b'{"status":"ok"}', "application/json")
        else:
            self._send(404, render("找不到页面", f'<h1>404</h1><p><a href="{url("/")}">回到问卷</a></p>'))

    def do_POST(self) -> None:
        if urllib.parse.urlparse(self.path).path.rstrip("/") != "/submit":
            self._send(404, render("找不到页面", "<h1>404</h1>"))
            return

        length = int(self.headers.get("Content-Length") or 0)
        form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        answers = {key: form.get(key, [""])[0] for key, _, _ in QUESTIONS}
        comment = form.get("comment", [""])[0][:500]

        with connect() as conn:
            conn.execute(
                "INSERT INTO response (answers, comment) VALUES (?, ?)",
                (json.dumps(answers, ensure_ascii=False), comment),
            )
            conn.commit()

        # 303 而不是 302：提交后刷新不该重复写一条回答。
        self.send_response(303)
        self.send_header("Location", url("/thanks"))
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt: str, *args) -> None:
        # 平台按容器 stdout 收日志，`bisheng logs` 读的就是这里。
        print(f"{self.address_string()} {fmt % args}", flush=True)


def main() -> None:
    connect().close()
    # 必须是 0.0.0.0：绑 127.0.0.1 在容器里只有进程自己连得上，健康探针会一直
    # 失败而日志干干净净——这是最难查的一种"起来了但不健康"。
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"form-survey listening on 0.0.0.0:{PORT} base_path={BASE_PATH!r} db={DB_PATH}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
