"""Fixture tests of the verification gate; these are not native execution proof."""
import copy
import hashlib
import io
import json
import unittest
import urllib.error
from unittest.mock import Mock

from native_bridge import NativeBridge, NativeBridgeError, NoRedirect


class NativeBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tool_key = 'tool_type_23_abc123'
        self.bridge = NativeBridge('http://platform.test:3008', tool_key=self.tool_key)
        self.contract = {'run_id': 'run-1', 'skill_sha256': 'a' * 64, 'cli_sha256': 'b' * 64,
                         'actions': {a: str(i) * 64 for i, a in enumerate(('forecast', 'history', 'finalize'), 1)}}
        self.versions = [{'id': 'version-1', 'session_id': 'chat-1', 'model': '1', 'user_id': 1,
                          'status': 'completed', 'skills': ['procurement-forecast-fast'],
                          'tools': [{'children': [{'id': 46, 'tool_key': self.tool_key}]}]}]
        self.catalog = [{'name': 'procurement-forecast-fast', 'content_hash': 'c' * 64}]
        self.config = {'models': [{'id': '1', 'name': 'fixture-model'}],
                       'tools': [{'children': [{'id': 46, 'tool_key': self.tool_key, 'name': 'forecast_execute', 'enabled': True}]}]}
        self.native_tools = [{'id': 23, 'user_id': 1, 'children': [
            {'id': 46, 'tool_key': self.tool_key, 'name': 'forecast_execute', 'user_id': 1}]}]
        records = [{'name': 'read_file', 'input': {'file_path': '/skills/procurement-forecast-fast/SKILL.md'}, 'output': 'Fixture SKILL body'}]
        for action, sha in self.contract['actions'].items():
            receipt = {'ok': True, 'action': action, 'run_id': 'run-1', 'action_sha256': sha,
                       'skill_sha256': 'a' * 64, 'cli_sha256': 'b' * 64}
            records.append({'name': self.tool_key, 'input': {'request_json': 'fixture'},
                            'is_completed': True, 'output': json.dumps({'status_code': 200, 'data': receipt})})
        self.detail = [{'id': 'task', 'history': [], 'children': [{'history': records}]}]

    def wire(self):
        self.raw_detail = json.dumps({'status_code': 200, 'data': self.detail}).encode()
        payloads = [self.versions, self.catalog, self.config, self.detail]
        selected_id = self.versions[0]['tools'][0]['children'][0]['id'] if self.versions[0].get('tools') else None
        if not any(t.get('tool_key') == self.tool_key and t.get('name') == 'forecast_execute'
                   and t.get('id') == selected_id and t.get('enabled') is not False
                   for group in self.config.get('tools', []) for t in group.get('children', [])):
            payloads.insert(3, self.native_tools)
        raw = [json.dumps({'status_code': 200, 'data': p}).encode() for p in payloads]
        self.bridge.opener = Mock()
        self.bridge.opener.open.side_effect = [io.BytesIO(r) for r in raw]

    def verify(self, **kwargs):
        self.wire()
        return self.bridge.verify('session=SECRET-FIXTURE', 'chat-1', 'version-1', self.contract, **kwargs)

    def prepare_receipt(self, compact=False):
        """Use the compact production response shape, not duplicate raw outputs."""
        records = self.detail[0]['children'][0]['history']
        subactions = [json.loads(record['output'])['data'] for record in records[1:3]]
        if compact:
            subactions = [{key: receipt[key] for key in ('ok', 'action', 'action_sha256')}
                          for receipt in subactions]
        receipt = {**subactions[1], 'action': 'prepare', 'subactions': subactions}
        receipt.update(run_id=self.contract['run_id'], skill_sha256=self.contract['skill_sha256'],
                       cli_sha256=self.contract['cli_sha256'])
        records[1:3] = [{'name': self.tool_key, 'is_completed': True,
                         'output': json.dumps({'receipt': receipt, 'ok': True})}]
        return receipt, records[1]

    def test_checkpoint_accepts_proven_active_task_without_claiming_native_completion(self):
        for status in ('in_progress', 'running', 'completed'):
            with self.subTest(status=status):
                self.versions[0]['status'] = status
                evidence = self.verify(business_checkpoint=True)
                self.assertEqual(evidence['status'], status)
                self.assertEqual(evidence['completion_gate'], 'all_business_actions_verified')
                self.assertEqual(evidence['tool_action_sha'], self.contract['actions'])
        self.assertEqual(self.verify()['completion_gate'], 'native_task_completed')

    def test_checkpoint_active_task_without_each_real_proof_is_rejected(self):
        for missing in ('skill', 'forecast', 'history', 'finalize'):
            with self.subTest(missing=missing):
                self.setUp()
                self.versions[0]['status'] = 'in_progress'
                records = self.detail[0]['children'][0]['history']
                index = ('skill', 'forecast', 'history', 'finalize').index(missing)
                records.pop(index)
                with self.assertRaises(NativeBridgeError): self.verify(business_checkpoint=True)

    def test_checkpoint_rejects_terminal_invalid_and_foreign_tasks_even_with_proof(self):
        for status in ('pending', 'queued', 'terminated', 'cancelled', 'failed', 'error', None):
            with self.subTest(status=status):
                self.versions[0]['status'] = status
                with self.assertRaises(NativeBridgeError): self.verify(business_checkpoint=True)
        self.setUp()
        self.versions[0]['session_id'] = 'foreign-chat'
        with self.assertRaises(NativeBridgeError): self.verify(business_checkpoint=True)

    def test_prepare_subreceipts_support_full_and_first_receipt_preview(self):
        for preview in (False, True):
            with self.subTest(preview=preview):
                self.setUp()
                receipt, record = self.prepare_receipt()
                if preview:
                    record['output'] = ('Tool result too large. Here is a preview:\n'
                                        '     1\t{"receipt": ' + json.dumps(receipt)
                                        + ', "facts": {"truncated": "')
                self.versions[0]['status'] = 'running'
                self.assertEqual(self.verify(business_checkpoint=True)['tool_action_sha'], self.contract['actions'])

    def test_prepare_subreceipts_require_exact_two_distinct_successful_actions(self):
        for mutation in ('missing', 'duplicate', 'reversed', 'extra', 'mapping', 'failed', 'foreign_run',
                         'wrong_hash', 'wrong_skill', 'wrong_cli', 'outside_subactions', 'outer_run'):
            with self.subTest(mutation=mutation):
                self.setUp()
                receipt, record = self.prepare_receipt()
                if mutation == 'missing': receipt['subactions'].pop()
                elif mutation == 'duplicate': receipt['subactions'][1] = copy.deepcopy(receipt['subactions'][0])
                elif mutation == 'reversed': receipt['subactions'].reverse()
                elif mutation == 'extra': receipt['subactions'].append(copy.deepcopy(receipt['subactions'][0]))
                elif mutation == 'mapping': receipt['subactions'] = {r['action']: r for r in receipt['subactions']}
                elif mutation == 'failed': receipt['subactions'][0]['ok'] = False
                elif mutation == 'foreign_run': receipt['subactions'][0]['run_id'] = 'foreign-run'
                elif mutation == 'wrong_hash': receipt['subactions'][0]['action_sha256'] = 'd' * 64
                elif mutation == 'wrong_skill': receipt['subactions'][0]['skill_sha256'] = 'e' * 64
                elif mutation == 'wrong_cli': receipt['subactions'][0]['cli_sha256'] = 'f' * 64
                elif mutation == 'outer_run': receipt['run_id'] = 'foreign-run'
                else: receipt['unrelated_facts'] = receipt.pop('subactions')
                record['output'] = json.dumps({'receipt': receipt, 'ok': True})
                with self.assertRaises(NativeBridgeError): self.verify(business_checkpoint=True)

    def test_compact_prepare_rejects_missing_child_identity_override_and_unknown_fields(self):
        for mutation in ('missing', 'foreign_run', 'wrong_skill', 'wrong_cli', 'wrong_action_sha', 'unknown'):
            with self.subTest(mutation=mutation):
                self.setUp()
                receipt, record = self.prepare_receipt(compact=True)
                if mutation == 'missing': receipt['subactions'].pop()
                elif mutation == 'foreign_run': receipt['subactions'][0]['run_id'] = 'foreign-run'
                elif mutation == 'wrong_skill': receipt['subactions'][0]['skill_sha256'] = 'd' * 64
                elif mutation == 'wrong_cli': receipt['subactions'][0]['cli_sha256'] = 'e' * 64
                elif mutation == 'wrong_action_sha': receipt['subactions'][0]['action_sha256'] = 'f' * 64
                else: receipt['subactions'][0]['extra_receipt'] = {'run_id': self.contract['run_id']}
                record['output'] = json.dumps({'receipt': receipt, 'ok': True})
                with self.assertRaises(NativeBridgeError): self.verify(business_checkpoint=True)

    def test_authoritative_recursive_outputs_and_exact_digest(self):
        evidence = self.verify()
        self.assertEqual(evidence['tool_action_sha'], self.contract['actions'])
        self.assertEqual(evidence['task_detail_sha256'], hashlib.sha256(self.raw_detail).hexdigest())
        self.assertEqual(evidence['model'], 'fixture-model')
        self.assertNotIn('SECRET-FIXTURE', json.dumps(evidence))
        for call in self.bridge.opener.open.call_args_list:
            request = call.args[0]
            self.assertEqual(request.get_method(), 'GET')
            self.assertEqual(call.kwargs['timeout'], 10)
            self.assertTrue(request.full_url.startswith('http://platform.test:3008/'))

    def test_echoed_prompt_inputs_and_assistant_answer_are_not_proof(self):
        records = self.detail[0]['children'][0]['history']
        receipts = copy.deepcopy(records[1:])
        records[:] = records[:1] + [{'name': 'thinking', 'output': json.dumps(receipts)},
                                    {'name': self.tool_key, 'input': json.dumps(receipts),
                                     'output': json.dumps({'ok': True, 'message': 'No API action executed'})}]
        self.versions[0]['question'] = json.dumps(receipts)
        self.versions[0]['output_result'] = {'answer': json.dumps(receipts)}
        with self.assertRaises(NativeBridgeError): self.verify()

    def test_each_receipt_must_match_run_action_hash_and_files(self):
        for key, bad in [('run_id', 'other-run'), ('action_sha256', 'd' * 64),
                         ('skill_sha256', 'e' * 64), ('cli_sha256', 'f' * 64), ('ok', False), ('action', 'other')]:
            with self.subTest(key=key):
                self.setUp()
                record = self.detail[0]['children'][0]['history'][2]
                execution = json.loads(record['output']); receipt = execution['data']
                receipt[key] = bad; record['output'] = json.dumps(execution)
                with self.assertRaises(NativeBridgeError): self.verify()

    def test_failed_api_and_missing_skill_read_fail(self):
        self.detail[0]['children'][0]['history'][1]['output'] = self.detail[0]['children'][0]['history'][1]['output'].replace('"status_code": 200', '"status_code": 500')
        with self.assertRaises(NativeBridgeError): self.verify()
        self.setUp(); self.detail[0]['children'][0]['history'][0]['input'] = {'file_path': '/other/SKILL.md'}
        with self.assertRaises(NativeBridgeError): self.verify()

    def test_structured_json_read_input_supported(self):
        record = self.detail[0]['children'][0]['history'][0]
        record['tool_input'] = json.dumps(record.pop('input'))
        self.assertEqual(self.verify()['status'], 'completed')

    def test_contract_key_and_operation_name_with_nested_json_output(self):
        self.bridge = NativeBridge('http://platform.test:3008')
        self.contract['native_tool_key'] = self.tool_key
        for record in self.detail[0]['children'][0]['history'][1:]:
            record['name'] = 'forecast_execute'
            # Native API wrappers may serialize the raw response as a string.
            record['output'] = json.dumps({'status_code': 200, 'data': record['output']})
        evidence = self.verify()
        self.assertEqual(evidence['execution_tool'], 'native_api')
        self.assertEqual(evidence['native_tool_key'], self.tool_key)

    def test_native_numbered_preview_accepts_only_complete_first_receipt(self):
        for record in self.detail[0]['children'][0]['history'][1:]:
            receipt = json.loads(record['output'])['data']
            record['output'] = ('Tool result too large. Saved to /large_tool_results/call_id\n'
                                'Here is a preview:\n     1\t{"receipt": '
                                + json.dumps(receipt) + ', "facts": {"truncated": "')
        self.assertEqual(self.verify()['tool_action_sha'], self.contract['actions'])

    def test_preview_rejects_unanchored_nested_or_incomplete_receipts(self):
        for variant in ('unanchored', 'nested', 'incomplete'):
            with self.subTest(variant=variant):
                self.setUp()
                record = self.detail[0]['children'][0]['history'][1]
                receipt = json.dumps(json.loads(record['output'])['data'])
                if variant == 'unanchored': text = 'Prose contains {"receipt": ' + receipt
                elif variant == 'nested': text = '     1\t{"facts": {"receipt": ' + receipt
                else: text = '     1\t{"receipt": ' + receipt[:-4]
                record['output'] = 'Tool result too large. Here is a preview:\n' + text
                with self.assertRaises(NativeBridgeError): self.verify()

    def test_exact_registered_tool_selection_and_identity_required(self):
        for change in ('selected_key', 'registered_key', 'registered_name', 'failed_record', 'wrong_record_name', 'code_tool'):
            with self.subTest(change=change):
                self.setUp()
                if change == 'selected_key': self.versions[0]['tools'][0]['children'][0]['tool_key'] = 'other'
                elif change == 'registered_key':
                    self.config['tools'][0]['children'][0]['tool_key'] = 'other'
                    self.native_tools[0]['children'][0]['tool_key'] = 'other'
                elif change == 'registered_name':
                    self.config['tools'][0]['children'][0]['name'] = 'other'
                    self.native_tools[0]['children'][0]['name'] = 'other'
                elif change == 'failed_record': self.detail[0]['children'][0]['history'][1]['is_completed'] = False
                else:
                    self.detail[0]['children'][0]['history'][1]['name'] = 'bisheng_code_interpreter' if change == 'code_tool' else 'other'
                with self.assertRaises(NativeBridgeError): self.verify()

    def test_native_permission_scoped_catalog_without_global_defaults(self):
        self.config['tools'] = []
        evidence = self.verify()
        self.assertEqual(evidence['native_tool_id'], 46)
        urls = [call.args[0].full_url for call in self.bridge.opener.open.call_args_list]
        self.assertIn('http://platform.test:3008/api/v1/tool?action=visible&is_preset=0', urls)

    def test_native_fallback_catalog_rejects_wrong_id_owner_or_key(self):
        for change in ('id', 'user_id', 'key', 'group_owner', 'missing'):
            with self.subTest(change=change):
                self.setUp(); self.config['tools'] = []
                if change == 'id': self.native_tools[0]['children'][0]['id'] = 47
                elif change == 'user_id': self.native_tools[0]['children'][0]['user_id'] = 2
                elif change == 'key': self.native_tools[0]['children'][0]['tool_key'] = 'other'
                elif change == 'group_owner': self.native_tools[0]['user_id'] = 2
                else: self.native_tools = []
                with self.assertRaises(NativeBridgeError): self.verify()

    def test_numbered_skill_bytes_with_empty_params(self):
        body = '---\nname: procurement-forecast-fast\n---\nFixture body\n'
        self.contract['skill_sha256'] = hashlib.sha256(body.encode()).hexdigest()
        records = self.detail[0]['children'][0]['history']
        records[0] = {'name': 'read_file', 'params': {},
                      'output': '\n'.join(f'{i}\t{line}' for i, line in enumerate(body.splitlines(), 1))}
        for record in records[1:]:
            output = json.loads(record['output'])
            output['data']['skill_sha256'] = self.contract['skill_sha256']
            record['output'] = json.dumps(output)
        self.assertEqual(self.verify()['status'], 'completed')
        records[0]['output'] += '\n5\tChanged body'
        with self.assertRaises(NativeBridgeError): self.verify()

    def test_missing_server_tool_key_never_falls_back_to_code_proof(self):
        self.bridge = NativeBridge('http://platform.test:3008')
        self.bridge.opener = Mock()
        with self.assertRaises(NativeBridgeError) as error:
            self.bridge.verify('session=test', 'chat-1', 'version-1', self.contract)
        self.assertEqual(error.exception.status_code, 503)
        self.bridge.opener.open.assert_not_called()

    def test_authoritative_version_catalog_and_model_required(self):
        for change in ('status', 'session', 'skill', 'mixed', 'catalog', 'model'):
            with self.subTest(change=change):
                self.setUp()
                if change == 'status': self.versions[0]['status'] = 'in_progress'
                elif change == 'session': self.versions[0]['session_id'] = 'other'
                elif change == 'skill': self.versions[0]['skills'] = []
                elif change == 'mixed': self.versions[0]['skills'].append('procurement-history')
                elif change == 'catalog': self.catalog = []
                elif change == 'model': self.config['models'] = []
                with self.assertRaises(NativeBridgeError): self.verify()

    def test_auth_and_redirect_errors_do_not_expose_cookie(self):
        for status in (401, 403, 302, 500):
            self.bridge.opener = Mock()
            self.bridge.opener.open.side_effect = urllib.error.HTTPError('http://platform.test', status, 'SECRET-FIXTURE', {}, io.BytesIO())
            with self.assertRaises(NativeBridgeError) as caught:
                self.bridge.verify('session=SECRET-FIXTURE', 'chat-1', 'version-1', self.contract)
            self.assertNotIn('SECRET-FIXTURE', str(caught.exception))
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'http://external.test'))

    def test_invalid_contract_and_identifiers_do_not_fetch(self):
        self.bridge.opener = Mock()
        for chat, contract in [('chat/../../', self.contract), ('chat-1', {}), ('chat-1', {**self.contract, 'actions': {}})]:
            with self.assertRaises(NativeBridgeError):
                self.bridge.verify('session=test', chat, 'version-1', contract)
        self.bridge.opener.open.assert_not_called()
        for base in ('http://user:secret@host', 'http://host/?x=1', 'http://host/path', 'file:///tmp'):
            with self.assertRaises(NativeBridgeError): NativeBridge(base)


if __name__ == '__main__':
    unittest.main()
