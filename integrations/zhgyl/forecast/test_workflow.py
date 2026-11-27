"""Local workflow protocol tests. Native evidence fixtures are simulated assertions.

They test the server-side gate contract, never prove platform/LLM execution.
"""
import copy
import json
import stat
import tempfile
import unittest
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from workflow import Workflow, WorkflowError
from adapters import (MockHistoryAdapter, HttpHistoryAdapter, HistoryAdapterError,
                      history_adapter_from_env, normalize_history)
from engine import GatewayError
from simulated_services import forecast_response
from store import digest

HERE = Path(__file__).resolve().parent


class FakeStore:
    def __init__(self):
        self.source = json.loads((HERE / 'skill/procurement-forecast-fast/assets/orders.json').read_text())
        self.source['batch'] = {'month': '2026-11', 'version': 'TEST-ONLY-1',
                                'dataset_sha': digest(self.source['records']),
                                'included_order_ids': [r['order_id'] for r in self.source['records']]}

    def snapshot(self):
        return copy.deepcopy(self.source)


class FakeGateway:
    def __init__(self, store):
        self.store = store
        self.calls = []
        self.fail = False
        self.tamper = False
        self.rollover = False

    def predict(self, spec, customer, start, months, request_id):
        self.calls.append((spec, customer, start, months))
        if self.fail:
            raise GatewayError('测试服务故障')
        value = forecast_response(spec, customer, start, months, self.store.source['batch'])
        if self.tamper and isinstance(value, dict):
            value['monthly'][0]['amount'] += 1
        if self.rollover:
            self.store.source['batch']['dataset_sha'] = 'rolled-over'
        return value

    def explain(self, *args):
        raise AssertionError('Workflow must never call explanation HTTP')


class FakeApp:
    def __init__(self, runtime):
        self.runtime = Path(runtime)
        self.store = FakeStore()
        self.gateway = FakeGateway(self.store)
        self.history_adapter = MockHistoryAdapter()
        self.forecast_is_external = False
        self.report_cache = {}
        self.public_prefix = ''


