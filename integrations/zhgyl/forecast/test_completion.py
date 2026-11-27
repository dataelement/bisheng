"""Completion protocol fixtures: no live Skill/model or timing evidence.

The real workflow and NativeBridge run against an in-memory authenticated API
fixture. Only the server worker is exercised; no browser is present or needed.
"""
import copy
import io
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from completion import CompletionSupervisor
from native_bridge import NativeBridge, NativeBridgeError
from server import native_summary
from test_workflow import FakeApp
from workflow import Workflow, WorkflowError


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = FakeApp(self.temp.name)
        self.app.workflow = Workflow(self.app)
        self.created = self.app.workflow.create({'spec': '189A1002-1', 'months': 2})
        self.runid, self.token = self.created['run_id'], self.created['token']
        self.hashes = self.app.workflow._hashes()
        self.cookie = 'session=ONLY-A-FIXTURE'
        self.task = {'chat_id': 'fixture-chat', 'session_version_id': 'fixture-version'}
        self.app.native_tool_key = 'fixture_forecast_tool'
        self.app.native = NativeBridge('http://fixture.invalid', tool_key=self.app.native_tool_key)
        self.version = {'id': self.task['session_version_id'], 'session_id': self.task['chat_id'],
                        'model': '1', 'user_id': 1, 'status': 'in_progress',
                        'skills': ['procurement-forecast-fast'],
                        'question': json.dumps({'run_id': self.runid, 'token': self.token}),
                        'tools': [{'id': 46, 'tool_key': self.app.native_tool_key}]}
        self.records = [{'name': 'read_file', 'input': {'file_path': '/skills/procurement-forecast-fast/SKILL.md'},
                         'output': 'Fixture Skill body, not a model execution'}]
        self.posts = []
        self.app.native.opener = Mock()
        self.app.native.opener.open.side_effect = self.native_request
        self.supervisor = CompletionSupervisor(self.app)

    def native_request(self, request, timeout):
        self.assertEqual(request.get_header('Cookie'), self.cookie)
        if request.get_method() == 'POST':
            self.assertTrue(request.full_url.endswith('/terminate-execute'))
            self.posts.append(json.loads(request.data))
            payload = None
        elif '/session-version-list?' in request.full_url:
            payload = [self.version]
        elif request.full_url.endswith('/skill/runtime/catalog'):
            payload = [{'name': 'procurement-forecast-fast', 'content_hash': self.hashes['skill_sha256']}]
        elif request.full_url.endswith('/workstation/config'):
            payload = {'models': [{'id': '1', 'name': 'fixture-model'}],
                       'tools': [{'id': 46, 'tool_key': self.app.native_tool_key,
                                  'name': 'forecast_execute', 'enabled': True}]}
        elif '/execute-task-detail?' in request.full_url:
            payload = [{'history': copy.deepcopy(self.records)}]
        else:
            raise AssertionError('Unexpected fixture API path: ' + request.full_url)
        return io.BytesIO(json.dumps({'status_code': 200, 'data': payload}).encode())

    def freeze_business_actions(self):
        prepared = self.app.workflow.prepare(self.runid, self.token, self.hashes)
        explanation = {'headline': '测试解释', 'body': '仅测试后台完成合同，不证明真实模型调用。',
                       'factors': [{'title': '样本', 'value': str(prepared['facts']['history']['summary']['record_count']),
                                    'detail': '测试范围事实'}],
                       'limitations': ['模拟订单与预测，不证明业务效果。'],
                       'influences': [{'title': '交付', 'detail': '使用完成交付统计。',
                                       'evidence_refs': ['STAT-DELIVERY']}],
                       'suggestions': [{'spec': target['spec'], 'customer': target['customer'],
                                        'reason': '按模型原值复核。', 'evidence_refs': target['evidence_refs']}
                                       for target in prepared['suggestion_targets']]}
        final = self.app.workflow.action(self.runid, self.token, 'finalize',
                    {**self.hashes, 'facts_ref': prepared['facts_ref'], 'explanation': explanation})
        self.records.extend({'name': self.app.native_tool_key, 'is_completed': True,
                             'output': json.dumps(native_summary(value), ensure_ascii=False)}
                            for value in (prepared, final))

    def run_worker(self):
        job = {'task': dict(self.task), 'state': 'running'}
        self.supervisor._complete(self.runid, self.token, self.cookie, job)
        return job

    def assert_no_report(self):
        self.assertIsNone(self.app.workflow.get(self.runid, self.token)['result'])
        self.assertEqual(self.app.report_cache, {})
        self.assertFalse((self.app.runtime / 'reports').exists())

    def assert_only_bound_task_stopped(self):
        self.assertEqual(self.posts, [{'linsight_session_version_id': self.task['session_version_id']}])

    def test_forged_bind_never_starts_worker_or_terminates_unrelated_task(self):
        original = copy.deepcopy(self.version)
        mutations = ({'question': json.dumps({'run_id': self.runid})},
                     {'question': json.dumps({'token': self.token})},
                     {'question': 'unrelated task'}, {'session_id': 'other-chat'},
                     {'id': 'other-version'}, {'skills': ['procurement-history']})
        with patch('completion.threading.Thread') as thread:
            for mutation in mutations:
                with self.subTest(mutation=mutation):
                    self.version = {**original, **mutation}
                    with self.assertRaises(WorkflowError):
                        self.supervisor.bind(self.runid, self.token, self.cookie, self.task)
                    thread.assert_not_called()
                    self.assertEqual(self.supervisor.jobs, {})
                    self.assertEqual(self.posts, [])
                    self.assert_no_report()

    def test_bind_requires_valid_run_capability_and_authenticated_native_read(self):
        with patch('completion.threading.Thread') as thread:
            with self.assertRaises(WorkflowError):
                self.supervisor.bind(self.runid, 'forged-token', self.cookie, self.task)
            self.app.native.opener.open.assert_not_called()
            with patch.object(self.app.native, '_get', side_effect=NativeBridgeError('unauthorized', 403)):
                with self.assertRaises(NativeBridgeError):
                    self.supervisor.bind(self.runid, self.token, self.cookie, self.task)
            thread.assert_not_called()
        self.assertEqual(self.posts, [])
        self.assertEqual(self.supervisor.jobs, {})

    def test_bound_task_cannot_be_replaced_with_other_termination_target(self):
        with patch('completion.threading.Thread') as thread:
            self.supervisor.bind(self.runid, self.token, self.cookie, self.task)
            self.supervisor.bind(self.runid, self.token, self.cookie, self.task)
            with self.assertRaises(WorkflowError):
                self.supervisor.bind(self.runid, self.token, self.cookie,
                                     {**self.task, 'session_version_id': 'other-version'})
            self.assertEqual(thread.call_count, 1)
        self.assertEqual(self.posts, [])
        self.assertEqual(self.supervisor.jobs[self.runid]['task'], self.task)
        stored = json.dumps(self.supervisor.jobs)
        self.assertNotIn(self.token, stored)
        self.assertNotIn(self.cookie, stored)

    def test_worker_completes_after_request_returns_without_browser(self):
        stopped = threading.Event()
        original_stop = self.supervisor._stop
        def stop(*args):
            try: return original_stop(*args)
            finally: stopped.set()
        with patch.object(self.supervisor, '_stop', side_effect=stop), \
                patch.object(self.app.native, 'verify', wraps=self.app.native.verify) as verify:
            self.assertEqual(self.supervisor.bind(self.runid, self.token, self.cookie, self.task)['state'], 'bound')
            self.assert_no_report()
            # A native API result arrives after the initiating request is gone.
            self.freeze_business_actions()
            self.assertTrue(stopped.wait(3), 'bounded worker did not finish')
            self.assertTrue(verify.call_args.kwargs['business_checkpoint'])
        status = self.app.workflow.get(self.runid, self.token)
        self.assertEqual(status['state'], 'completed')
        self.assertEqual(status['result']['provenance']['native_agent']['status'], 'in_progress')
        self.assertEqual(set(name for run, name in self.app.report_cache), {'report.html', 'report.md', 'result.json'})
        self.assert_only_bound_task_stopped()

    def test_real_summary_compact_receipt_survives_native_1024_character_preview(self):
        self.freeze_business_actions()
        prepared_record = self.records[1]
        packet = json.loads(prepared_record['output'])
        self.assertEqual(next(iter(packet)), 'receipt')
        for child in packet['receipt']['subactions']:
            self.assertEqual(set(child), {'ok', 'action', 'action_sha256'})
        compact = json.dumps(packet, ensure_ascii=False, separators=(',', ':'))
        first_receipt = '{"receipt":' + json.dumps(packet['receipt'], ensure_ascii=False, separators=(',', ':'))
        self.assertLess(len(first_receipt), 1000)
        self.assertGreater(len(compact), 1024)
        # Apply the observed preview limit to the actual production response,
        # rather than constructing an artificially complete receipt by hand.
        prepared_record['output'] = ('Tool result too large. Saved to /large_tool_results/fixture\n'
                                     'Here is a preview:\n     1\t' + compact[:1024])
        with self.assertRaises(json.JSONDecodeError):
            json.loads(compact[:1024])
        job = self.run_worker()
        self.assertEqual(job['state'], 'completed')
        final = self.app.workflow.get(self.runid, self.token)
        self.assertEqual(final['result']['provenance']['native_agent']['tool_action_sha'],
                         self.app.workflow.verification_contract(self.runid, self.token)['actions'])
        self.assert_only_bound_task_stopped()

    def test_summary_column_rows_preserve_all_history_delivery_and_month_dimension_values(self):
        prepared = self.app.workflow.prepare(self.runid, self.token, self.hashes)
        summary = native_summary(prepared)['facts']
        original = prepared['facts']
        for compact, column_key, row_key, expected in (
                (summary['history'], 'monthly_columns', 'monthly', original['history']['monthly']),
                (summary['analytics']['delivery'], 'monthly_columns', 'monthly',
                 original['analytics']['delivery']['monthly']),
                (summary['report_dimensions'], 'by_month_columns', 'by_month',
                 original['report_dimensions']['by_month'])):
            with self.subTest(table=row_key, columns=compact[column_key]):
                columns, rows = compact[column_key], compact[row_key]
                self.assertTrue(rows)
                self.assertEqual(len(columns), len(set(columns)))
                self.assertTrue(all(len(row) == len(columns) for row in rows))
                self.assertEqual([dict(zip(columns, row)) for row in rows], expected)

    def test_authorization_gate_failure_stops_and_never_generates_report(self):
        self.freeze_business_actions()
        with patch.object(self.app.native, 'verify', side_effect=NativeBridgeError('unauthorized', 403)), \
                patch.object(self.app.workflow, 'verify', wraps=self.app.workflow.verify) as publish:
            job = self.run_worker()
            publish.assert_not_called()
        self.assertEqual(job['state'], 'failed')
        self.assertTrue(job['native_stop_confirmed'])
        self.assert_only_bound_task_stopped()
        self.assert_no_report()

    def test_missing_receipts_retry_only_until_absolute_deadline(self):
        self.freeze_business_actions()
        self.records.pop()  # No authoritative finalize tool output.
        with patch('completion.time') as clock, \
                patch.object(self.app.workflow, 'verify', wraps=self.app.workflow.verify) as publish:
            clock.monotonic.side_effect = [0, 0, 29]
            job = self.run_worker()
            publish.assert_not_called()
            clock.sleep.assert_called_once_with(.25)
        self.assertEqual(job['state'], 'timed_out')
        self.assertEqual(self.app.workflow.get(self.runid, self.token)['state'], 'timed_out')
        self.assert_only_bound_task_stopped()
        self.assert_no_report()

    def test_already_spent_budget_never_verifies_or_publishes(self):
        self.freeze_business_actions()
        self.app.workflow.runs[self.runid]['created_monotonic'] = time.monotonic() - 31
        with patch.object(self.app.native, 'verify') as verify:
            job = self.run_worker()
            verify.assert_not_called()
        self.assertEqual(job['state'], 'timed_out')
        self.assert_only_bound_task_stopped()
        self.assert_no_report()

    def test_native_evidence_arriving_after_deadline_cannot_release_report(self):
        self.freeze_business_actions()
        original = self.app.native.verify
        with patch('completion.time') as clock:
            clock.monotonic.return_value = 0
            def late_evidence(*args, **kwargs):
                result = original(*args, **kwargs)
                clock.monotonic.return_value = 31
                return result
            with patch.object(self.app.native, 'verify', side_effect=late_evidence), \
                    patch.object(self.app.workflow, 'verify', wraps=self.app.workflow.verify) as publish:
                job = self.run_worker()
                publish.assert_not_called()
        self.assertEqual(job['state'], 'timed_out')
        self.assert_only_bound_task_stopped()
        self.assert_no_report()

    def test_report_render_crossing_deadline_never_publishes_staged_files(self):
        import workflow as workflow_module
        self.freeze_business_actions()
        original_render = workflow_module.save_report
        clock = Mock()
        clock.monotonic.return_value = 0
        clock.time.return_value = time.time()
        self.app.workflow.runs[self.runid]['created_monotonic'] = 0
        def late_render(*args, **kwargs):
            blobs = original_render(*args, **kwargs)
            self.assertEqual(set(blobs), {'report.html', 'report.md', 'result.json'})
            self.assertFalse((self.app.runtime / 'reports').exists())
            # Rendering finished, but all output is still private staging data.
            clock.monotonic.return_value = 31
            return blobs
        with patch('completion.time', clock), patch('workflow.time', clock), \
                patch('workflow.save_report', side_effect=late_render) as render, \
                patch.object(self.app.workflow, 'verify', wraps=self.app.workflow.verify) as publish:
            job = self.run_worker()
            render.assert_called_once()
            self.assertEqual(publish.call_args.kwargs['deadline'], 28)
        self.assertIn(job['state'], ('failed', 'timed_out'))
        self.assertEqual(self.app.workflow.get(self.runid, self.token)['state'], 'timed_out')
        self.assertEqual(list(self.app.runtime.glob('.pending-report-*')), [])
        self.assert_only_bound_task_stopped()
        self.assert_no_report()

    def test_stage_failure_stops_without_attempting_native_verification(self):
        self.app.gateway.fail = True
        with self.assertRaises(WorkflowError):
            self.app.workflow.prepare(self.runid, self.token, self.hashes)
        with patch.object(self.app.native, 'verify') as verify:
            job = self.run_worker()
            verify.assert_not_called()
        self.assertEqual(job['state'], 'failed')
        self.assert_only_bound_task_stopped()
        self.assert_no_report()

    def test_worker_initial_capability_failure_still_stops_bound_task(self):
        with patch.object(self.app.workflow, 'get', side_effect=WorkflowError('capability expired', 410)):
            job = self.run_worker()
        self.assertEqual(job['state'], 'failed')
        self.assert_only_bound_task_stopped()
        self.assert_no_report()


if __name__ == '__main__':
    unittest.main()
