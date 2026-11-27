#!/usr/bin/env python3
"""Private Excel-snapshot mock of the supplied MK envelope. Python 3.8+, stdlib only."""
import argparse
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
import unicodedata
from urllib.parse import parse_qs, urlsplit

FUNCTION = 'mock_procurement_history_v1'
CALL = '/openapi/tic-definition/integrationInterface/call'
TOKEN_TTL = 7200


def norm(value):
    return ' '.join(unicodedata.normalize('NFKC', value).split()).casefold()


class Fault(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


def integer(value, name, maximum):
    if isinstance(value, bool) or not re.fullmatch(r'[1-9][0-9]{0,6}', str(value)):
        raise Fault(400, 'invalid_parameter', name + ' must be a positive integer')
    value = int(value)
    if value > maximum:
        raise Fault(400, 'invalid_parameter', name + ' exceeds budget')
    return value


def regex_worker():
    data = json.load(sys.stdin)
    try:
        pattern = re.compile(data['pattern'], re.IGNORECASE)
        print(json.dumps({'matches': [v for v in data['models'] if pattern.fullmatch(v)]}))
    except re.error:
        print(json.dumps({'error': 'invalid_regex'}))


class Application:
    def __init__(self, snapshot, credentials):
        raw = Path(snapshot).read_bytes()
        self.snapshot = json.loads(raw)
        self.snapshot_id = hashlib.sha256(raw).hexdigest()
        self.credentials = json.loads(Path(credentials).read_text())
        if not all(isinstance(self.credentials.get(k), str) and len(self.credentials[k]) >= 12
                   for k in ('appKey', 'appSecret')):
            raise ValueError('Mock credentials must be configured')
        self.tokens, self.lock = {}, threading.Lock()
        self.slots = threading.BoundedSemaphore(8)
        self.records = self.snapshot['records']
        self.columns = self.snapshot['columns']
        self.source_rows = self.snapshot['sourceRows']
        keys = [c['key'] for c in self.columns]
        if len(keys) != 129 or len(set(keys)) != 129 or len(self.records) != len(self.source_rows):
            raise ValueError('Invalid snapshot shape')
        if any(set(r) != set(keys) or not isinstance(r['col_CJ'], str) for r in self.records):
            raise ValueError('Invalid snapshot record')
        self.models = sorted(set(norm(r['col_CJ']) for r in self.records))

    def issue(self, body):
        if not isinstance(body, dict) or set(body) != {'appKey', 'appSecret'}:
            raise Fault(400, 'invalid_parameter', 'Expected appKey and appSecret')
        if not all(isinstance(body[k], str) and hmac.compare_digest(body[k], self.credentials[k])
                   for k in ('appKey', 'appSecret')):
            raise Fault(401, 'invalid_credentials', 'Invalid mock credentials')
        token, now = secrets.token_urlsafe(32), time.time()
        with self.lock:
            self.tokens = {k: expiry for k, expiry in self.tokens.items() if expiry > now}
            if len(self.tokens) >= 512:
                raise Fault(429, 'token_budget', 'Too many active tokens')
            self.tokens[token] = now + TOKEN_TTL
        return {'access_token': token, 'expires_in': TOKEN_TTL, 'errcode': 0}

    def authenticate(self, header, query):
        token = header[7:] if header.startswith('Bearer ') else query.get('access_token', [''])[0]
        with self.lock:
            valid = self.tokens.get(token, 0) > time.time()
        if not valid:
            raise Fault(401, 'invalid_token', 'Missing, expired or invalid mock access_token')

    def query(self, body):
        if not isinstance(body, dict) or set(body) != {'requestQuery'}:
            raise Fault(400, 'invalid_parameter', 'Expected requestQuery object')
        q = body['requestQuery']
        if not isinstance(q, dict) or set(q) - {'model', 'match_mode', 'pageNum', 'pageSize'}:
            raise Fault(400, 'invalid_parameter', 'Unknown query parameters')
        model, mode = q.get('model'), q.get('match_mode', 'exact')
        if not isinstance(model, str) or not model.strip() or len(model) > 256:
            raise Fault(400, 'invalid_parameter', 'model must contain 1-256 characters')
        if mode not in ('exact', 'regex'):
            raise Fault(400, 'invalid_parameter', 'match_mode must be exact or regex')
        page = integer(q.get('pageNum', 1), 'pageNum', 100000)
        size = integer(q.get('pageSize', 50), 'pageSize', 100)
        if mode == 'exact':
            matched = {norm(model)}
        else:
            # A killed child bounds catastrophic regex backtracking; no shell or user code execution.
            try:
                done = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--regex-worker'],
                                      input=json.dumps({'pattern': unicodedata.normalize('NFKC', model),
                                                        'models': self.models}),
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      encoding='utf-8', timeout=1, check=True)
                result = json.loads(done.stdout)
            except subprocess.TimeoutExpired:
                raise Fault(422, 'regex_timeout', 'Regex exceeded one-second runtime budget')
            if 'error' in result:
                raise Fault(400, 'invalid_regex', 'Invalid Python regular expression')
            matched = set(result['matches'])
        indices = [i for i, row in enumerate(self.records) if norm(row['col_CJ']) in matched]
        total = len(indices)
        selected = indices[(page - 1) * size:page * size]
        demo_sources=self.snapshot.get('demoSources',{})
        selected_models={self.records[i]['col_CJ'] for i in indices}
        source=self.snapshot['source']
        if len(selected_models)==1 and next(iter(selected_models)) in demo_sources:
            source=demo_sources[next(iter(selected_models))]
        elif selected_models & set(demo_sources):
            source={'file':'原始采购样例与独立模拟演示数据','sheet':'mixed',
                    'scope':'provided_excel_and_explicitly_synthetic_demo_records',
                    'sources':[self.snapshot['source'],*[demo_sources[m] for m in sorted(selected_models & set(demo_sources))]]}
        return {'totalElements': total, 'result': [self.records[i] for i in selected],
                'pageNum': page, 'pageSize': size, 'totalPages': math.ceil(total / size),
                'hasNext': page * size < total, 'snapshotId': self.snapshot_id,
                'schemaVersion': self.snapshot['schemaVersion'], 'mock': True,
                'scope': source['scope'], 'source': source,
                'recordOrigins': [self.snapshot.get('recordOrigins',[{}]*len(self.records))[i] for i in selected],
                'sourceRows': [self.source_rows[i] for i in selected], 'fieldMap': self.columns,
                'matchedModelCount': len(set(norm(self.records[i]['col_CJ']) for i in indices)),
                'query': {'model': model, 'match_mode': mode}}