class WorkflowProtocol(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = FakeApp(self.temp.name)
        self.workflow = Workflow(self.app)
        self.created = self.workflow.create({'spec': '189A1002-1', 'months': 3})
        self.runid, self.token = self.created['run_id'], self.created['token']
        self.hashes = self.workflow._hashes()

    def tearDown(self):
        self.temp.cleanup()

    def act(self, name, payload=None):
        return self.workflow.action(self.runid, self.token, name, {**self.hashes, **(payload or {})})

    def history(self):
        self.act('forecast')
        return self.act('history')

    def explanation(self, history):
        return {'headline': '测试解释', 'body': '仅测试解释验证器，并不表示调用真实模型。',
                'factors': [{'title': '样本', 'value': str(history['facts']['history']['summary']['record_count']), 'detail': '测试范围事实'}],
                'limitations': ['模拟订单与预测，不证明业务效果。'],
                'influences': [{'title': '交付', 'detail': '使用完成交付统计。', 'evidence_refs': ['STAT-DELIVERY']}],
                'suggestions': [{'spec': t['spec'], 'customer': t['customer'], 'reason': '按模型原值复核。',
                                 'evidence_refs': t['evidence_refs']} for t in history['suggestion_targets']]}

    def finalize(self):
        history = self.history()
        payload = {'facts_ref': history['facts_ref'], 'explanation': self.explanation(history)}
        return history, payload, self.act('finalize', payload)

    def simulated_verification_evidence(self):
        return {'chat_id': 'TEST-SIMULATED-NOT-NATIVE', 'session_version_id': 'fixture-v1',
                'model': 'test-fixture', 'tool_action_sha': self.workflow.verification_contract(self.runid, self.token)['actions']}

    def test_create_freezes_scope_without_model_call(self):
        self.assertEqual(self.app.gateway.calls, [])
        self.assertEqual(self.created['scope']['months'], 3)
        self.assertIsNone(self.workflow.get(self.runid, self.token)['result'])
        other = self.workflow.create({'query': '189A1002-1 从2027年起三个月 演示客户乙', 'spec': 'all'})
        self.assertEqual(other['scope'], {'specs': ['189A1002-1'], 'customer': '演示客户乙', 'start_month': '2027-01', 'months': 3})
        with self.assertRaises(WorkflowError):
            self.workflow.create({'query': '189A1002-1 和186A3107-751'})

    def test_capability_expiry_and_no_token_audit(self):
        with self.assertRaises(WorkflowError) as invalid:
            self.workflow.get(self.runid, 'wrong')
        self.assertEqual(invalid.exception.status_code, 403)
        with patch('workflow.time.time', return_value=self.workflow.runs[self.runid]['expires_at'] + 1):
            with self.assertRaises(WorkflowError) as expired:
                self.workflow.get(self.runid, self.token)
        self.assertEqual(expired.exception.status, 410)
        audit = self.workflow.audit_path.read_text()
        self.assertNotIn(self.token, audit)
        self.assertEqual(stat.S_IMODE(self.workflow.audit_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.app.runtime.stat().st_mode), 0o700)

    def test_order_hash_scope_and_snapshot_guards(self):
        with self.assertRaises(WorkflowError): self.act('history')
        with self.assertRaises(WorkflowError): self.act('forecast', {'months': 8})
        with self.assertRaises(WorkflowError): self.act('forecast', {'skill_sha256': 'forged'})
        self.assertEqual(self.app.gateway.calls, [])
        self.workflow.runs[self.runid]['source']['cutoff'] = '2020-01-01'
        with self.assertRaises(WorkflowError): self.act('forecast')

    def test_forecast_independent_idempotent_and_gateway_failure(self):
        first = self.act('forecast'); second = self.act('forecast')
        self.assertEqual(first, second); self.assertEqual(len(self.app.gateway.calls), 1)
        self.assertFalse((self.app.runtime / 'reports').exists())
        other = self.workflow.create({'spec': '189A1002-1'})
        self.app.gateway.fail = True
        with self.assertRaises(WorkflowError) as error:
            self.workflow.action(other['run_id'], other['token'], 'forecast', self.hashes)
        self.assertEqual(error.exception.status, 502)
        self.assertEqual(self.workflow.get(other['run_id'], other['token'])['state'], 'stage_failed')

    def test_slow_forecast_does_not_block_status_or_other_runs(self):
        entered, release = threading.Event(), threading.Event()
        original = self.app.gateway.predict
        def slow(*args):
            if args[-1] == self.runid:
                entered.set()
                if not release.wait(3): raise AssertionError('test did not release HTTP')
            return original(*args)
        self.app.gateway.predict = slow
        with ThreadPoolExecutor(max_workers=4) as pool:
            pending = pool.submit(self.act, 'forecast')
            try:
                self.assertTrue(entered.wait(1))
                status = pool.submit(self.workflow.get, self.runid, self.token).result(1)
                self.assertEqual(status['stage'], 'forecast')
                self.assertIsNone(status['result'])
                self.assertGreaterEqual(status['elapsed_seconds'], 0)
                other = pool.submit(self.workflow.create, {'spec': '189A1002-1'}).result(1)
                result = pool.submit(self.workflow.action, other['run_id'], other['token'],
                                     'forecast', self.hashes).result(1)
                self.assertEqual(result['state'], 'forecast_completed')
            finally:
                release.set()
            self.assertEqual(pending.result(1)['state'], 'forecast_completed')

    def test_concurrent_prepare_and_original_actions_execute_once(self):
        entered, release = threading.Event(), threading.Event()
        original = self.app.gateway.predict
        def slow(*args):
            entered.set()
            if not release.wait(3): raise AssertionError('test did not release HTTP')
            return original(*args)
        self.app.gateway.predict = slow
        with patch.object(self.app.history_adapter, 'read', wraps=self.app.history_adapter.read) as read:
            with ThreadPoolExecutor(max_workers=4) as pool:
                first = pool.submit(self.workflow.prepare, self.runid, self.token, self.hashes)
                try:
                    self.assertTrue(entered.wait(1))
                    duplicate = pool.submit(self.act, 'prepare')
                    forecast = pool.submit(self.act, 'forecast')
                    history = pool.submit(self.act, 'history')
                finally:
                    release.set()
                prepared = first.result(2)
                self.assertEqual(prepared, duplicate.result(2))
                self.assertEqual(prepared['subactions'], [forecast.result(2), history.result(2)])
            self.assertEqual(read.call_count, 1)
        self.assertEqual(len(self.app.gateway.calls), 1)
        self.assertEqual(set(self.workflow.runs[self.runid]['successes']), {'forecast', 'history'})
        self.assertEqual(set(self.workflow.verification_contract(self.runid, self.token)['actions']),
                         {'forecast', 'history'})
        audit = [json.loads(line)['action'] for line in self.workflow.audit_path.read_text().splitlines()]
        self.assertEqual(audit.count('forecast'), 1)
        self.assertEqual(audit.count('history'), 1)

    def test_prepare_preserves_api_zero_receipts_and_three_action_verification(self):
        other = self.workflow.create({'spec': 'BACB30YP8K9', 'months': 2})
        prepared = self.workflow.prepare(other['run_id'], other['token'], self.hashes)
        self.assertEqual(prepared['action'], 'prepare')
        self.assertIsNone(prepared['subactions'][0]['predictions']['BACB30YP8K9'])
        self.assertEqual(prepared['facts']['status'], 'unpredictable')
        self.assertIn('数字0', prepared['facts']['items'][0]['reason'])
        self.assertEqual(len(prepared['facts']['report_dimensions']['by_month']), 2)
        for receipt in prepared['subactions']:
            self.assertEqual(receipt, self.workflow.action(other['run_id'], other['token'],
                                                           receipt['action'], self.hashes))
            self.assertEqual(receipt['action_sha256'], digest(self.hashes))
        self.workflow.action(other['run_id'], other['token'], 'finalize',
                             {**self.hashes, 'explanation': self.explanation(prepared)})
        actions = self.workflow.verification_contract(other['run_id'], other['token'])['actions']
        self.assertEqual(set(actions), {'forecast', 'history', 'finalize'})
        # Receipt copies cannot corrupt the cached proof or frozen facts.
        prepared['subactions'][0]['action_sha256'] = 'forged'
        self.assertEqual(self.workflow.prepare(other['run_id'], other['token'], self.hashes)
                         ['subactions'][0]['action_sha256'], actions['forecast'])
        with self.assertRaises(WorkflowError):
            self.workflow.prepare(other['run_id'], other['token'], {**self.hashes, 'months': 8})

    def test_prepare_errors_preserve_stage_and_retry_only_missing_work(self):
        self.app.gateway.fail = True
        with self.assertRaises(WorkflowError) as failure:
            self.act('prepare')
        self.assertEqual(failure.exception.status, 502)
        self.assertEqual(self.workflow.get(self.runid, self.token)['error']['stage'], 'forecast')
        self.assertEqual(self.workflow.runs[self.runid]['successes'], {})
        self.app.gateway.fail = False
        with patch.object(self.app.history_adapter, 'read', side_effect=HistoryAdapterError('history down')):
            with self.assertRaises(WorkflowError): self.act('prepare')
        self.assertEqual(self.workflow.get(self.runid, self.token)['error']['stage'], 'history')
        self.assertEqual(set(self.workflow.runs[self.runid]['successes']), {'forecast'})
        calls = len(self.app.gateway.calls)
        prepared = self.act('prepare')
        self.assertEqual(prepared['state'], 'history_completed')
        self.assertEqual(len(self.app.gateway.calls), calls)
        self.assertFalse((self.app.runtime / 'reports').exists())

    def test_expire_during_http_is_immediate_terminal_and_idempotent(self):
        entered, release = threading.Event(), threading.Event()
        original = self.app.gateway.predict
        def slow(*args):
            entered.set()
            if not release.wait(3): raise AssertionError('test did not release HTTP')
            return original(*args)
        self.app.gateway.predict = slow
        with ThreadPoolExecutor(max_workers=3) as pool:
            pending = pool.submit(self.act, 'prepare')
            try:
                self.assertTrue(entered.wait(1))
                expired = pool.submit(self.workflow.expire, self.runid, self.token, '30秒超时').result(1)
                self.assertEqual(expired['state'], 'timed_out')
                self.assertIsNone(expired['result'])
                duplicate = self.workflow.expire(self.runid, self.token, '重复超时')
                self.assertEqual(duplicate['error'], expired['error'])
            finally:
                release.set()
            with self.assertRaises(WorkflowError) as failure: pending.result(1)
        self.assertEqual(failure.exception.status, 408)
        self.assertEqual(self.workflow.runs[self.runid]['successes'], {})
        self.assertEqual(self.workflow.runs[self.runid]['predictions'], {})
        self.assertEqual(self.workflow.get(self.runid, self.token)['state'], 'timed_out')
        for action in ('forecast', 'history', 'prepare', 'finalize'):
            with self.assertRaises(WorkflowError) as stopped: self.act(action)
            self.assertEqual(stopped.exception.status, 408)
        with self.assertRaises(WorkflowError): self.workflow.verify(self.runid, self.token, {})
        self.assertFalse((self.app.runtime / 'reports').exists())

    def test_expired_run_rejects_new_actions_before_http_finishes(self):
        entered, release = threading.Event(), threading.Event()
        original = self.app.history_adapter.read
        def slow(*args):
            entered.set()
            if not release.wait(3): raise AssertionError('test did not release history')
            return original(*args)
        self.act('forecast')
        with patch.object(self.app.history_adapter, 'read', side_effect=slow):
            with ThreadPoolExecutor(max_workers=3) as pool:
                pending = pool.submit(self.act, 'history')
                try:
                    self.assertTrue(entered.wait(1))
                    self.workflow.expire(self.runid, self.token, 'history timeout')
                    rejected = pool.submit(self.act, 'forecast')
                    with self.assertRaises(WorkflowError) as stopped: rejected.result(1)
                    self.assertEqual(stopped.exception.status, 408)
                finally:
                    release.set()
                with self.assertRaises(WorkflowError): pending.result(1)
        self.assertEqual(set(self.workflow.runs[self.runid]['successes']), {'forecast'})
        self.assertEqual(self.workflow.get(self.runid, self.token)['state'], 'timed_out')

    def test_expire_during_report_generation_never_releases_results(self):
        self.finalize()
        evidence = self.simulated_verification_evidence()
        entered, release = threading.Event(), threading.Event()
        original = __import__('workflow').save_report
        def slow(*args):
            entered.set()
            if not release.wait(3): raise AssertionError('test did not release report generation')
            return original(*args)
        with patch('workflow.save_report', side_effect=slow):
            with ThreadPoolExecutor(max_workers=2) as pool:
                pending = pool.submit(self.workflow.verify, self.runid, self.token, evidence)
                try:
                    self.assertTrue(entered.wait(1))
                    expired = pool.submit(self.workflow.expire, self.runid, self.token, 'report timeout').result(1)
                    self.assertEqual(expired['state'], 'timed_out')
                finally:
                    release.set()
                with self.assertRaises(WorkflowError): pending.result(1)
        self.assertEqual(self.app.report_cache, {})
        self.assertFalse((self.app.runtime / 'reports' / self.runid).exists())
        self.assertEqual(list(self.app.runtime.glob('.pending-report-*')), [])
        self.assertIsNone(self.workflow.get(self.runid, self.token)['result'])
        self.assertEqual(self.workflow.get(self.runid, self.token)['state'], 'timed_out')

    def test_concurrent_verify_is_idempotent_and_completed_cannot_expire(self):
        self.finalize()
        evidence = self.simulated_verification_evidence()
        with patch('workflow.save_report', wraps=__import__('workflow').save_report) as save:
            with ThreadPoolExecutor(max_workers=2) as pool:
                pending = [pool.submit(self.workflow.verify, self.runid, self.token, evidence) for _ in range(2)]
                results = [item.result(2) for item in pending]
            self.assertEqual(save.call_count, 1)
        self.assertEqual(results[0]['result'], results[1]['result'])
        final = self.workflow.expire(self.runid, self.token, 'late timeout')
        self.assertEqual(final['state'], 'completed')
        self.assertIsNotNone(final['result'])

    def test_prediction_tampering_and_rollover_are_errors(self):
        self.app.gateway.tamper = True
        with self.assertRaises(WorkflowError): self.act('forecast')
        self.assertEqual(self.workflow.runs[self.runid]['predictions'], {})
        self.app.gateway.tamper = False; self.app.gateway.rollover = True
        with self.assertRaises(WorkflowError): self.act('forecast')
        self.assertEqual(self.workflow.runs[self.runid]['predictions'], {})

    def test_history_matches_aggregates_and_zero_is_not_missing(self):
        history = self.history(); facts = history['facts']
        rows = facts['items'][0]['forecast']['monthly']
        self.assertEqual(facts['forecast']['summary']['quantity'], sum(r['quantity'] for r in rows))
        self.assertEqual(len(history['suggestion_targets']), 2)
        self.assertEqual(facts['provenance']['history_mode'], 'mock_sql')
        self.assertTrue(facts['provenance']['history_is_synthetic'])
        self.assertTrue(facts['provenance']['history_batch_aligned'])
        self.assertIn('STAT-QUANTITY', history['evidence_refs'])
        other = self.workflow.create({'spec': 'ZERO-PRED-001', 'months': 2})
        self.workflow.action(other['run_id'], other['token'], 'forecast', self.hashes)
        zero = self.workflow.action(other['run_id'], other['token'], 'history', self.hashes)['facts']
        self.assertEqual(zero['status'], 'predicted')
        self.assertEqual(zero['forecast']['summary']['quantity'], 0)

    def test_refusal_is_not_assumed_sparse_and_no_history_has_no_suggestions(self):
        for spec, state in [('BACB30YP8K9', 'unpredictable'), ('NEW-PART-001', 'no_history')]:
            created = self.workflow.create({'spec': spec})
            self.workflow.action(created['run_id'], created['token'], 'forecast', self.hashes)
            history = self.workflow.action(created['run_id'], created['token'], 'history', self.hashes)
            self.assertEqual(history['facts']['status'], state)
            self.assertNotIn('缺少足够重复历史', history['facts']['items'][0]['reason'])
            self.assertEqual(history['suggestion_targets'], [])
            payload = {**self.hashes, 'explanation': self.explanation(history)}
            self.workflow.action(created['run_id'], created['token'], 'finalize', payload)

    def test_invalid_explanation_retains_facts_and_never_publishes(self):
        history = self.history(); explanation = self.explanation(history)
        explanation['influences'][0]['evidence_refs'] = []
        with self.assertRaises(WorkflowError): self.act('finalize', {'explanation': explanation})
        run = self.workflow.runs[self.runid]
        self.assertEqual(run['facts_ref'], history['facts_ref'])
        self.assertIsNotNone(run['result']['forecast'])
        self.assertIsNone(run['result']['explanation'])
        self.assertFalse((self.app.runtime / 'reports').exists())
        explanation = self.explanation(history); explanation['influences'][0]['evidence_refs'] = ['invented']
        with self.assertRaises(WorkflowError): self.act('finalize', {'explanation': explanation})

    def test_missing_price_cannot_be_asserted_as_zero_change(self):
        run=self.workflow.create({'spec':'BACB30YP8K9'})
        self.workflow.action(run['run_id'],run['token'],'forecast',self.hashes)
        history=self.workflow.action(run['run_id'],run['token'],'history',self.hashes)
        explanation=self.explanation(history)
        explanation['body']='数量与价格环比均为0且change_pct为null。'
        with self.assertRaisesRegex(WorkflowError,'价格趋势缺少观测值'):
            self.workflow.action(run['run_id'],run['token'],'finalize',{**self.hashes,'explanation':explanation})
        self.assertFalse((self.app.runtime/'reports').exists())
        explanation['body']='历史数量为0；价格环比不能视为0，缺少单价观测无法计算。'
        self.assertEqual(self.workflow.action(run['run_id'],run['token'],'finalize',{**self.hashes,'explanation':explanation})['state'],'awaiting_native_verification')

    def test_suggestion_coverage_numbers_scope_and_relevance(self):
        history = self.history()
        variations = []
        missing = self.explanation(history); missing['suggestions'].pop(); variations.append(missing)
        duplicate = self.explanation(history); duplicate['suggestions'].append(copy.deepcopy(duplicate['suggestions'][0])); variations.append(duplicate)
        numeric = self.explanation(history); numeric['suggestions'][0]['quantity'] = -1; variations.append(numeric)
        price = self.explanation(history); price['suggestions'][0]['unit_price'] = 1; variations.append(price)
        wrong = self.explanation(history); wrong['suggestions'][0]['evidence_refs'] = wrong['suggestions'][1]['evidence_refs']; variations.append(wrong)
        for explanation in variations:
            with self.subTest(explanation=explanation):
                with self.assertRaises(WorkflowError): self.act('finalize', {'explanation': explanation})
        self.act('finalize', {'explanation': self.explanation(history)})

    def test_finalize_only_freezes_native_verify_releases_report(self):
        history, payload, receipt = self.finalize()
        self.assertEqual(receipt['state'], 'awaiting_native_verification')
        self.assertEqual(self.act('finalize', payload), receipt)
        self.assertIsNone(self.workflow.get(self.runid, self.token)['result'])
        self.assertFalse((self.app.runtime / 'reports').exists())
        evidence = self.simulated_verification_evidence(); evidence['tool_action_sha'] = {'forecast': 'forged'}
        with self.assertRaises(WorkflowError): self.workflow.verify(self.runid, self.token, evidence)
        final = self.workflow.verify(self.runid, self.token, self.simulated_verification_evidence())
        self.assertEqual(final['state'], 'completed')
        result = final['result']; self.assertIsNotNone(result['reports'])
        self.assertEqual(result['explanation']['analysis_model'], 'test-fixture')
        self.assertEqual(result['report_dimensions']['suggestions'][0]['quantity'], history['suggestion_targets'][0]['quantity'])
        self.assertEqual(result['report_dimensions']['suggestions'][0]['amount'], history['suggestion_targets'][0]['amount'])
        self.assertEqual(len(self.app.report_cache), 3)
        for filename in ('report.html', 'report.md', 'result.json'):
            self.assertEqual(stat.S_IMODE((self.app.runtime / 'reports' / self.runid / filename).stat().st_mode), 0o600)

    def test_different_success_payload_rejected(self):
        history, payload, receipt = self.finalize()
        payload['explanation']['body'] = 'Changed after freeze'
        with self.assertRaises(WorkflowError): self.act('finalize', payload)
        self.assertEqual(self.workflow.runs[self.runid]['result']['explanation']['body'], '仅测试解释验证器，并不表示调用真实模型。')
        self.assertEqual(self.workflow.get(self.runid, self.token)['state'], 'awaiting_native_verification')
        self.assertEqual(self.workflow.verify(self.runid, self.token, self.simulated_verification_evidence())['state'], 'completed')
        with self.assertRaises(WorkflowError): self.act('finalize', payload)
        self.assertEqual(self.workflow.get(self.runid, self.token)['state'], 'completed')


    def test_external_forecast_records_separate_batch_and_preserves_warning(self):
        original = self.app.gateway.predict
        def external(*args):
            payload = original(*args)
            payload['dataset_sha'] = 'external-forecast-snapshot'
            for row in payload['monthly']: row['is_synthetic'] = False
            return payload
        self.app.gateway.predict = external
        with self.assertRaises(WorkflowError): self.act('forecast')
        self.app.forecast_is_external = True
        history = self.history()
        provenance = history['facts']['provenance']
        self.assertEqual(provenance['forecast_mode'], 'external_http')
        self.assertEqual(provenance['forecast_dataset_sha'], 'external-forecast-snapshot')
        self.assertFalse(provenance['forecast_batch_aligned'])
        self.assertFalse(provenance['forecast_is_synthetic'])
        self.assertTrue(provenance['history_batch_aligned'])
        self.act('finalize', {'explanation': self.explanation(history)})
        final = self.workflow.verify(self.runid, self.token, self.simulated_verification_evidence())['result']
        self.assertTrue(any('独立数据快照' in x for x in final['explanation']['limitations']))


class HistoryHttpContract(unittest.TestCase):
    def setUp(self):
        self.source = FakeStore().snapshot()
        self.specs = ['189A1002-1']; self.customer = '演示客户甲'; self.request_id = 'test-http-history'
        self.received = None; self.change = lambda payload: payload; self.http_status = 200
        outer = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                outer.received = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                response = outer.change(outer.response())
                blob = json.dumps(response, ensure_ascii=False).encode()
                self.send_response(outer.http_status); self.send_header('Content-Length', str(len(blob))); self.end_headers(); self.wfile.write(blob)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.adapter = HttpHistoryAdapter('http://127.0.0.1:' + str(self.server.server_port) + '/nl2sql')

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(1)

    def response(self):
        history = MockHistoryAdapter().read(self.source, self.specs, self.customer, self.request_id)
        return {**history, 'ok': True, 'request_id': self.request_id,
                'scope': {'specs': self.specs, 'customer': self.customer, 'window': self.source['window']},
                'dataset_sha': 'external-history-snapshot',
                'summary': {'record_count': 999999}, 'monthly': [],
                'source': {'mode': 'nl2sql', 'query_id': 'QUERY-TEST', 'is_synthetic': False, 'label': 'HTTP test fixture'}}

    def read(self):
        return self.adapter.read(self.source, self.specs, self.customer, self.request_id)

    def test_config_selects_adapter_without_skill_database_credentials(self):
        with patch.dict(os.environ, {'FORECAST_HISTORY_URL': ''}): self.assertIsInstance(history_adapter_from_env(), MockHistoryAdapter)
        with patch.dict(os.environ, {'FORECAST_HISTORY_URL': self.adapter.url}): self.assertIsInstance(history_adapter_from_env(), HttpHistoryAdapter)
        with self.assertRaises(ValueError): HttpHistoryAdapter('https://user:password@example.com/history')

    def test_http_roundtrip_recomputes_aggregates_and_separates_snapshot(self):
        history = self.read()
        self.assertEqual(self.received, {'request_id': self.request_id,
            'scope': {'specs': self.specs, 'customer': self.customer, 'window': self.source['window']},
            'snapshot': {'dataset_sha': self.source['batch']['dataset_sha'], 'version': 'TEST-ONLY-1', 'cutoff': self.source['cutoff']}})
        self.assertEqual(history['summary']['record_count'], len(history['records']))
        self.assertGreater(len(history['monthly']), 0)
        self.assertEqual(history['summary']['total_quantity'], sum(r['quantity'] for r in history['records']))
        self.assertEqual(history['provenance']['history_mode'], 'nl2sql')
        self.assertFalse(history['provenance']['is_synthetic'])
        self.assertEqual(history['provenance']['history_dataset_sha'], 'external-history-snapshot')
        self.assertFalse(history['provenance']['history_batch_aligned'])

    def test_http_error_never_becomes_empty_history(self):
        self.http_status = 503
        with self.assertRaises(HistoryAdapterError): self.read()

    def test_partial_foreign_or_duplicate_rows_rejected(self):
        changes = [lambda p: {**p, 'complete': False},
                   lambda p: {**p, 'records': [{**p['records'][0], 'customer': '演示客户乙'}]},
                   lambda p: {**p, 'records': [p['records'][0], p['records'][0]]},
                   lambda p: {**p, 'records': [{**p['records'][0], 'spec': 'FOREIGN-PART'}]}]
        for change in changes:
            self.change = change
            with self.subTest(change=change):
                with self.assertRaises(HistoryAdapterError): self.read()

    def test_units_dates_numbers_and_origin_contract_rejected(self):
        mutations = [('unit', '箱'), ('currency', 'USD'), ('date', '2030-01-01'),
                     ('quantity', -1), ('unit_price', float('nan')), ('amount', 1),
                     ('actual_delivery_date', '2000-01-01')]
        for key, value in mutations:
            payload = self.response(); payload['records'][0][key] = value
            with self.subTest(field=key):
                with self.assertRaises(HistoryAdapterError):
                    normalize_history(payload, self.source, self.specs, self.customer, self.request_id, 'nl2sql')
        for key, value in [('request_id', 'foreign-request'), ('window', {'start': '2020-01-01', 'end': '2020-12-31'}), ('dataset_sha', '')]:
            payload = self.response(); payload[key] = value
            with self.assertRaises(HistoryAdapterError): normalize_history(payload, self.source, self.specs, self.customer, self.request_id, 'nl2sql')
        payload = self.response(); del payload['source']['query_id']
        with self.assertRaises(HistoryAdapterError): normalize_history(payload, self.source, self.specs, self.customer, self.request_id, 'nl2sql')

    def test_workflow_uses_external_history_provenance_and_recomputed_records(self):
        with tempfile.TemporaryDirectory() as runtime:
            app = FakeApp(runtime); app.history_adapter = self.adapter
            workflow = Workflow(app); created = workflow.create({'spec': self.specs[0], 'customer': self.customer})
            self.request_id = created['run_id']
            hashes = workflow._hashes(); workflow.action(created['run_id'], created['token'], 'forecast', hashes)
            facts = workflow.action(created['run_id'], created['token'], 'history', hashes)['facts']
            self.assertEqual(facts['provenance']['history_mode'], 'nl2sql')
            self.assertFalse(facts['provenance']['history_batch_aligned'])
            self.assertFalse(facts['provenance']['history_is_synthetic'])
            self.assertEqual(facts['items'][0]['history']['summary'], facts['history']['summary'])
            self.assertTrue(facts['provenance']['data_warnings'])

    def test_history_failure_preserves_forecast_and_no_report(self):
        with tempfile.TemporaryDirectory() as runtime:
            app = FakeApp(runtime); app.history_adapter = self.adapter
            workflow = Workflow(app); created = workflow.create({'spec': '189A1002-1', 'customer': self.customer})
            hashes = workflow._hashes(); workflow.action(created['run_id'], created['token'], 'forecast', hashes)
            self.http_status = 503
            with self.assertRaises(WorkflowError): workflow.action(created['run_id'], created['token'], 'history', hashes)
            run = workflow.runs[created['run_id']]
            self.assertEqual(run['state'], 'stage_failed'); self.assertIn('189A1002-1', run['predictions'])
            self.assertFalse((Path(runtime) / 'reports').exists())


if __name__ == '__main__':
    unittest.main()
