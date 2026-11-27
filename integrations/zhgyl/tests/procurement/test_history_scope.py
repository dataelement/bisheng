"""Synthetic, network-free regression for history/supplier intent boundaries."""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

DEFAULT = Path(__file__).resolve().parents[2] / 'skills/procurement-history'
SKILL = Path(os.environ.get('PROCUREMENT_SKILL_DIR', DEFAULT))
sys.path.insert(0, str(SKILL / 'scripts'))
import procurement as p
import procurement_workflow as flow


class HistoryScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        old = Path.cwd()
        os.chdir(self.temp.name)
        self.addCleanup(os.chdir, old)
        Path('uploads/procurement-api').mkdir(parents=True)
        self.serial = 0
        self.columns = []
        for i in range(1, 130):
            n, letters = i, ''
            while n:
                n, remainder = divmod(n - 1, 26)
                letters = chr(65 + remainder) + letters
            self.columns.append({'key': 'col_' + letters, 'column': letters, 'label': 'fixture'})
        for _, (index, label) in p.engine.FIELDS.items():
            self.columns[index]['label'] = label
        self.rows = []
        for i, (model, supplier, price) in enumerate([
                ('DEMO-QPL-001', 'Fixture A', 100), ('DEMO-QPL-001', 'Fixture B', 120),
                ('DEMO-NEAR-001', 'Fixture A', 105), ('DEMO-NEAR-002', 'Fixture B', 110)], 1):
            row = dict.fromkeys([c['key'] for c in self.columns])
            vals = dict(model=model, supplier_name=supplier, supplier_id='S'+str(i),
                        order_id='O'+str(i), order_no='PO'+str(i), line_id='L'+str(i),
                        order_fk='O'+str(i), line_order_no='PO'+str(i), line_no='1',
                        customer_name='Fixture customer', material_name='铝合金',
                        currency='CNY', unit='件', quantity=10, unit_price=price,
                        line_amount=price*10, header_total=price*10, incoterms='FCA',
                        incoterms_place='Fixture place', confirmed_at='2026-11-0'+str(i)+' 10:00:00')
            for key, value in vals.items():
                row[self.columns[p.engine.FIELDS[key][0]]['key']] = value
            self.rows.append(row)
        qpl = [dict(record_id='Q'+str(i),row_kind='supplier_record',source_page=1,source_row=i,
                    company_name=name,company_code='Q'+str(i),address='Fixture address',city='Fixture city',country='Fixture country', product_group_code='AFM-002-1',
                    product_group='材料分销',product_group_source_page=1,product_group_source_row=1,raw_text=name,review_notes='synthetic only',parse_status='fixture')
               for i,name in enumerate(['Fixture A','Fixture B','Fixture Catalog'],1)]
        self.index = Path('qualification.json')
        self.index.write_text(json.dumps({'version':1,'qpl':{'records':qpl,'source':{'file':'fixture-qpl'}},
                                         'qsl':{'records':[],'source':{'file':'fixture-qsl'}}}))
        self.patch = patch.object(p, 'INDEX', self.index.resolve())
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def receipt(self, model, mode='exact'):
        self.serial += 1
        rows = [deepcopy(r) for r in self.rows if (re.search(model,r['col_CJ']) if mode=='regex' else r['col_CJ']==model)]
        source = {'file':'synthetic.json','sheet':'fixture','scope':'synthetic_only'}
        data = dict(schemaVersion='procurement-excel-v1',mock=True,result=rows, sourceRows=[i+2 for i,r in enumerate(self.rows) if r in rows],
                    totalElements=len(rows),pageNum=1,pageSize=100,totalPages=1 if rows else 0,hasNext=False,
                    matchedModelCount=len({r['col_CJ'] for r in rows}),snapshotId='fixture-scope-v1',
                    query={'model':model,'match_mode':mode},fieldMap=self.columns,source=source)
        name = 'uploads/procurement-api/'+str(self.serial)+'.json'
        Path(name).write_text(json.dumps({'success':True,'code':'000000','data':{'status':200,'data':data}}))
        return name

    def run_action(self, request, outcome='ok'):
        result=p.run(request)
        self.assertEqual(result['outcome'],outcome,result)
        self.assertTrue(result['terminal'])
        self.assertEqual(result['next_action'],'none')
        return result

    def first(self, model='DEMO-QPL-001', action='history', **kw):
        return self.run_action(dict(action=action, model=model,page_files=[self.receipt(model)],**kw),
                               'ok' if any(r['col_CJ']==model for r in self.rows) else 'no_records')

    def keep(self, model, intent=None):
        _, pattern=flow.pending_pattern(model)
        req=dict(action='resolve',decision='keep',model=pattern,reference_model=model,match_mode='regex',page_files=[self.receipt(pattern,'regex')])
        if intent:req['intent']=intent
        return self.run_action(req,'ok' if any(re.search(pattern,r['col_CJ']) for r in self.rows) else 'no_records')

    def cache(self):
        return Path('uploads/procurement-runtime/recommendations.json')

    def candidate(self, model='DEMO-QPL-001'):
        value=json.loads(self.cache().read_text())[p.engine.norm(model)]
        return next(i['candidate_ref'] for i in value['items'] if i.get('group')=='catalog')

    def assert_history(self,result):
        self.assertNotIn('一、本型号历史供应商',result['answer'])
        self.assertNotIn('二、名录候选供应商',result['answer'])
        self.assertFalse(self.cache().exists())

    def test_history_does_not_query_or_load_suppliers_or_publish_candidates(self):
        with patch.object(p.qualification_lookup,'load',side_effect=AssertionError('no catalog lookup')), patch.object(p.recommendation,'recommend',side_effect=AssertionError('no recommendation')), patch.object(p.engine,'query_records',wraps=p.engine.query_records) as query:
            result=self.first(purchaser='空客')
            self.assert_history(result)
            self.assertTrue(all(c.args[2].get('intent','history')=='history' for c in query.call_args_list))
        registry=p.load_registry()
        saved=json.loads((Path(registry['entries'][0]['session']).with_name('session-model-1-result.json')).read_text())
        self.assertNotIn('advice',saved)

    def test_history_filter_sort_reset_and_compare_stay_history(self):
        self.first()
        for req in [dict(action='filter',set={'customer':'Fixture customer'}),dict(action='show',sort='price_asc'),dict(action='reset'),dict(action='compare',positions=[1,2])]:
            self.assert_history(self.run_action(req))

    def test_history_followed_by_explicit_suppliers_reuses_batch(self):
        self.first(purchaser='空客')
        result=self.run_action({'action':'suppliers'})
        self.assertIn('一、本型号历史供应商',result['answer'])
        self.assertIn('二、名录候选供应商',result['answer'])
        self.assertTrue(self.cache().exists())
        self.run_action({'action':'confirm','supplier_name':self.candidate()},'confirmed')
        self.run_action({'action':'unconfirm'})

    def test_exact_and_near_missing_history_have_no_recommendation(self):
        self.assert_history(self.first('MISSING-XYZ',purchaser='空客'))
        self.assert_history(self.keep('MISSING-XYZ'))
        result=self.run_action({'action':'explain_limits','topic':'sourcing'})
        self.assertIn('二、名录候选供应商',result['answer'])
        self.assertTrue(self.cache().exists())

    def test_history_near_candidates_and_choose_stay_history(self):
        self.first('DEMO-NEAR-MISSING',purchaser='空客')
        self.assert_history(self.keep('DEMO-NEAR-MISSING'))
        self.assert_history(self.run_action({'action':'choose','candidate_position':2,'intent':'history'}))
        self.assertEqual(p.load_registry()['workflow']['selected_model'],'DEMO-NEAR-002')
        self.run_action({'action':'suppliers'})
        self.assertTrue(self.cache().exists())

    def test_choose_history_with_filters_from_supplier_intent_skips_catalog(self):
        self.first('DEMO-NEAR-MISSING',action='suppliers',purchaser='空客')
        self.keep('DEMO-NEAR-MISSING')
        with patch.object(p.qualification_lookup,'load',side_effect=AssertionError('no catalog lookup')), patch.object(p.recommendation,'recommend',side_effect=AssertionError('no recommendation')), patch.object(p.engine,'query_records',wraps=p.engine.query_records) as query:
            result=self.run_action({'action':'choose','candidate_position':1,'intent':'history','set':{'customer':'Fixture customer'}})
            self.assertEqual(len(query.call_args_list),1)
            self.assertTrue(all(c.args[2].get('intent','history')=='history' for c in query.call_args_list))
            self.assertNotIn('二、名录候选供应商',result['answer'])

    def test_supplier_intent_near_missing_still_recommends(self):
        self.first('MISSING-XYZ',action='suppliers',purchaser='空客')
        result=self.keep('MISSING-XYZ')
        self.assertIn('二、名录候选供应商',result['answer'])
        self.assertTrue(self.cache().exists())

    def test_same_scope_history_keeps_already_shown_catalog_ids(self):
        self.first(action='suppliers',purchaser='空客')
        ref=self.candidate();before=self.cache().read_bytes()
        result=self.run_action({'action':'history'})
        self.assertNotIn('二、名录候选供应商',result['answer'])
        self.assertEqual(self.cache().read_bytes(),before)
        self.run_action({'action':'confirm','supplier_name':ref},'confirmed')

    def test_history_filter_expiry_does_not_restore_old_ref_after_unset(self):
        self.first(action='suppliers',purchaser='空客');ref=self.candidate()
        self.run_action({'action':'history','set':{'supplier':'Fixture A'}})
        self.run_action({'action':'history','unset':['supplier']})
        self.run_action({'action':'confirm','supplier_name':ref},'invalid_selection')
        self.run_action({'action':'suppliers'})
        self.assertNotEqual(self.candidate(),ref)

    def test_filtered_history_from_supplier_view_skips_supplier_execution(self):
        self.first(action='suppliers',purchaser='空客')
        with patch.object(p.qualification_lookup,'load',side_effect=AssertionError('no catalog lookup')), patch.object(p.recommendation,'recommend',side_effect=AssertionError('no recommendation')), patch.object(p.engine,'query_records',wraps=p.engine.query_records) as query:
            result=self.run_action({'action':'history','set':{'supplier':'Fixture A'}})
            self.assertEqual(len(query.call_args_list),1)
            self.assertTrue(all(c.args[2].get('intent','history')=='history' for c in query.call_args_list))
            self.assertNotIn('二、名录候选供应商',result['answer'])

    def test_history_buyer_change_expires_ref_even_when_switched_back(self):
        self.first(action='suppliers',purchaser='空客');ref=self.candidate()
        self.run_action({'action':'history','purchaser':'其他甲方'})
        self.run_action({'action':'history','purchaser':'空客'})
        self.run_action({'action':'confirm','supplier_name':ref},'invalid_selection')

    def test_empty_history_filter_expires_ref(self):
        self.first(action='suppliers',purchaser='空客');ref=self.candidate()
        self.run_action({'action':'history','set':{'supplier':'not present'}},'no_records')
        self.run_action({'action':'history','unset':['supplier']})
        self.run_action({'action':'confirm','supplier_name':ref},'invalid_selection')

    def test_new_query_does_not_accept_old_candidate_ref(self):
        self.first(action='suppliers',purchaser='空客');ref=self.candidate()
        self.first('DEMO-NEAR-001',purchaser='空客')
        self.run_action({'action':'confirm','supplier_name':ref},'invalid_selection')

    def test_history_supplier_name_cannot_confirm_without_supplier_view(self):
        self.first(purchaser='空客')
        self.run_action({'action':'confirm','supplier_name':'Fixture A'},'needs_clarification')

    def test_explicit_supplier_buyer_filters_and_price_conditions_remain(self):
        result=self.first(action='suppliers',purchaser='空客',set={'supplier':'Fixture A'},sort='price_asc')
        self.assertIn('FCA',result['answer']);self.assertIn('CNY',result['answer'])
        self.assertIn('历史最低单价升序',result['answer'])
        result=self.run_action({'action':'suppliers','purchaser':'商飞','unset':['supplier']})
        self.assertIn('排除',result['answer'])
        self.run_action({'action':'confirm','supplier_name':'Fixture A'},'invalid_selection')

    def test_explicit_qsl_standard_candidate_can_confirm_and_unconfirm(self):
        index=json.loads(self.index.read_text())
        index['qsl']['records']=[dict(record_id='FIXTURE-QSL-1',row_kind='supplier_record',source_row=1,
            supplier_name='Fixture QSL catalog',supplier_code='FIXTURE-QSL',material_category='钢材-不锈钢',
            standard_code='AMS5557',product_form='管材',parse_status='fixture')]
        self.index.write_text(json.dumps(index))
        result=self.first('AMS5557',action='suppliers',purchaser='商飞')
        self.assertIn('QSL规范号一致',result['answer'])
        ref=self.candidate('AMS5557')
        self.run_action({'action':'confirm','supplier_name':ref},'confirmed')
        self.run_action({'action':'unconfirm'})

    def test_batch_history_isolated_then_explicit_item_suppliers(self):
        result=self.run_action({'action':'batch','intent':'history','purchaser':'空客','items':[
            {'model':'DEMO-QPL-001','page_files':[self.receipt('DEMO-QPL-001')]},
            {'model':'MISSING-XYZ','page_files':[self.receipt('MISSING-XYZ')]}]},'partial')
        self.assertNotIn('二、名录候选供应商',result['answer'])
        meta=json.loads(Path('uploads/procurement-runtime/manual-batch.json').read_text())
        first=Path(meta['items'][0]['root'])/'session-registry.json';before=first.read_bytes()
        result=self.run_action({'action':'suppliers','item_index':2},'no_records')
        self.assertIn('二、名录候选供应商',result['answer'])
        self.assertEqual(first.read_bytes(),before)


if __name__=='__main__':
    unittest.main(verbosity=2)