class Handler(BaseHTTPRequestHandler):
    server_version = 'ProcurementMock/1.0'

    def log_message(self, *_):
        # The MK compatibility URL can contain a token. Never log URLs, bodies or credentials.
        pass

    def send_json(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.dispatch(False)

    def do_POST(self):
        self.dispatch(True)

    def dispatch(self, post):
        self.connection.settimeout(5)
        app = self.server.app
        if not app.slots.acquire(blocking=False):
            self.send_json(429, {'success': False, 'code': 'busy', 'msg': 'Request budget reached'})
            return
        trace = secrets.token_hex(12)
        try:
            u = urlsplit(self.path)
            query = parse_qs(u.query, keep_blank_values=True)
            if any(len(v) != 1 for v in query.values()):
                raise Fault(400, 'invalid_parameter', 'Duplicate URL parameters')
            if not post and u.path == '/health':
                self.send_json(200, {'status': 'ok', 'mock': True, 'rows': len(app.records),
                                     'columns': len(app.columns), 'snapshotId': app.snapshot_id})
                return
            if not post and u.path == '/openapi.json':
                schema = Path(__file__).with_name('openapi.json')
                if not schema.is_file():
                    raise Fault(404, 'schema_unavailable', 'OpenAPI definition is not installed')
                self.send_json(200, json.loads(schema.read_text(encoding='utf-8')))
                return
            if not post and u.path == '/':
                self.send_json(200, {'service': '采购历史Excel模拟接口', 'mock': True,
                                     'functionCode': FUNCTION, 'tokenEndpoint': '/authapi/getToken',
                                     'queryEndpoint': CALL,
                                     'notice': '测试样例；不是客户生产接口。业务数据需鉴权。'})
                return
            if post:
                if self.headers.get('Transfer-Encoding'):
                    raise Fault(400, 'invalid_request', 'Chunked requests are not supported')
                length = self.headers.get('Content-Length', '')
                if not length.isdigit() or not 0 < int(length) <= 16384:
                    raise Fault(413, 'body_budget', 'JSON body must contain 1-16384 bytes')
                if self.headers.get_content_type() != 'application/json':
                    raise Fault(415, 'content_type', 'Use application/json')
                try:
                    raw = self.rfile.read(int(length))
                    body = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                except (ValueError, UnicodeDecodeError):
                    raise Fault(400, 'invalid_json', 'Invalid JSON body')
            if post and u.path == '/authapi/getToken':
                self.send_json(200, app.issue(body))
                return
            if post and u.path == CALL:
                app.authenticate(self.headers.get('Authorization', ''), query)
                if query.get('functionCode') != [FUNCTION]:
                    raise Fault(404, 'unknown_function', 'Unknown mock functionCode')
                result = app.query(body)
                self.send_json(200, {'success': True, 'code': 'return.optSuccess',
                                     'msg': '您的操作已成功！', 'data': {'status': 200,
                                     'msg': '请求成功', 'data': result}, 'traceId': trace})
                return
            raise Fault(404, 'not_found', 'Unknown endpoint or method')
        except Fault as fault:
            self.send_json(fault.status, {'success': False, 'code': fault.code,
                                         'msg': fault.message, 'data': None, 'traceId': trace})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.send_json(500, {'success': False, 'code': 'internal_error',
                                 'msg': 'Mock processing failed; inspect service health', 'traceId': trace})
        finally:
            app.slots.release()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--credentials', required=True)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=18768)
    args = parser.parse_args()
    app = Application(args.snapshot, args.credentials)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    server.app = app
    server.serve_forever()


if __name__ == '__main__':
    if sys.argv[1:] == ['--regex-worker']:
        regex_worker()
    else:
        main()
