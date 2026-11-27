"""Optional API quality metadata: synthetic fixtures, no real model or credentials."""
import copy
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_workflow as fixtures
from engine import ForecastGateway, GatewayError, validate_prediction
from reports import html_report, markdown
from workflow import Workflow, WorkflowError


class OptionalPredictionQuality(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.app=fixtures.FakeApp(self.temp.name);self.workflow=Workflow(self.app)
        self.created=self.workflow.create({'spec':'189A1002-1','months':3})
        self.runid,self.token=self.created['run_id'],self.created['token']
        self.hashes=self.workflow._hashes()

    act=fixtures.WorkflowProtocol.act
    history=fixtures.WorkflowProtocol.history
    explanation=fixtures.WorkflowProtocol.explanation
    simulated_verification_evidence=fixtures.WorkflowProtocol.simulated_verification_evidence

    def external_payload(self):
        raw=self.app.gateway.predict('189A1002-1','all','2026-12',3,'fixture-only')
        raw['dataset_sha']='independent-api-fixture'
        for row in raw['monthly']:
            row.pop('backtest_mape',None);row['is_synthetic']=False
        return raw

    def validate(self,raw):
        return validate_prediction(raw,'189A1002-1','all','2026-12',3,expected_synthetic=None,
                                   expected_customers=self.app.store.source['customers'])

    def test_missing_quality_preserves_api_rows_and_values(self):
        raw=self.external_payload();saved=copy.deepcopy(raw)
        result=self.validate(raw)
        self.assertEqual(raw,saved)
        self.assertEqual(result['monthly'],saved['monthly'])
        self.assertTrue(all('backtest_mape' not in row for row in result['monthly']))
        self.assertTrue(any('未提供' in note for note in result['quality_notes']))
        self.assertFalse(any('偏差较大' in note for note in result['quality_notes']))

    def test_null_and_partially_available_quality_remain_distinct(self):
        raw=self.external_payload();raw['monthly'][0]['backtest_mape']=None
        raw['monthly'][1]['backtest_mape']=.48
        result=self.validate(raw)
        self.assertIsNone(result['monthly'][0]['backtest_mape'])
        self.assertTrue(any('未提供' in note for note in result['quality_notes']))
        self.assertTrue(any('48.0%' in note for note in result['quality_notes']))

    def test_provided_quality_is_strictly_validated(self):
        for invalid in (-.01,1.01,True,False,'0.18',float('nan'),float('inf'),[],{}):
            with self.subTest(value=repr(invalid)):
                raw=self.external_payload();raw['monthly'][0]['backtest_mape']=invalid
                with self.assertRaises(GatewayError):self.validate(raw)
        for valid in (0,1,.18):
            with self.subTest(value=valid):
                raw=self.external_payload();raw['monthly'][0]['backtest_mape']=valid
                self.assertEqual(self.validate(raw)['monthly'][0]['backtest_mape'],valid)

    def test_missing_quality_does_not_relax_scope_or_price_validation(self):
        for field,value in [('quantity',True),('amount',-1),('unit_price','48.42'),('month','2040-01'),('is_synthetic',None)]:
            raw=self.external_payload();raw['monthly'][0][field]=value
            with self.subTest(field=field),self.assertRaises(GatewayError):self.validate(raw)
        raw=self.external_payload();raw['monthly'].pop()
        with self.assertRaises(GatewayError):self.validate(raw)

    def http_gateway(self, payload, full_endpoint=False):
        outer=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                outer.http_path=self.path
                code=200 if self.path.split('?')[0]=='/api/forecast' else 404
                blob=json.dumps(payload).encode()
                self.send_response(code);self.send_header('Content-Length',str(len(blob)));self.end_headers();self.wfile.write(blob)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def close():server.shutdown();server.server_close();thread.join(1)
        self.addCleanup(close)
        base='http://127.0.0.1:'+str(server.server_port)
        self.app.forecast_is_external=True
        self.app.gateway=ForecastGateway(base+('/api/forecast' if full_endpoint else '/'))

    def test_api_base_with_trailing_slash_consumes_optional_quality(self):
        self.http_gateway(self.external_payload())
        history=self.history()
        self.assertTrue(self.http_path.startswith('/api/forecast?'))
        self.assertEqual(history['facts']['status'],'predicted')
        self.assertTrue(any('未提供' in note for note in history['facts']['forecast']['quality_notes']))

    def test_full_endpoint_in_base_configuration_fails_without_report(self):
        self.http_gateway(self.external_payload(),full_endpoint=True)
        with self.assertRaises(WorkflowError):self.act('forecast')
        state=self.workflow.get(self.runid,self.token)
        self.assertEqual(state['state'],'stage_failed');self.assertIsNone(state['result'])
        self.assertIn('/api/forecast/api/forecast?',self.http_path)

    def test_string_zero_format_error_does_not_become_unpredictable(self):
        self.http_gateway('0')
        with self.assertRaises(WorkflowError):self.act('forecast')
        state=self.workflow.get(self.runid,self.token)
        self.assertEqual(state['state'],'stage_failed');self.assertIsNone(state['result'])

    def test_independent_api_without_quality_completes_same_run_reports(self):
        raw=self.external_payload();self.app.forecast_is_external=True
        with patch.object(self.app.gateway,'predict',return_value=raw):history=self.history()
        self.assertEqual(history['facts']['status'],'predicted')
        self.assertFalse(history['facts']['provenance']['forecast_is_synthetic'])
        self.assertEqual(history['facts']['forecast']['summary']['quantity'],sum(row['quantity'] for row in raw['monthly']))
        self.assertEqual(len(history['suggestion_targets']),2)
        self.act('finalize',{'explanation':self.explanation(history)})
        result=self.workflow.verify(self.runid,self.token,self.simulated_verification_evidence())['result']
        self.assertTrue(all('backtest_mape' not in row for row in result['items'][0]['forecast']['monthly']))
        for text in (html_report(result),markdown(result)):
            self.assertIn(result['request_id'],text);self.assertIn('未提供',text)
            self.assertNotIn('回测偏差较大',text)
        frozen=json.loads((Path(self.temp.name)/'reports'/self.runid/'result.json').read_text())
        self.assertEqual(frozen['request_id'],result['request_id'])
        self.assertEqual(frozen['forecast'],result['forecast'])
        self.assertEqual(frozen['report_dimensions']['suggestions'],result['report_dimensions']['suggestions'])


if __name__=='__main__':unittest.main()
