"""Transport HTTP fixture; loopback default, explicit private-container binding."""
import argparse
import hmac
import os
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from contract import (active_query, SCHEMA, CALL, FUNCTION, ContractError, encode, loads, query,
                      require, response_page, sha, validate_entities, validate_source)


class Application:
    def __init__(self, snapshot, token):
        raw = Path(snapshot).read_bytes()
        self.snapshot = loads(raw)
        require(set(self.snapshot) == {'schemaVersion','source','details','bills'} and self.snapshot['schemaVersion'] == SCHEMA)
        validate_source(self.snapshot['source'])
        validate_entities(self.snapshot['details'], self.snapshot['bills'])
        require(isinstance(token, str) and 24 <= len(token) <= 256, 'A local token is required')
        self.snapshot_id, self.token = sha(raw), token
        self.slots = threading.BoundedSemaphore(8)


class Handler(BaseHTTPRequestHandler):
    server_version = 'TransportLocal/0.1'
    def log_message(self, *_):
        pass  # No request bodies, URLs, headers or credentials in logs.

    def reply(self, status, payload):
        raw = encode(payload)
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(raw)

    def dispatch(self, post=False):
        self.connection.settimeout(5)
        app, trace = self.server.app, secrets.token_hex(12)
        acquired = app.slots.acquire(blocking=False)
        try:
            if not acquired:
                self.error(429, 'busy', trace); return
            url = urlsplit(self.path)
            if not post and url.path == '/health' and not url.query:
                self.reply(200, {'status':'ok','mock':True,'rows':len(app.snapshot['details']),
                                'bills':len(app.snapshot['bills']),'snapshotId':app.snapshot_id}); return
            if not post and url.path == '/openapi.json' and not url.query:
                self.reply(200, loads(Path(__file__).with_name('openapi.json').read_bytes())); return
            if not post or url.path != CALL:
                self.error(404, 'not_found', trace); return
            params = parse_qs(url.query, keep_blank_values=True)
            if params != {'functionCode':[FUNCTION]}:
                self.error(400, 'invalid_function', trace); return
            header = self.headers.get('Authorization', '')
            if not header.startswith('Bearer ') or not hmac.compare_digest(header[7:].encode(), app.token.encode()):
                self.error(401, 'invalid_token', trace); return
            length = self.headers.get('Content-Length', '')
            if self.headers.get('Transfer-Encoding') or not length.isdigit() or not 0 < int(length) <= 16384:
                self.error(413, 'body_budget', trace); return
            if self.headers.get_content_type() != 'application/json':
                self.error(415, 'content_type', trace); return
            body = loads(self.rfile.read(int(length)))
            require(isinstance(body, dict) and set(body) == {'requestQuery'}, 'Expected requestQuery')
            params = body['requestQuery']
            require(isinstance(params, dict) and not set(params) - {'conditions','pageNum','pageSize'} and 'conditions' in params, 'Invalid query wrapper')
            result = response_page(app.snapshot, app.snapshot_id, active_query(params['conditions']),
                                   params.get('pageNum',1), params.get('pageSize',50))
            self.reply(200, {'success':True, 'code':'return.optSuccess','msg':'请求成功',
                             'data':{'status':200,'data':result},'traceId':trace})
        except ContractError:
            self.error(400, 'invalid_request', trace)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            pass
        except Exception:
            self.error(500, 'internal_error', trace)
        finally:
            if acquired:
                app.slots.release()

    def error(self, status, code, trace):
        self.reply(status, {'success':False,'code':code,'msg':code,'data':None,'traceId':trace})

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch(True)

    def do_PUT(self):
        self.reply(405, {'success':False,'code':'method_not_allowed','msg':'method_not_allowed',
                         'data':None,'traceId':secrets.token_hex(12)})

    do_DELETE = do_PATCH = do_PUT


def make_server(snapshot, token, port=0, bind='127.0.0.1'):
    require(bind in ('127.0.0.1','0.0.0.0'), 'Unsupported bind address')
    app = Application(snapshot, token)
    server = ThreadingHTTPServer((bind, port), Handler)
    server.daemon_threads = True
    server.app = app
    return server


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', required=True); parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--bind', choices=['127.0.0.1','0.0.0.0'], default='127.0.0.1',
                        help='0.0.0.0 only for the private D API container, with no host port publishing')
    args = parser.parse_args()
    instance = make_server(args.snapshot, os.environ.get('TRANSPORT_MOCK_TOKEN'), args.port, args.bind)
    print(encode({'listen':'http://'+args.bind+':' + str(instance.server_port), 'local_only':args.bind=='127.0.0.1'}).decode(), flush=True)
    try:
        instance.serve_forever()
    finally:
        instance.server_close()
