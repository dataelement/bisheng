"""Standalone transport business API. No imports or patches to BISHENG."""
from __future__ import annotations
import argparse
import functools
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = Path(__file__).resolve().parent
MAX_BODY = 65536
MAX_CONTEXTS = 256
CONTEXT_TTL = 86400
EXECUTION_TIMEOUT = 25


def terminal(code, answer):
    return {'status': 'error', 'outcome': code, 'terminal': True,
            'next_action': 'none', 'answer': answer}


def worker(root):
    sys.path.insert(0, str(HERE / 'engine'))
    import contract
    import fetch_history
    import tool_adapter
    import transport
    from process_summary import business_process
    # Trusted service configuration, never a model supplied URL or credential.
    tool_adapter.fetch = functools.partial(fetch_history.fetch, allow_private=True)
    tool_adapter.fetch_inquiry = functools.partial(fetch_history.fetch_inquiry, allow_private=True)
    request = contract.loads(sys.stdin.buffer.read(MAX_BODY + 1))
    if request.get('action') == 'detail' and 'query_id' not in request:
        with transport.locked(root):
            state = transport.read(transport.safe(root, transport.STATE))[1]
            if transport.previous_inquiry(state):
                print(json.dumps(transport.refresh_inquiry(), ensure_ascii=False))
                return
            transport.validate_state(state)
            request['query_id'] = state['query_id']
    result = tool_adapter.execute({'request': request}, workspace=root,
                                  base_url=os.environ['TRANSPORT_API_ORIGIN'],
                                  token=os.environ['TRANSPORT_MOCK_TOKEN'])
    result['answer'] = business_process('transport', request, result)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


class Application:
    def __init__(self, state_dir, token):
        if not isinstance(token, str) or len(token) < 24:
            raise ValueError('Service credential missing')
        self.token = token
        self.root = Path(state_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.capacity = threading.BoundedSemaphore(4)

    def execute(self, body):
        if not isinstance(body, dict) or set(body) - {'request_json', 'context_id'}:
            return terminal('invalid_request', '运输请求参数无效，本轮已结束；请检查查询条件。')
        text = body.get('request_json')
        try:
            if not isinstance(text, str) or len(text.encode()) > MAX_BODY:
                raise ValueError()
            # Reuse the strict JSON decoder including duplicate-key rejection.
            sys.path.insert(0, str(HERE / 'engine'))
            from contract import loads
            request = loads(text)
            if not isinstance(request, dict):
                raise ValueError()
        except Exception:
            return terminal('invalid_request', '运输请求参数无效，本轮已结束；请检查查询条件。')
        context = body.get('context_id', '')
        if not isinstance(context, str):
            return terminal('invalid_context', '运输查询上下文无效，本轮已结束；请重新查询历史。')
        if not context:
            if request.get('action') not in ('history', 'inquiry', 'explain_limits'):
                return terminal('needs_query', '尚无当前运输查询，无法定位 F01；本轮已结束，请先查询历史费用。')
            if sum(p.is_dir() for p in self.root.iterdir()) >= MAX_CONTEXTS:
                return terminal('capacity', '运输查询服务暂忙，本轮已结束；请稍后重试。')
            context = secrets.token_hex(24)
            root = self.root / context
            root.mkdir(mode=0o700)
        else:
            if not re.fullmatch('[a-f0-9]{48}', context):
                return terminal('invalid_context', '运输查询上下文无效，本轮已结束；请重新查询历史。')
            root = self.root / context
            if root.is_symlink() or not root.is_dir() or time.time() - root.stat().st_mtime > CONTEXT_TTL:
                return terminal('expired_context', '运输查询上下文不存在或已过期，本轮已结束；请重新查询历史。')
        if not self.capacity.acquire(blocking=False):
            return terminal('busy', '运输查询服务暂忙，本轮已结束；请稍后重试。')
        try:
            completed = subprocess.run([sys.executable, str(HERE / 'service.py'), '--worker', str(root)],
                                       input=text.encode(), capture_output=True, timeout=EXECUTION_TIMEOUT)
            if completed.returncode or len(completed.stdout) > 1024 * 1024:
                return terminal('execution_error', '运输查询未能完成，本轮已结束；这不表示没有历史费用。')
            result = json.loads(completed.stdout)
            if result.get('terminal') is not True or result.get('next_action') != 'none' or not isinstance(result.get('answer'), str):
                raise ValueError('Result contract')
            result['context_id'] = context
            # Native follow-ups retain the final message, not arbitrary tool metadata.
            # Put the opaque context into the F reference's Markdown fragment so
            # it survives normal Chat history without a platform-specific hook.
            answer = result['answer']
            prefix = ''
            if answer.startswith('```business-process\n'):
                end = answer.find('\n```', len('```business-process\n'))
                if end >= 0:
                    prefix, answer = answer[:end + 4], answer[end + 4:]
            result['answer'] = prefix + re.sub(r'(?<![A-Za-z0-9])F\d{2,}(?![A-Za-z0-9])',
                lambda match: '[' + match[0] + '](#transport-context-' + context + '-' + match[0] + ')', answer)
            return result
        except subprocess.TimeoutExpired:
            return terminal('timeout', '运输查询超过处理时限，本轮已结束；这不表示没有历史费用，请稍后重试。')
        except Exception:
            return terminal('execution_error', '运输查询未能完成，本轮已结束；这不表示没有历史费用。')
        finally:
            self.capacity.release()


class Handler(BaseHTTPRequestHandler):
    server_version = 'TransportBusinessAPI/1.0'

    def log_message(self, *_):
        pass

    def reply(self, status, value):
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if self.path == '/health':
            self.reply(200, {'status': 'ok', 'service': 'transport-native-api'})
        elif self.path == '/openapi.json':
            self.reply(200, json.loads((HERE / 'openapi.json').read_text()))
        else:
            self.reply(404, terminal('not_found', '运输接口不存在，本轮已结束。'))

    def do_POST(self):
        self.connection.settimeout(5)
        if self.path != '/transport/execute':
            self.reply(404, terminal('not_found', '运输接口不存在，本轮已结束。')); return
        auth = self.headers.get('Authorization', '')
        if not hmac.compare_digest(auth.encode(), ('Bearer ' + self.server.app.token).encode()):
            self.reply(401, terminal('unauthorized', '运输工具鉴权失败，本轮已结束；请联系管理员检查工具配置。')); return
        length = self.headers.get('Content-Length', '')
        if self.headers.get('Transfer-Encoding') or not length.isdigit() or not 0 < int(length) <= MAX_BODY:
            self.reply(413, terminal('invalid_request', '运输请求大小超限，本轮已结束。')); return
        if self.headers.get_content_type() != 'application/json':
            self.reply(415, terminal('invalid_request', '运输请求格式错误，本轮已结束。')); return
        try:
            body = json.loads(self.rfile.read(int(length)))
            self.reply(200, self.server.app.execute(body))
        except Exception:
            self.reply(400, terminal('invalid_request', '运输请求无法解析，本轮已结束。'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker')
    parser.add_argument('--state', default='/state')
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    if args.worker:
        try:
            worker(Path(args.worker))
        except Exception:
            print(json.dumps(terminal('state_error', '运输查询状态无法读取，本轮已结束；请重新查询历史。'), ensure_ascii=False))
        return
    app = Application(args.state, os.environ.get('TRANSPORT_MOCK_TOKEN'))
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    server.daemon_threads = True
    server.app = app
    server.serve_forever()


if __name__ == '__main__':
    main()
