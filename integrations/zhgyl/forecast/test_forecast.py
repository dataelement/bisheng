# coding: utf-8
"""HTTP integration with local mock data and explicitly simulated native proofs.

No test invokes a real platform model or proves native Skill/NL2SQL execution.
Monthly fixture/store regressions remain deterministic.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from server import App
from store import MonthlyStore, TZ, digest
from simulated_services import forecast_response
from native_bridge import NativeBridgeError

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / 'skill/procurement-forecast-fast/assets/orders.json'


class MonthlyDocument(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.environment = patch.dict(os.environ, {'FORECAST_API_BASE': '', 'FORECAST_HISTORY_URL': ''})
        cls.environment.start()
        cls.temp = tempfile.TemporaryDirectory()
        cls.app = App(('127.0.0.1', 0), runtime=cls.temp.name, auto_refresh=False,
                      clock=lambda: datetime(2026, 11, 23, 12, tzinfo=TZ))
        cls.app.ensure_month()  # Frozen deterministic November batch, no scheduler.
        cls.t = threading.Thread(target=cls.app.serve_forever, daemon=True); cls.t.start()
        cls.base = f'http://127.0.0.1:{cls.app.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown(); cls.app.server_close(); cls.t.join(1)
        cls.temp.cleanup(); cls.environment.stop()

    def request(self, path, body=None, headers=None):
        request = urllib.request.Request(self.base + path,
                    data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
                    headers={'Content-Type': 'application/json', **(headers or {})})
        return urllib.request.urlopen(request, timeout=6)

    def json(self, path, body=None, headers=None):
        with self.request(path, body, headers) as response:
            return json.load(response)

    def auth(self, run):
        return {'Authorization': 'Bearer ' + run['token']}

    def create(self, **params):
        return self.json('/api/runs', {'query': '', 'spec': '189A1002-1', 'customer': 'all',
                                     'start_month': '2026-12', 'months': 12, **params})

    def action(self, run, action, payload=None):
        return self.json('/api/runs/' + run['run_id'] + '/' + action,
                         {**self.app.workflow._hashes(), **(payload or {})}, self.auth(run))

    def stage_history(self, **params):
        run = self.create(**params)
        self.action(run, 'forecast')
        return run, self.action(run, 'history')

    def query(self, **params):
        return self.stage_history(**params)[1]['facts']

    def fixture_explanation(self, history):
        """Hand-authored test fixture; deliberately labels absence of real model."""
        count = history['facts']['history']['summary']['record_count']
        return {'headline': 'HTTP解释测试夹具', 'body': f'{count}笔记录；本解释由测试构造，未调用真实模型。',
                'factors': [{'title': '样本', 'value': str(count), 'detail': '完整冻结测试窗口'}],
                'limitations': ['模拟订单与预测；原生核验器使用测试替身，不证明真实平台执行。'],
                'influences': [{'title': '交付', 'detail': '引用确定性交付统计。', 'evidence_refs': ['STAT-DELIVERY']}],
                'suggestions': [{'spec': target['spec'], 'customer': target['customer'],
                                 'reason': '按本次模型原值与客户核对；仅为测试夹具。',
                                 'evidence_refs': target['evidence_refs']} for target in history['suggestion_targets']]}

    def finalize_fixture(self, run, history):
        return self.action(run, 'finalize', {'facts_ref': history['facts_ref'],
                                           'explanation': self.fixture_explanation(history)})

    def complete_fixture(self, **params):
        run, history = self.stage_history(**params)
        self.finalize_fixture(run, history)
        def simulated_native(cookie, chat_id, version, contract):
            self.assertEqual(set(contract['actions']), {'forecast', 'history', 'finalize'})
            self.assertEqual(chat_id, 'SIMULATED-HTTP-TEST')
            return {'chat_id': chat_id, 'session_version_id': version,
                    'model': '测试夹具（非真实模型调用）', 'status': 'completed',
                    'tool_action_sha': contract['actions']}
        with patch.object(self.app.native, 'verify', side_effect=simulated_native) as native:
            response = self.json('/api/runs/' + run['run_id'] + '/verify',
                                 {'chat_id': 'SIMULATED-HTTP-TEST', 'session_version_id': 'FIXTURE-V1'}, self.auth(run))
            native.assert_called_once()
        self.assertEqual(response['state'], 'completed')
        return response['result']

    def assert_http(self, code, path, body=None, headers=None):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request(path, body, headers)
        self.assertEqual(error.exception.code, code)
        error.exception.close()

    def test_run_creation_has_scope_without_analysis_or_forecast(self):
        with patch.object(self.app.gateway, 'predict', wraps=self.app.gateway.predict) as predict:
            run = self.create(months=3)
            predict.assert_not_called()
        self.assertEqual(run['scope']['months'], 3)
        state = self.json('/api/runs/' + run['run_id'], headers=self.auth(run))
        self.assertEqual(state['state'], 'created'); self.assertIsNone(state['result'])
        self.assertFalse((Path(self.temp.name) / 'reports' / run['run_id']).exists())

    def test_R01_explicit_scope_overrides_defaults(self):
        result = self.query(query='189A1002-1 从2027年起三个月 演示客户乙')
        self.assertEqual(result['scope'], {'specs': ['189A1002-1'], 'customer': '演示客户乙', 'start_month': '2027-01', 'months': 3})
        self.assertEqual(len(result['forecast']['monthly']), 3); self.assertEqual(result['period']['end'], '2027-03-31')
        self.assertTrue(all(row['customer'] == '演示客户乙' for row in result['history']['records']))

    def test_R01_unknown_customer_all_and_ambiguous_scope(self):
        result = self.query(query='新型号 ABC123 未来三个月')
        self.assertEqual(result['status'], 'no_history'); self.assertEqual(result['spec'], 'ABC123')
        self.assertEqual(self.create(query='189A1002-1 全部客户未来三个月', customer='演示客户甲')['scope']['customer'], 'all')
        self.assertEqual(self.create(query='189A1002-1 演示客户甲与演示客户乙未来三个月')['scope']['customer'], 'all')
        self.assert_http(422, '/api/runs', {'query': '预测189A1002-1和UNKNOWN-002'})

    def test_R02_R04_monthly_values_not_annual_division(self):
        result = self.query(); self.assertEqual(result['status'], 'predicted')
        self.assertEqual(len(result['forecast']['monthly']), 12)
        self.assertGreater(len({row['quantity'] for row in result['forecast']['monthly']}), 3)
        self.assertGreater(len({row['unit_price'] for row in result['forecast']['monthly']}), 3)
        rows = result['items'][0]['forecast']['monthly']; self.assertEqual(len(rows), 24)
        self.assertEqual(result['forecast']['summary']['quantity'], sum(row['quantity'] for row in rows))
        self.assertEqual(Decimal(str(result['forecast']['summary']['amount'])), sum(Decimal(str(row['amount'])) for row in rows))
        for row in rows:
            self.assertEqual(Decimal(str(row['amount'])), Decimal(str(row['quantity'])) * Decimal(str(row['unit_price'])))

    def test_R03_historical_quantity_price_and_null(self):
        history = self.query(spec='BACB30YP8K9')['history']
        self.assertEqual(history['summary']['record_count'], 2)
        self.assertEqual(sum(row['orders'] for row in history['monthly']), 2)
        self.assertTrue(any(row['quantity'] == 0 and row['unit_price'] is None for row in history['monthly']))
        self.assertEqual(history['summary']['total_quantity'], 104)

    def test_R05_delivery_uses_actual_completed_only(self):
        result = self.query(); records = result['history']['records']; delivery = result['analytics']['delivery']
        days = [(datetime.fromisoformat(row['actual_delivery_date']) - datetime.fromisoformat(row['date'])).days
                for row in records if row['actual_delivery_date']]
        self.assertEqual(delivery['completed_orders'], len(days)); self.assertEqual(delivery['open_orders'], 1)
        self.assertEqual(delivery['avg_days'], round(sum(days) / len(days), 1))
        self.assertTrue(all(row['lead_days'] is None for row in records if not row['actual_delivery_date']))

    def test_R06_customer_changes_filtered_and_recomputed(self):
        result = self.query(customer='演示客户甲'); changes = result['analytics']['customer_changes']
        self.assertEqual(len(changes), 1); self.assertEqual(changes[0]['customer'], '演示客户甲')
        records = result['history']['records']; months = [row['month'] for row in result['history']['monthly']]
        self.assertEqual(changes[0]['previous_quantity'], sum(row['quantity'] for row in records if months[-6] <= row['date'][:7] <= months[-4]))
        self.assertEqual(changes[0]['current_quantity'], sum(row['quantity'] for row in records if months[-3] <= row['date'][:7] <= months[-1]))

    def test_R07_history_exposes_facts_without_mock_explanation_call(self):
        run, history = self.stage_history(); result = history['facts']
        self.assertEqual({context['type'] for context in result['analytics']['context']}, {'current_order', 'project_plan', 'market'})
        self.assertIsNone(result['explanation']); self.assertIsNone(result['reports'])
        events = [json.loads(line) for line in (Path(self.temp.name) / 'events.jsonl').read_text().splitlines()]
        events = [event for event in events if event.get('request_id') == run['run_id']]
        self.assertEqual(sum(event['type'] == 'forecast_http' for event in events), 1)
        self.assertFalse(any(event['type'] == 'analysis_http' for event in events))
        self.assertEqual(result['provenance']['history_mode'], 'mock_sql')

    def test_R08_new_orders_in_history_model_input_and_hash(self):
        result = self.query(); self.assertEqual(result['batch']['dataset_rows'], 30); self.assertEqual(result['batch']['added_count'], 2)
        self.assertEqual(result['forecast']['dataset_sha'], result['provenance']['dataset_sha'])
        self.assertTrue({'SIM-NEW-001', 'SIM-NEW-002'} <= set(result['forecast']['input_order_ids']))
        self.assertTrue(any(row['order_id'] == 'SIM-NEW-001' for row in result['history']['records']))
        first = next(row for row in result['items'][0]['forecast']['monthly'] if row['month'] == '2026-12' and row['customer'] == '演示客户甲')
        self.assertEqual(first['quantity'], 74)
        self.assertEqual(result['provenance']['dataset_sha'], digest(self.app.store.snapshot()['records']))

    def test_R08_refresh_idempotent(self):
        first = self.json('/api/monthly-refresh', {}); second = self.json('/api/monthly-refresh', {})
        self.assertEqual(first, second); self.assertEqual(len({row['order_id'] for row in self.app.store.snapshot()['records']}), 30)

    def test_R09_new_model_waits_and_job_is_idempotent(self):
        result = self.query(spec='NEW-PART-001'); self.assertEqual(result['status'], 'no_history'); self.assertIsNone(result['forecast'])
        first = self.json('/api/recalculate', {'spec': 'NEW-PART-001'}); second = self.json('/api/recalculate', {'spec': 'NEW-PART-001'})
        self.assertEqual(first, second); self.assertEqual(first['job']['status'], 'waiting_for_data')

    def test_R10_refusal_retains_history_and_no_report_before_verify(self):
        run, history = self.stage_history(spec='BACB30YP8K9'); facts = history['facts']
        self.assertEqual(facts['status'], 'unpredictable'); self.assertIsNone(facts['forecast'])
        self.assertEqual(facts['history']['summary']['record_count'], 2)
        self.assertIn('API未提供具体原因', facts['items'][0]['reason'])
        self.finalize_fixture(run, history)
        state = self.json('/api/runs/' + run['run_id'], headers=self.auth(run))
        self.assertEqual(state['state'], 'awaiting_native_verification'); self.assertIsNone(state['result'])
        self.assert_http(404, '/api/reports/' + run['run_id'] + '/result.json')

    def test_R11_all_dimensions_and_null_exclusion(self):
        result = self.query(spec='all', months=3); dimensions = result['report_dimensions']
        self.assertEqual(result['status'], 'mixed'); self.assertEqual(len(dimensions['by_material']), 3)
        self.assertEqual(len(dimensions['by_customer']), 2); self.assertEqual(len(dimensions['by_month']), 3)
        refused = next(row for row in dimensions['by_material'] if row['spec'] == 'BACB30YP8K9')
        self.assertIsNone(refused['forecast_quantity'])
        self.assertEqual(sum(row['forecast_quantity'] or 0 for row in dimensions['by_customer']), result['forecast']['summary']['quantity'])
        self.assertEqual(dimensions['by_month'][0]['history_month'], '2025-12'); self.assertIn('BACB30YP8K9', dimensions['excluded_specs'])

    def test_R12_suggestions_and_reports_after_simulated_native_gate(self):
        result = self.complete_fixture(spec='all', months=3)
        self.assertIn('非真实模型调用', result['explanation']['analysis_model'])
        for suggestion in result['report_dimensions']['suggestions']:
            item = next(item for item in result['items'] if item['spec'] == suggestion['spec'])
            rows = [row for row in item['forecast']['monthly'] if row['customer'] == suggestion['customer']]
            self.assertEqual(suggestion['quantity'], sum(row['quantity'] for row in rows))
            self.assertEqual(Decimal(str(suggestion['amount'])), sum(Decimal(str(row['amount'])) for row in rows))
            self.assertTrue({row['prediction_id'] for row in rows} <= set(suggestion['evidence_refs']))
        self.assertEqual(self.json(result['reports']['json_url']), result)
        for key in ('html_url', 'markdown_url'):
            with self.request(result['reports'][key]) as response: text = response.read().decode()
            for needle in (result['request_id'], result['batch']['dataset_sha'], '2025-12', '物料维度', '客户维度', '时间维度', 'PLAN-001', 'MKT-001', 'SIM-NEW-001'):
                self.assertIn(needle, text)

    def test_R12_finalize_rejects_quantity_changes(self):
        run, history = self.stage_history(); explanation = self.fixture_explanation(history)
        explanation['suggestions'][0]['quantity'] = -1
        self.assert_http(422, '/api/runs/' + run['run_id'] + '/finalize',
                         {**self.app.workflow._hashes(), 'explanation': explanation}, self.auth(run))
        self.assertIsNotNone(self.app.workflow.runs[run['run_id']]['result']['forecast'])
        self.assert_http(404, '/api/reports/' + run['run_id'] + '/result.json')

    def test_R15_bias_zero_and_service_error_remain_distinct(self):
        result = self.query(spec='186A3107-751')
        self.assertTrue(any('回测偏差较大' in note for note in result['forecast']['quality_notes']))
        self.assertTrue(all(row['backtest_mape'] == .48 for row in result['items'][0]['forecast']['monthly']))
        result = self.query(spec='ZERO-PRED-001'); self.assertEqual(result['status'], 'predicted'); self.assertEqual(result['forecast']['summary']['quantity'], 0)
        run = self.create(spec='TEST-API-ERROR')
        self.assert_http(502, '/api/runs/' + run['run_id'] + '/forecast', self.app.workflow._hashes(), self.auth(run))
        state = self.json('/api/runs/' + run['run_id'], headers=self.auth(run))
        self.assertEqual(state['state'], 'stage_failed'); self.assertIsNone(state['result'])

    def test_cli_forecast_action_calls_run_scoped_http(self):
        run = self.create(query='预测189A1002-1未来三个月', customer='演示客户乙')
        command = [sys.executable, str(HERE / 'skill/procurement-forecast-fast/scripts/run.py'),
                   '--action', 'forecast', '--base-url', self.base, '--run-id', run['run_id'], '--token', run['token']]
        process = subprocess.run(command, cwd=self.temp.name, capture_output=True, text=True, timeout=7)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertNotIn(run['token'], process.stdout + process.stderr)
        receipt = json.loads(process.stdout)
        self.assertEqual(receipt['scope']['months'], 3); self.assertEqual(receipt['action'], 'forecast')
        self.assertEqual(receipt['state'], 'forecast_completed')

    def test_legacy_monolithic_and_explanation_routes_disabled(self):
        self.assert_http(410, '/api/analyze', {'spec': '189A1002-1'})
        self.assert_http(410, '/api/explanation', {'history': {}})

    def test_native_api_summary_preserves_full_report_facts(self):
        run=self.create()
        def invoke(action):
            return self.json('/api/skill-execute',{'request_json':json.dumps({'run_id':run['run_id'],'token':run['token'],'action':action})})
        forecast=invoke('forecast');history=invoke('history')
        self.assertEqual(next(iter(forecast)),'receipt')
        self.assertEqual(forecast['receipt']['action'],'forecast')
        self.assertLess(len(json.dumps(forecast,ensure_ascii=False)),1500)
        self.assertEqual(history['receipt']['action'],'history')
        self.assertNotIn(run['token'],json.dumps(history))
        self.assertEqual(len(history['facts']['forecast']['monthly']),12)
        stored=self.app.workflow.runs[run['run_id']]['result']
        self.assertEqual(len(stored['items'][0]['forecast']['monthly']),24)
        self.assertEqual(len(stored['history']['records']),19)
        self.assertIsNone(self.json('/api/runs/'+run['run_id'],headers=self.auth(run))['result'])

    def test_native_api_wrapper_rejects_scope_injection_and_bad_capability(self):
        run=self.create()
        def body(**extra):return {'request_json':json.dumps({'run_id':run['run_id'],'token':run['token'],'action':'forecast',**extra})}
        self.assert_http(400,'/api/skill-execute',body(spec='all'))
        self.assert_http(403,'/api/skill-execute',body(token='wrong'))
        self.assert_http(400,'/api/skill-execute',{'request_json':'not-json'})

    def test_authentication_hash_stage_and_verifier_guards(self):
        run = self.create(); path = '/api/runs/' + run['run_id']
        self.assert_http(403, path)
        self.assert_http(403, path + '/forecast', self.app.workflow._hashes())
        self.assert_http(409, path + '/forecast', {'skill_sha256': 'wrong', 'cli_sha256': 'wrong'}, self.auth(run))
        self.assert_http(409, path + '/history', self.app.workflow._hashes(), self.auth(run))
        self.action(run, 'forecast'); history = self.action(run, 'history'); self.finalize_fixture(run, history)
        with patch.object(self.app.native, 'verify', side_effect=NativeBridgeError('测试夹具：原生任务未完成')):
            self.assert_http(409, path + '/verify', {'chat_id': 'TEST', 'session_version_id': 'TEST'}, self.auth(run))
        state = self.json(path, headers=self.auth(run))
        self.assertEqual(state['state'], 'awaiting_native_verification'); self.assertIsNone(state['result'])

    def test_invalid_request_security(self):
        self.assert_http(403, '/api/runs', {'spec': 'all'}, {'Origin': 'https://example.com'})
        self.assert_http(404, '/%2e%2e/server.py')
        self.assert_http(422, '/api/forecast?spec=189A1002-1&months=999999')


class MonthlyLifecycle(unittest.TestCase):
    def test_R08_same_month_new_order_then_cross_month(self):
        with tempfile.TemporaryDirectory() as temp:
            store = MonthlyStore(FIXTURE, temp); before = FIXTURE.read_bytes()
            first = store.refresh('2026-11', forecast_response, '2026-11-10')
            self.assertEqual(first['added_count'], 1); self.assertEqual(first['dataset_rows'], 29)
            second = store.refresh('2026-11', forecast_response, '2026-11-23')
            self.assertNotEqual(first['version'], second['version']); self.assertEqual(second['added_count'], 1); self.assertEqual(second['dataset_rows'], 30)
            self.assertEqual(store.refresh('2026-11', forecast_response, '2026-11-23')['version'], second['version'])
            third = store.refresh('2026-12', forecast_response, '2026-12-01')
            self.assertEqual(third['added_count'], 0); self.assertEqual(third['new_order_totals']['189A1002-1|演示客户甲'], 70)
            fourth = store.refresh('2026-12', forecast_response, '2026-12-06')
            self.assertEqual(fourth['added_count'], 1); self.assertEqual(fourth['dataset_rows'], 31)
            self.assertEqual(fourth['new_order_totals']['189A1002-1|演示客户甲'], 110)
            self.assertEqual(store.snapshot()['window']['end'], '2026-12-06'); self.assertEqual(FIXTURE.read_bytes(), before)
            batch = json.loads((Path(temp) / ('batch-' + fourth['version'] + '.json')).read_text())
            self.assertTrue(any(row['output'] and 'SIM-DEC-001' in row['output']['input_order_ids'] for row in batch['forecasts']))

    def test_R08_background_worker_checks_clock_rollover(self):
        with tempfile.TemporaryDirectory() as temp:
            clock = [datetime(2026, 11, 23, 12, tzinfo=TZ)]
            with patch.dict(os.environ, {'FORECAST_API_BASE': '', 'FORECAST_HISTORY_URL': ''}):
                app = App(('127.0.0.1', 0), runtime=temp, clock=lambda: clock[0], check_interval=.02)
            try:
                deadline = time.monotonic() + 2
                while not app.store.state['batches'] and time.monotonic() < deadline: time.sleep(.02)
                self.assertEqual(app.store.catalog()['batch']['month'], '2026-11')
                clock[0] = datetime(2026, 12, 6, 12, tzinfo=TZ)
                while app.store.catalog()['batch']['month'] != '2026-12' and time.monotonic() < deadline: time.sleep(.02)
                self.assertEqual(app.store.catalog()['batch']['dataset_rows'], 31)
            finally:
                app.server_close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
