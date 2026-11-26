"""Shared-record example: trusted gateway identity, persistent CAS writes and SSE."""

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from bisheng_sdk import auth
from bisheng_sdk.errors import PlatformIdentityMissingError
from bisheng_sdk.realtime import OperationConflict, RealtimeStore, ReplayExpired, RevisionConflict

store = RealtimeStore()
base = os.environ.get("BISHENG_APP_BASE_PATH", "").rstrip("/")
PAGE = r"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>协作工作台</title><style>body{font:16px system-ui;margin:32px;max-width:800px}textarea{width:100%;min-height:100px}pre{white-space:pre-wrap}button{padding:10px;margin:12px 0}</style><h1>团队共享记录</h1><p>每人使用自己的毕昇账号。保存后同事自动看到结果，未保存的输入属于自己。</p><p id="status" role="status">正在同步…</p><textarea id="note" aria-label="共享记录"></textarea><button id="save">保存</button><button id="rebase" hidden>比较后，以最新版本继续编辑</button><pre id="records"></pre><script>
const base=__BASE__;let state={cursor:0,records:[]},editingRevision=null,conflicted=false;
const note=document.getElementById('note'),status=document.getElementById('status');
async function load(){const r=await fetch(base+'/api/snapshot',{cache:'no-store'});if(!r.ok){const e=Error([401,403].includes(r.status)?'身份或权限已变更，请重新打开工作台':'读取失败 '+r.status);e.noRetry=[401,403].includes(r.status);throw e}const next=await r.json();if(next.cursor>=state.cursor){state=next;document.getElementById('records').textContent=JSON.stringify(state.records,null,2);if(editingRevision===null)note.value=state.records.find(r=>r.id==='shared-note')?.value?.text||'';}}
note.onfocus=()=>{editingRevision??=state.records.find(r=>r.id==='shared-note')?.revision||0};
document.getElementById('rebase').onclick=()=>{editingRevision=state.records.find(r=>r.id==='shared-note')?.revision||0;conflicted=false;document.getElementById('rebase').hidden=true;status.textContent='已采用最新记录版本，当前输入保留，确认后可保存'};
document.getElementById('save').onclick=async()=>{if(conflicted){status.textContent='请先比较并确认最新记录版本';return}const operation_id=crypto.randomUUID?crypto.randomUUID():Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);try{const r=await fetch(base+'/api/record',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({text:note.value,expected_revision:editingRevision??(state.records.find(r=>r.id==='shared-note')?.revision||0),operation_id})});if(r.status===409){await load();conflicted=true;document.getElementById('rebase').hidden=false;throw Error('记录已被他人更新，请比较最新记录后重新编辑；当前输入已保留。')}if(!r.ok)throw Error('保存失败 '+r.status);editingRevision=null;await load();status.textContent='已保存并同步'}catch(e){status.textContent=e.message}};
let events=null,retryDelay=500,retryTimer=null;
function retry(){events?.close();clearTimeout(retryTimer);retryTimer=setTimeout(async()=>{try{await load();connect()}catch(e){status.textContent=e.message;if(!e.noRetry){retryDelay=Math.min(retryDelay*2,30000);retry()}}},retryDelay)}
function connect(){events=new EventSource(base+'/api/events?after='+state.cursor);events.onmessage=e=>{if(Number(e.lastEventId)>state.cursor)load().then(()=>status.textContent='已同步').catch(e=>status.textContent=e.message)};events.addEventListener('reset',retry);events.onopen=()=>{retryDelay=500;status.textContent='实时同步已连接'};events.onerror=()=>{status.textContent='同步连接中断，正在重连；未保存输入仍保留';retry()}}
load().then(connect).catch(e=>status.textContent=e.message);
</script></html>"""  # noqa: RUF001 - Chinese punctuation in the embedded UI is intentional.


class Handler(BaseHTTPRequestHandler):
    def send(self, data, code=200, kind="application/json; charset=utf-8"):
        body = data.encode() if isinstance(data, str) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def visitor(self):
        with auth.bind(dict(self.headers.items())):
            return auth.current_user()

    def do_GET(self):
        path = urlsplit(self.path).path.rstrip("/")
        # Health probes do not require visitor identity and never change data.
        if not path:
            self.send(
                PAGE.replace("__BASE__", json.dumps(base).replace("<", "\\u003c")), kind="text/html; charset=utf-8"
            )
            return
        try:
            self.visitor()
        except PlatformIdentityMissingError:
            self.send({"error": "identity_required"}, 401)
            return
        if path == "/api/snapshot":
            self.send(store.snapshot("notes"))
        elif path == "/api/events":
            query = parse_qs(urlsplit(self.path).query)
            try:
                cursor = int(self.headers.get("Last-Event-ID") or query.get("after", ["0"])[0])
                store.events(cursor)
            except (ValueError, ReplayExpired):
                self.send({"error": "snapshot_required"}, 409)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            try:
                while True:
                    try:
                        events = store.events(cursor)
                    except ReplayExpired:
                        self.wfile.write(b"event: reset\ndata: {}\n\n")
                        self.wfile.flush()
                        return
                    for event in events:
                        cursor = event["seq"]
                        self.wfile.write(f"id: {cursor}\ndata: {json.dumps(event)}\n\n".encode())
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    time.sleep(1)
            except (BrokenPipeError, ConnectionResetError):
                return
        else:
            self.send({"error": "not_found"}, 404)

    def read_body(self):
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            chunks, size = [], 0
            while True:
                line = self.rfile.readline(128)
                length = int(line.split(b";", 1)[0], 16)
                if length < 0 or size + length > 8192:
                    raise ValueError()
                if not length:
                    if self.rfile.readline(128) != b"\r\n":
                        raise ValueError()
                    return b"".join(chunks)
                data = self.rfile.read(length)
                if len(data) != length or self.rfile.read(2) != b"\r\n":
                    raise ValueError()
                chunks.append(data)
                size += length
        size = int(self.headers.get("Content-Length", "0"))
        if size < 0 or size > 8192:
            raise ValueError()
        return self.rfile.read(size)

    def do_POST(self):
        if urlsplit(self.path).path != "/api/record":
            self.send({"error": "not_found"}, 404)
            return
        try:
            visitor = self.visitor()
        except PlatformIdentityMissingError:
            self.send({"error": "identity_required"}, 401)
            return
        try:
            body = json.loads(self.read_body())
            if not isinstance(body, dict) or not isinstance(body.get("text"), str) or len(body["text"]) > 2000:
                raise ValueError()
            result = store.write(
                "notes",
                "shared-note",
                {"text": body["text"]},
                expected_revision=body["expected_revision"],
                operation_id=body["operation_id"],
                actor=f"{visitor.tenant_id}:{visitor.user_id}",
            )
            self.send(result)
        except (RevisionConflict, OperationConflict):
            self.send({"error": "revision_conflict"}, 409)
        except (ValueError, KeyError, TypeError):
            self.send({"error": "invalid_request"}, 400)


if __name__ == "__main__":
    ThreadingHTTPServer(
        (os.environ.get("BISHENG_APP_BIND", "0.0.0.0"), int(os.environ.get("PORT", "8080"))), Handler
    ).serve_forever()
