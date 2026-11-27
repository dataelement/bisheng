import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('native_service', Path(__file__).with_name('service.py'))
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


class ServiceContract(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = service.Application(self.directory.name, 'x' * 32)

    def call(self, request, context=''):
        return self.app.execute({'request_json': json.dumps(request), 'context_id': context})

    def ended(self, result, outcome):
        self.assertIs(result['terminal'], True)
        self.assertEqual(result['next_action'], 'none')
        self.assertEqual(result['outcome'], outcome)
        self.assertTrue(result['answer'])

    def test_missing_context_never_creates_global_query(self):
        self.ended(self.call({'action': 'detail', 'reference': 'F01'}), 'needs_query')
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_context_traversal_and_unknown_context_rejected(self):
        self.ended(self.call({'action': 'show'}, '../outside'), 'invalid_context')
        self.ended(self.call({'action': 'show'}, 'f' * 48), 'expired_context')

    def test_duplicate_keys_and_unknown_envelope_rejected(self):
        self.ended(self.app.execute({'request_json': '{"action":"history","action":"show"}'}), 'invalid_request')
        self.ended(self.app.execute({'request_json': '{}', 'base_url': 'http://example.com'}), 'invalid_request')

    def test_each_new_query_has_independent_context(self):
        done = subprocess.CompletedProcess([], 0, json.dumps(service.terminal('ok', 'fixture')).encode(), b'')
        with patch.object(service.subprocess, 'run', return_value=done):
            a = self.call({'action': 'history'})
            b = self.call({'action': 'history'})
            c = self.call({'action': 'show'}, a['context_id'])
        self.assertNotEqual(a['context_id'], b['context_id'])
        self.assertEqual(a['context_id'], c['context_id'])

    def test_timeout_is_terminal_and_does_not_retry(self):
        with patch.object(service.subprocess, 'run', side_effect=subprocess.TimeoutExpired([], 25)) as run:
            self.ended(self.call({'action': 'history'}), 'timeout')
            run.assert_called_once()

    def test_corrupt_worker_result_fails_closed(self):
        done = subprocess.CompletedProcess([], 0, b'{"answer":"incomplete"}', b'')
        with patch.object(service.subprocess, 'run', return_value=done):
            self.ended(self.call({'action': 'history'}), 'execution_error')

    def test_busy_and_capacity_are_terminal(self):
        with patch.object(service, 'MAX_CONTEXTS', 0):
            self.ended(self.call({'action': 'history'}), 'capacity')
        for _ in range(4):
            self.app.capacity.acquire()
        self.ended(self.call({'action': 'history'}), 'busy')


if __name__ == '__main__':
    unittest.main()
