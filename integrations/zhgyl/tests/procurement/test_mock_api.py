"""Smoke the standalone procurement API over HTTP with generated rows."""

import json
from pathlib import Path
import secrets
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
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


if __name__ == '__main__':
    unittest.main()
