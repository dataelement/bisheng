"""Local native API regressions for master/house matching and bill coverage."""
from copy import deepcopy
from http.server import ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch

import service


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(HERE / 'engine'))
from contract import DETAIL_FIELDS, SCHEMA, encode, loads, sha, validate_entities
import transport
import inquiry


def build_fixture():
    fixture = {'schemaVersion': SCHEMA, 'source': {
        'file': 'synthetic waybill regression', 'sha256': '0'*64,
        'dataset_kind': 'synthetic_integration_fixture', 'revision': 4,
        'sheets': {'details': '货物汇总', 'bills': '运费账单'}}, 'details': [], 'bills': []}
    row = {key:'SYNTHETIC' for key in DETAIL_FIELDS}
    row.update(sequence=1, pieces='1', net_weight_kg=20, origin='JFK', destination='TFU',
               goods_currency='USD', goods_foreign=1000, goods_cny=7000, currency='USD',
               fee_foreign=100, fee_cny=700, fee_ratio=0.1, mode='空运',
               material_type='普通', dangerous_goods='危化品', length_cm=100, width_cm=80,
               height_cm=60, package_count=1, carrier='SYNTHETIC CARRIER',
               etd='2024-06-15T00:00:00', eta='2024-06-18T00:00:00', month='2024-06')
    base_bill = dict(invoice_date='2024-06-20T00:00:00', currency='USD', cny_total=700,
                     carrier=row['carrier'], quote_time='2024-06-01T00:00:00')
    plans = [
        ('A', 'MBL-1', 100, [('HBL-1', 30), ('HBL-2', 35)]),
        ('B', 'MBL-1', 700, [('HBL-3', 36), ('', 42)]),
        ('C', 'MBL-2', 1200, [('HBL-1', None)]),
        ('D', 'MBL-3', 1700, [('', None)]),
    ]
    for bill_no, master, total, members in plans:
        bill = deepcopy(base_bill)
        bill.update(bill_no=bill_no, master_no=master, foreign_total=total,
                    house_numbers=';'.join(house for house, _ in members if house),
                    contracts=row['contract_no'], detail_count=len(members),
                    source_row=2 + len(fixture['bills']))
        fixture['bills'].append(bill)
        for house, gross in members:
            source_row = 2 + len(fixture['details'])
            fixture['details'].append({**row, 'id': f'cargo:{source_row}', 'source_row': source_row,
                                       'bill_no': bill_no, 'master_no': master, 'house_no': house,
                                       'fee_foreign': total, 'gross_weight_kg': gross})
    validate_entities(fixture['details'], fixture['bills'])
    return fixture


class WaybillAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        path = Path(cls.directory.name)
        cls.fixture = build_fixture()
        snapshot = path / 'snapshot.json'
        snapshot.write_bytes(encode(cls.fixture))
        token = 'transport-local-regression-token'
        cls.token = token
        source_path = HERE.parent / 'transport-history/server.py'
        spec = importlib.util.spec_from_file_location('transport_source', source_path)
        source = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(source)
        upstream = source.make_server(snapshot, token)
        cls.upstream = upstream
        cls.start(upstream)
        env = patch.dict(os.environ, {'TRANSPORT_API_ORIGIN': f'http://127.0.0.1:{upstream.server_port}',
                                      'TRANSPORT_MOCK_TOKEN': token})
        env.start()
        cls.addClassCleanup(env.stop)
        native = ThreadingHTTPServer(('127.0.0.1', 0), service.Handler)
        native.daemon_threads = True
        cls.sessions = path / 'sessions'
        native.app = service.Application(cls.sessions, token)
        cls.start(native)
        cls.url = f'http://127.0.0.1:{native.server_port}/transport/execute'

    @classmethod
    def start(cls, server):
        cls.addClassCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(thread.join, 1)
        cls.addClassCleanup(server.shutdown)

    def submit(self, request, context=''):
        wrapper = {'request_json': json.dumps(request), 'context_id': context}
        req = urllib.request.Request(self.url, data=encode(wrapper),
                                     headers={'Authorization': 'Bearer ' + self.token,
                                              'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=12) as response:
            result = json.load(response)
        self.assertTrue(result['terminal'])
        self.assertEqual(result['next_action'], 'none')
        return result

    def history(self, master, houses=None, **query):
        query['master_numbers'] = [master]
        if houses is not None:
            query['house_numbers'] = houses
        return self.submit({'action': 'history', 'query': query})

    def test_main_lookup_does_not_combine_separate_bills_or_claim_house_match(self):
        found = self.history('MBL-1')
        self.assertEqual(found['association']['status'], 'master_candidates')
        self.assertEqual(found['counts']['matched_details'], 0)
        self.assertEqual([(b['bill_no'], b['matched_count'], b['coverage_count']) for b in found['bills']],
                         [('A', 0, 2), ('B', 0, 2)])
        self.assertIn('分单未确认', found['answer'])
        self.assertEqual(found['answer'].count('USD 100.00'), 1)
        self.assertEqual(found['answer'].count('USD 700.00'), 1)
        self.assertNotIn('USD 1,200.00', found['answer'])

    def test_pair_keeps_only_actual_bill_and_its_full_coverage(self):
        found = self.history('MBL-1', ['HBL-1'])
        self.assertEqual(found['association']['status'], 'pair_matched')
        self.assertEqual([(b['bill_no'], b['matched_count'], b['coverage_count']) for b in found['bills']], [('A', 1, 2)])
        self.assertIn('HBL-2', found['answer'])
        self.assertNotIn('HBL-3', found['answer'])
        details = self.submit({'action': 'detail', 'reference': 'F01'}, found['context_id'])
        self.assertEqual(details['query_id'], found['query_id'])
        self.assertEqual(details['bills'], found['bills'])
        self.assertIn('主单号：MBL-1', details['answer'])
        self.assertNotIn('USD 700.00', details['answer'])

    def test_house_filter_can_confirm_candidate_and_unknown_stays_unverified(self):
        candidate = self.history('MBL-1')
        confirmed = self.submit({'action': 'filter', 'set': {'house_numbers': ['HBL-3']}},
                                candidate['context_id'])
        self.assertEqual(confirmed['association']['status'], 'pair_matched')
        self.assertEqual([(b['bill_no'], b['matched_count'], b['coverage_count']) for b in confirmed['bills']], [('B', 1, 2)])
        only_blank = self.history('MBL-3')
        self.assertEqual(only_blank['association']['status'], 'master_candidates')
        self.assertIn('未提供', only_blank['answer'])
        unknown = self.history('MBL-1', ['HBL-1', 'HBL-NONE'])
        self.assertEqual(unknown['association']['status'], 'partial_pair_match')
        self.assertEqual(unknown['association']['unconfirmed_house_count'], 1)

    def test_no_pair_does_not_fall_back_to_master_or_to_house_alone(self):
        for master, houses, status in [('MBL-1', ['HBL-NONE'], 'pair_not_confirmed'),
                                       ('MBL-2', ['HBL-3'], 'pair_not_confirmed'),
                                       ('MBL-NONE', None, 'master_not_found')]:
            with self.subTest(master=master, houses=houses):
                response = self.history(master, houses)
                self.assertEqual(response['outcome'], 'no_records')
                self.assertEqual(response['association']['status'], status)
                self.assertEqual(response['bills'], [])

    def test_legacy_bill_and_house_lookup_still_match_and_gross_is_optional(self):
        for query in ({'bill_numbers': ['A']}, {'house_numbers': ['HBL-3']}):
            with self.subTest(query=query):
                result = self.submit({'action': 'history', 'query': query})
                self.assertEqual(result['outcome'], 'ok')
                self.assertNotIn('人民币开票金额', result['answer'])
                self.assertNotIn('货值', result['answer'])
                self.assertNotIn('运费占比', result['answer'])
        result = self.history('MBL-2', ['HBL-1'])
        self.assertIn('毛重：未提供', result['answer'])

    def test_inquiry_compares_only_gross_and_dimensions(self):
        row = self.fixture['details'][0]
        target = {field: row[field] for field in inquiry.REQUIRED}
        target['package_count'] = row['package_count'] + 10
        full = self.submit({'action': 'inquiry', 'target': target})
        self.assertEqual(full['match']['match_type'], 'full')
        self.assertIn('全量匹配（物料、毛重、尺寸', full['answer'])
        self.assertNotIn('包装数量', full['answer'])
        self.assertTrue(all('amount_ranges' in plan and 'cny_min' not in plan for plan in full['recommendation']))
        unknown = {**target, 'net_weight_kg': target['gross_weight_kg']}
        del unknown['gross_weight_kg']
        missing = self.submit({'action': 'inquiry', 'target': unknown})
        self.assertEqual(missing['outcome'], 'needs_clarification')
        self.assertIn('毛重', missing['answer'])

    def test_retired_fields_absent_in_history_detail_and_limits(self):
        initial = self.history('MBL-1', ['HBL-1'])
        results = [initial,
                   self.submit({'action': 'detail', 'reference': 'F01'}, initial['context_id']),
                   self.submit({'action': 'explain_limits'})]
        for result in results:
            for retired in ('报价日期', '报价时间', '开票日期', '人民币', '货值', '运费占比', '包装数量'):
                self.assertNotIn(retired, result['answer'])

    def test_history_fetches_only_requested_scope_without_recommendations(self):
        handler = self.upstream.RequestHandlerClass
        original = handler.do_POST
        calls = []
        def record(instance):
            calls.append(instance.path)
            return original(instance)
        with patch.object(handler, 'do_POST', record):
            result = self.submit({'action': 'history', 'query': {'bill_numbers': ['A']}})
        self.assertEqual(result['outcome'], 'ok')
        self.assertEqual(len(calls), 1)
        self.assertNotIn('recommendation', result)
        self.assertNotIn('方案推荐', result['answer'])

    def test_retired_date_and_physical_filters_rejected_without_state_change(self):
        first = self.history('MBL-1', ['HBL-1'])
        for request in (
                {'action': 'show', 'sort': 'invoice_date_desc'},
                {'action': 'filter', 'set': {'date_from': '2024-01-01', 'date_field': 'invoice_date'}},
                {'action': 'history', 'query': {'package_count': 2}},
                {'action': 'history', 'query': {'net_weight_kg': 100}}):
            result = self.submit(request, first['context_id'])
            self.assertEqual(result['outcome'], 'invalid_request')
        restored = self.submit({'action': 'show'}, first['context_id'])
        self.assertEqual(restored['bills'], first['bills'])
        self.assertEqual(restored['query_id'], first['query_id'])

    def test_recommendation_ignores_all_retired_amount_fields(self):
        rows = deepcopy(self.fixture['details'])
        bills = deepcopy(self.fixture['bills'])
        target = {field: rows[0][field] for field in inquiry.REQUIRED}
        expected = inquiry.recommend(rows, bills, target)
        for row in rows:
            for key in ('goods_currency','goods_foreign','goods_cny','fee_cny','fee_ratio','package_count'):
                row.pop(key)
        for bill in bills:
            for key in ('cny_total','quote_time','invoice_date'):
                bill.pop(key)
        self.assertEqual(inquiry.recommend(rows, bills, target), expected)
        self.assertTrue(all('cny_median' not in item for item in expected['items']))

    def test_explicit_recommendation_keeps_approximate_and_no_route_experience(self):
        row = self.fixture['details'][0]
        target = {field: row[field] for field in inquiry.REQUIRED}
        approximate = self.submit({'action': 'inquiry', 'target': {**target, 'gross_weight_kg': 999}})
        self.assertEqual(approximate['match']['match_type'], 'approximate')
        self.assertTrue(approximate['recommendation'])
        other_route = self.submit({'action': 'inquiry', 'target': {**target, 'destination': 'NO_ROUTE'}})
        self.assertEqual(other_route['outcome'], 'recommended')
        self.assertEqual(other_route['counts']['matched_details'], 0)
        self.assertIn('相近经验', other_route['answer'])
        self.assertTrue(other_route['recommendation'])

    def test_legacy_sort_and_advice_remain_readable_without_active_use(self):
        initial = self.history('MBL-1', ['HBL-1'])
        path = self.sessions / initial['context_id'] / transport.STATE
        state = loads(path.read_bytes())
        state['view']['sort'] = 'invoice_date_desc'
        base = self.fixture['details'][0]
        state['advice'] = {'basis': {'house_no': base['house_no'], **{key:base[key] for key in transport.ADVICE_KEYS}},
                           'profiles': 1, 'total': 0, 'items': []}
        state['sha256'] = sha(encode({key:value for key,value in state.items() if key!='sha256'}))
        path.write_bytes(encode(state))
        restored = self.submit({'action': 'show'}, initial['context_id'])
        self.assertEqual(restored['outcome'], 'ok')
        self.assertEqual(restored['bills'], initial['bills'])
        self.assertNotIn('方案推荐', restored['answer'])
        state['filters'] = {'date_field': 'invoice_date', 'date_from': '2024-01-01'}
        state['sha256'] = sha(encode({key:value for key,value in state.items() if key!='sha256'}))
        path.write_bytes(encode(state))
        retired = self.submit({'action': 'show'}, initial['context_id'])
        self.assertEqual(retired['outcome'], 'needs_query')
        self.assertNotIn('bills', retired)

    def test_inquiry_additional_filter_also_limits_recommendations(self):
        target = {field: self.fixture['details'][0][field] for field in inquiry.REQUIRED}
        result = self.submit({'action':'inquiry', 'target': target, 'set': {'model': 'NO_MODEL'}})
        self.assertEqual(result['outcome'], 'no_records')
        self.assertEqual(result['counts']['matched_details'], 0)
        self.assertEqual(result['recommendation'], [])


if __name__ == '__main__':
    unittest.main()
