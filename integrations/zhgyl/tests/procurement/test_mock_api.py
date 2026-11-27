"""Smoke the standalone procurement API over HTTP with generated rows."""

import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'services' / 'procurement'))
from server import Application, Handler, ThreadingHTTPServer


class ProcurementMockTest(unittest.TestCase):
    def test_token_exact_regex_and_empty(self):
        with TemporaryDirectory() as directory:
            files = Path(directory)
            columns = ['col_CJ', *(f'test_{i}' for i in range(128))]
            models = ['DEMO-ALPHA-100', 'DEMO-ALPHA-101', 'DEMO-BETA-200']
            snapshot = {
                'schemaVersion': 1,
                'columns': [{'key': name} for name in columns],
                'records': [dict.fromkeys(columns, None) | {'col_CJ': name} for name in models],
                'sourceRows': [2, 3, 4],
                'source': {'file': 'fixture', 'scope': 'synthetic'},
            }
            credentials = {key: secrets.token_hex(12) for key in ('appKey', 'appSecret')}
            (files / 'snapshot.json').write_text(json.dumps(snapshot))
            (files / 'credentials.json').write_text(json.dumps(credentials))
            with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
                server.app = Application(files / 'snapshot.json', files / 'credentials.json')
                thread = Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f'http://127.0.0.1:{server.server_port}'
                try:
                    token = self.post(base + '/authapi/getToken', credentials)['access_token']
                    endpoint = (base + '/openapi/tic-definition/integrationInterface/call'
                                '?functionCode=mock_procurement_history_v1')
                    self.query(endpoint, token, 'demo-alpha-100', 'exact', 1)
                    self.query(endpoint, token, 'DEMO-ALPHA-10[01]', 'regex', 2)
                    # Delay only the child interpreter's startup. The query and
                    # tiny catalog are identical to the successful case above.
                    (files / 'sitecustomize.py').write_text(
                        'import sys, time\nif sys.argv[-1] == "--regex-worker":\n    time.sleep(1.25)\n'
                    )
                    with patch.dict(os.environ, {'PYTHONPATH': str(files)}):
                        self.query(endpoint, token, 'DEMO-ALPHA-10[01]', 'regex', 2)
                    self.assert_regex_fault(endpoint, token, 400, 'invalid_regex', '[')
                    with patch('server.subprocess.run', side_effect=subprocess.TimeoutExpired('worker', 5)):
                        self.assert_regex_fault(endpoint, token, 503, 'regex_worker_timeout')
                    self.assert_cpu_watchdog(endpoint, token)
                    self.query(endpoint, token, 'DEMO-ALPHA-10[01]', 'regex', 2)
                    self.query(endpoint, token, 'DEMO-UNKNOWN', 'exact', 0)
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        self.query(endpoint, 'expired', 'DEMO-ALPHA-100', 'exact', 1)
                    self.assertEqual(error.exception.code, 401)
                finally:
                    server.shutdown()
                    thread.join(timeout=2)

    @staticmethod
    def post(endpoint, payload, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        request = urllib.request.Request(endpoint, json.dumps(payload).encode(), headers)
        with urllib.request.urlopen(request, timeout=4) as reply:
            return json.load(reply)

    def query(self, endpoint, token, model, mode, expected):
        value = self.post(endpoint, {'requestQuery': {'model': model, 'match_mode': mode}}, token)
        self.assertTrue(value['success'])
        self.assertEqual(value['data']['data']['totalElements'], expected)

    def assert_regex_fault(self, endpoint, token, status, code, pattern='DEMO-ALPHA-10[01]'):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.query(endpoint, token, pattern, 'regex', 2)
        with error.exception as reply:
            self.assertEqual(reply.code, status)
            self.assertEqual(json.load(reply)['code'], code)

    def assert_cpu_watchdog(self, endpoint, token):
        run = subprocess.run
        # Exercise the real CPU timer with finite synthetic work, independent
        # of pattern complexity or the runner's wall-clock scheduling speed.
        program = """
import sys
import time

sys.path.insert(0, sys.argv[1])
import server

def compile_with_cpu_work(*args):
    end = time.process_time() + 0.4
    while time.process_time() < end:
        pass
    return original_compile(*args)

original_compile = server.re.compile
server.re.compile = compile_with_cpu_work
server.REGEX_CPU_SECONDS = 0.05
server.regex_worker()
"""
        def run_worker(command, **kwargs):
            return run([command[0], '-c', program, str(Path(command[1]).parent)], **kwargs)

        with patch('server.subprocess.run', side_effect=run_worker):
            self.assert_regex_fault(endpoint, token, 422, 'regex_timeout')


if __name__ == '__main__':
    unittest.main()
