"""Staged, capability-scoped procurement work; interpretation belongs to the Agent.

The hashes in action receipts identify bytes, not execution. Only the server's
independent native-task verification may release a final report via verify().
"""
from __future__ import annotations
import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import tempfile
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'skill/procurement-forecast-fast/scripts'))
from engine import (GatewayError, build_analytics, merge_months,
                    resolve_scope, summarize_forecast, validate_prediction)
from store import add_month, digest, now_text
from reports import save_report
from adapters import MockHistoryAdapter, select_history


class WorkflowError(Exception):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = self.status_code = status


def _clone(value):
    return copy.deepcopy(value)


def _text(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 12000:
        raise WorkflowError('分析字段无效：' + field)
    return value.strip()


class Workflow:
    TTL = 30 * 60

    def __init__(self, app):
        self.app = app
        if not hasattr(app, 'history_adapter'):
            app.history_adapter = MockHistoryAdapter()
        self.runs = {}
        self.lock = threading.RLock()
        self.runtime = Path(app.runtime)
        self.runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.runtime.chmod(0o700)
        self.audit_path = self.runtime / 'workflow-audit.jsonl'

    def _hashes(self):
        base = HERE / 'skill/procurement-forecast-fast'
        return {'skill_sha256': hashlib.sha256((base / 'SKILL.md').read_bytes()).hexdigest(),
                'cli_sha256': hashlib.sha256((base / 'scripts/run.py').read_bytes()).hexdigest()}

    def _audit(self, run, action, status):
        # Explicit allowlist: never persist capability tokens, prompts or raw payloads.
        event = {'time': now_text(), 'run_id': run['id'], 'action': action,
                 'status': status, 'dataset_sha': run['source']['batch']['dataset_sha']}
        event.update(run.get('hashes', {}))
        fd = os.open(self.audit_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, 'a', encoding='utf-8') as stream:
            os.chmod(self.audit_path, 0o600)
            stream.write(json.dumps(event, ensure_ascii=False) + '\n')

    def _run(self, runid, token):
        # The registry lock is never held during network, disk or run work.
        with self.lock:
            run = self.runs.get(runid)
        if not run or not isinstance(token, str) or not hmac.compare_digest(run['token'], token):
            raise WorkflowError('工作流不存在或凭证无效', 403)
        if time.time() >= run['expires_at']:
            raise WorkflowError('工作流凭证已过期，请重新开始', 410)
        return run

    def create(self, payload):
        if not isinstance(payload, dict):
            raise WorkflowError('参数必须为对象', 400)
        query = payload.get('query', '')
        if not isinstance(query, str) or len(query) > 500:
            raise WorkflowError('查询不得超过500字', 400)
        source = _clone(self.app.store.snapshot())
        if not source.get('batch'):
            raise WorkflowError('月度数据批次尚未就绪', 409)
        default_start = add_month(source['batch']['month'], 1)
        try:
            scope = resolve_scope(query, source, payload.get('spec'), payload.get('customer', 'all'),
                                  payload.get('start_month', default_start), payload.get('months', 12))
        except (ValueError, TypeError) as exc:
            raise WorkflowError(str(exc), 422) from exc
        runid = uuid.uuid4().hex
        run = {'id': runid, 'token': secrets.token_urlsafe(32), 'expires_at': time.time() + self.TTL,
               'created_monotonic': time.monotonic(), 'terminal_error': None,
               'scope': scope, 'source': source, 'snapshot_sha': digest(source), 'successes': {},
               'state': 'created', 'stage': 'scope', 'result': None, 'error': None,
               'predictions': {}, 'hashes': {}, 'facts_ref': None,
               'lock': threading.RLock(), 'status_lock': threading.RLock()}
        self._publish(run)
        self._audit(run, 'create', 'completed')
        with self.lock:
            self.runs[runid] = run
        return {'ok': True, 'run_id': runid, 'token': run['token'], 'scope': _clone(scope)}

    def _check_active(self, run):
        if run['terminal_error'] is not None:
            raise WorkflowError(run['terminal_error'], 408)

    def _publish(self, run):
        # Result objects are replaced rather than mutated after publication.
        # A deadline can be recorded while the run lock is held by slow HTTP.
        with run['status_lock']:
            if run['terminal_error'] is not None:
                run.update(state='timed_out', stage='timeout',
                           error={'stage': 'timeout', 'message': run['terminal_error']})
            run['status'] = {'ok': True, 'run_id': run['id'], 'state': run['state'], 'stage': run['stage'],
                             'facts_ref': run['facts_ref'], 'error': run['error'],
                             'result': run['result'] if run['state'] == 'completed' else None}

    def get(self, runid, token):
        run = self._run(runid, token)
        with run['status_lock']:
            status = run['status']
        return {**_clone(status), 'elapsed_seconds': max(0.0, time.monotonic() - run['created_monotonic'])}

    def expire(self, runid, token, message):
        """Stop publication without waiting for in-flight HTTP; repeated calls are safe."""
        run = self._run(runid, token)
        message = _text(message, 'timeout.message')
        expired = False
        with run['status_lock']:
            if run['state'] != 'completed' and run['terminal_error'] is None:
                run['terminal_error'] = message
                self._publish(run)
                expired = True
        if expired:
            self._audit(run, 'timeout', 'failed')
        return self.get(runid, token)

    def prepare(self, runid, token, payload):
        return self.action(runid, token, 'prepare', payload)

    def _frozen(self, run, current=False):
        if digest(run['source']) != run['snapshot_sha']:
            raise WorkflowError('冻结数据已改变，拒绝继续', 409)
        if current:
            live = self.app.store.snapshot()
            if not live.get('batch') or live['batch']['dataset_sha'] != run['source']['batch']['dataset_sha']:
                raise WorkflowError('数据批次已更新，请创建新工作流', 409)

    def action(self, runid, token, action, payload):
        run = self._run(runid, token)
        self._check_active(run)
        with run['lock']:
            # A queued same-run request can expire while waiting for its turn.
            run = self._run(runid, token)
            self._check_active(run)
            if action == 'prepare':
                # Pure orchestration of the original actions: both independently
                # validated, cached and audited. No interpretation or extra success
                # enters the three-action native verification contract.
                forecast = self.action(runid, token, 'forecast', payload)
                history = self.action(runid, token, 'history', payload)
                with run['status_lock']:
                    self._check_active(run)
                    return {**history, 'action': 'prepare', 'subactions': [forecast, history]}
            if action not in ('forecast', 'history', 'finalize'):
                raise WorkflowError('未知Skill动作', 404)
            frozen_state = run['state'] if run['state'] in ('completed', 'awaiting_native_verification') else None
            try:
                if not isinstance(payload, dict):
                    raise WorkflowError('参数必须为对象', 400)
                hashes = self._hashes()
                if any(payload.get(k) != v for k, v in hashes.items()):
                    raise WorkflowError('Skill或CLI文件哈希不匹配', 409)
                self._frozen(run)
                for key, value in run['scope'].items():
                    if key in payload and payload[key] != value:
                        raise WorkflowError('动作不得更改冻结范围', 409)
                signature = digest(payload)
                old = run['successes'].get(action)
                if old:
                    if old['signature'] != signature:
                        raise WorkflowError('已成功动作的参数不得改变', 409)
                    with run['status_lock']:
                        self._check_active(run)
                        return _clone(old['receipt'])
                if run['state'] in ('completed', 'awaiting_native_verification'):
                    raise WorkflowError('解释已经冻结，不能再次执行动作', 409)
                run['hashes'] = hashes
                run['stage'] = action
                run['error'] = None
                self._publish(run)
                if action == 'forecast':
                    receipt = self._forecast(run)
                elif action == 'history':
                    if 'forecast' not in run['successes']:
                        raise WorkflowError('必须先执行forecast', 409)
                    receipt = self._history(run)
                else:
                    if 'history' not in run['successes']:
                        raise WorkflowError('必须先执行history', 409)
                    receipt = self._finalize(run, payload)
                receipt.update(ok=True, run_id=runid, action=action, action_sha256=signature, **hashes)
                with run['status_lock']:
                    self._check_active(run)
                    run['successes'][action] = {'signature': signature, 'receipt': _clone(receipt)}
                    self._publish(run)
                self._audit(run, action, 'completed')
                return _clone(receipt)
            except (WorkflowError, GatewayError, sqlite3.Error, ValueError, KeyError, TypeError, OSError) as exc:
                if not frozen_state:
                    run['state'] = 'stage_failed'
                    run['stage'] = action
                # Retain prior facts/predictions; a failure never becomes no_history.
                if isinstance(exc, WorkflowError):
                    error = exc
                elif isinstance(exc, GatewayError):
                    error = WorkflowError(str(exc), 502)
                else:
                    error = WorkflowError('工作流动作失败，保留已完成事实', 422)
                run['error'] = {'stage': action, 'message': str(error)}
                self._audit(run, action, 'failed')
                self._publish(run)
                raise error from exc

    def _forecast(self, run):
        external = bool(getattr(self.app, 'forecast_is_external', False))
        self._frozen(run, current=not external)
        s = run['scope']
        for spec in s['specs']:
            # Preserve successful per-material calls if a subsequent call fails.
            if spec in run['predictions']:
                continue
            self._check_active(run)
            raw = self.app.gateway.predict(spec, s['customer'], s['start_month'], s['months'], run['id'])
            self._check_active(run)
            prediction = validate_prediction(raw, spec, s['customer'], s['start_month'], s['months'],
                                             expected_synthetic=None if external else True,
                                             expected_customers=run['source']['customers'])
            if not external and prediction is not None and prediction['dataset_sha'] != run['source']['batch']['dataset_sha']:
                raise WorkflowError('预测使用的数据批次与冻结范围不一致', 409)
            self._frozen(run, current=not external)
            run['predictions'][spec] = _clone(prediction)
        run['state'] = 'forecast_completed'
        return {'state': run['state'], 'scope': _clone(s), 'predictions': _clone(run['predictions']),
                'batch': _clone(run['source']['batch']),
                'provenance': {'execution': 'awaiting_native_verification', **run['hashes']}}

    def _history(self, run):
        source = run['source']; s = run['scope']; specs = s['specs']; customer = s['customer']
        start = s['start_month']; months = s['months']
        end = (date.fromisoformat(add_month(start, months) + '-01') - timedelta(days=1)).isoformat()
        history = self.app.history_adapter.read(source, specs, customer, run['id'])
        self._check_active(run)
        history_provenance = history['provenance']
        items = []
        for spec in specs:
            item_history = select_history(history, source, [spec], customer)
            forecast = _clone(run['predictions'][spec])
            state = 'predicted' if forecast is not None else 'unpredictable' if item_history['records'] else 'no_history'
            reason = ('回测偏差较大，需要人工复核' if forecast and any(r.get('backtest_mape') is not None and r['backtest_mape'] > .3 for r in forecast['monthly'])
                      else '返回可预测结果' if forecast is not None
                      else '预测API返回数字0（拒绝预测）；API未提供具体原因，不能据此判定需求为零。' if item_history['records']
                      else '当前范围无历史样本；预测API返回数字0，需补充数据后离线重新计算。')
            items.append({'spec': spec, 'material': source['materials'].get(spec, {}).get('material', '新增物料'),
                          'status': state, 'unit': '件', 'currency': 'CNY', 'history': item_history,
                          'forecast': forecast, 'reason': reason})
        analytics = build_analytics(history, source, customer)
        for context in analytics['context']:
            if context.get('type') == 'current_order':
                context['is_synthetic'] = history_provenance['is_synthetic']
        if len(specs) > 1:
            analytics['price_trend']['comparison'] += '；多物料加权单价受采购结构影响，不代表同物料涨价。'
        rows = [r for item in items if item['forecast'] for r in item['forecast']['monthly']]
        states = {i['status'] for i in items}
        forecast_shas = sorted({i['forecast']['dataset_sha'] for i in items if i['forecast']})
        forecast_aligned = all(sha == source['batch']['dataset_sha'] for sha in forecast_shas) if forecast_shas else None
        warnings = []
        if history_provenance['history_mode'] != 'mock_sql' or getattr(self.app, 'forecast_is_external', False):
            warnings.append('项目计划和市场上下文仍来自本地模拟资料，尚未接入正式来源。')
        if not history_provenance['history_batch_aligned']:
            warnings.append('历史查询来自独立数据快照，与本地参考批次未对齐；不能宣称同批数据。')
        if forecast_aligned is False:
            warnings.append('预测来自独立数据快照，与本地参考批次未对齐；历史与预测比较需核对口径。')
        forecast = None
        if rows:
            forecast = {'monthly': merge_months(rows), 'summary': summarize_forecast(rows),
                        'quality_notes': list(dict.fromkeys(n for i in items if i['forecast'] for n in i['forecast']['quality_notes'])),
                        'model_version': rows[0]['model_version'],
                        'dataset_sha': forecast_shas[0] if len(forecast_shas) == 1 else None,
                        'input_order_ids': list(dict.fromkeys(oid for i in items if i['forecast'] for oid in i['forecast']['input_order_ids']))}
            forecast['quality_notes'].extend(warnings)
        by_material = [{'spec': i['spec'], 'material': i['material'], 'status': i['status'],
                        'history_quantity': i['history']['summary']['total_quantity'],
                        'forecast_quantity': i['forecast']['summary']['quantity'] if i['forecast'] else None,
                        'forecast_amount': i['forecast']['summary']['amount'] if i['forecast'] else None} for i in items]
        by_customer = []
        for c in source['customers']:
            if customer != 'all' and customer != c:
                continue
            rs = [r for r in rows if r['customer'] == c]; summary = summarize_forecast(rs)
            by_customer.append({'customer': c, 'history_quantity': sum(r['quantity'] for r in history['records'] if r['customer'] == c),
                                'forecast_quantity': summary['quantity'] if rs else None,
                                'forecast_amount': summary['amount'] if rs else None,
                                'unpredictable_items': [i['spec'] for i in items if i['forecast'] is None]})
        by_month = []
        for offset in range(months):
            month = add_month(start, offset); rs = [r for r in rows if r['month'] == month]
            summary = summarize_forecast(rs); hm = add_month(month, -12)
            historical = next((r for r in history['monthly'] if r['month'] == hm), None)
            by_month.append({'month': month, 'history_month': hm, 'history_quantity': historical['quantity'] if historical else None,
                             'forecast_quantity': summary['quantity'] if rs else None,
                             'forecast_unit_price': summary['weighted_unit_price'] if rs else None,
                             'forecast_amount': summary['amount'] if rs else None})
        steps = [{'id': 'scope', 'title': '冻结物料、客户与月份范围', 'status': 'completed', 'detail': '同次工作流使用冻结数据'},
                 {'id': 'forecast', 'title': 'Skill调用月度预测HTTP API', 'status': 'completed', 'detail': '逐物料校验模型原值和批次'},
                 {'id': 'history', 'title': 'Skill查询历史与统计事实', 'status': 'completed', 'detail': f"{history['summary']['record_count']}笔完整样本"}]
        result = {'ok': True, 'request_id': run['id'], 'status': next(iter(states)) if len(states) == 1 else 'mixed',
                  'message': '', 'scope': _clone(s), 'spec': specs[0] if len(specs) == 1 else '全部物料',
                  'material': items[0]['material'] if len(specs) == 1 else '多物料分析', 'customer': customer, 'unit': '件', 'currency': 'CNY',
                  'period': {'key': 'monthly', 'label': f'{start} 至 {end[:7]}（逐月）', 'start': start + '-01',
                             'end': end, 'start_month': start, 'months': months},
                  'history': history, 'forecast': forecast, 'items': items, 'analytics': analytics,
                  'report_dimensions': {'by_material': by_material, 'by_customer': by_customer, 'by_month': by_month,
                                        'suggestions': [], 'excluded_specs': [i['spec'] for i in items if i['forecast'] is None]},
                  'explanation': None, 'steps': steps, 'reports': None, 'generated_at': now_text(), 'batch': _clone(source['batch']),
                  'provenance': {'is_synthetic': True, 'label': source['label'], 'cutoff': source['cutoff'],
                                 'dataset_sha': source['batch']['dataset_sha'],
                                 'history_source': history_provenance['history_source'],
                                 'history_mode': history_provenance['history_mode'],
                                 'history_query_id': history_provenance['query_id'],
                                 'history_is_synthetic': history_provenance['is_synthetic'],
                                 'history_dataset_sha': history_provenance['history_dataset_sha'],
                                 'history_batch_aligned': history_provenance['history_batch_aligned'],
                                 'forecast_mode': 'external_http' if getattr(self.app, 'forecast_is_external', False) else 'mock_http',
                                 'forecast_is_synthetic': any(r['is_synthetic'] for r in rows) if rows else None,
                                 'forecast_dataset_sha': forecast_shas[0] if len(forecast_shas) == 1 else None,
                                 'forecast_dataset_shas': forecast_shas, 'forecast_batch_aligned': forecast_aligned,
                                 'data_warnings': warnings,
                                 'forecast_source': '外部预测HTTP API' if getattr(self.app, 'forecast_is_external', False) else '模拟时序模型HTTP API', 'analysis_source': '等待独立核验平台Agent执行',
                                 'execution': 'awaiting_native_verification', **run['hashes']}}
        evidence = sorted({r['source_id'] for r in history['records']} | {r['prediction_id'] for r in rows}
                          | {x['id'] for x in analytics['context']} | {'STAT-DELIVERY', 'STAT-CUSTOMER', 'STAT-QUANTITY', 'STAT-PRICE'})
        targets = []
        for spec, c in sorted({(r['spec'], r['customer']) for r in rows}):
            rs = [r for r in rows if r['spec'] == spec and r['customer'] == c]; summary = summarize_forecast(rs)
            targets.append({'spec': spec, 'customer': c, 'quantity': summary['quantity'], 'amount': summary['amount'],
                            'period': result['period']['label'], 'evidence_refs': [r['prediction_id'] for r in rs]})
        run.update(result=result, facts_ref=digest(result), evidence_refs=evidence, suggestion_targets=targets, state='history_completed')
        return {'state': run['state'], 'facts_ref': run['facts_ref'], 'facts': _clone(result),
                'evidence_refs': evidence, 'suggestion_targets': targets}

    def _refs(self, record, valid):
        refs = record.get('evidence_refs')
        if not isinstance(refs, list) or not refs or any(not isinstance(r, str) or r not in valid for r in refs):
            raise WorkflowError('解释必须引用本次事实中存在的非空证据')
        if len(refs) != len(set(refs)):
            raise WorkflowError('证据引用不能重复')
        return refs

    def _finalize(self, run, payload):
        if payload.get('facts_ref', run['facts_ref']) != run['facts_ref']:
            raise WorkflowError('解释引用的事实版本不匹配', 409)
        explanation = payload.get('explanation', {k: v for k, v in payload.items() if k not in ('skill_sha256', 'cli_sha256', 'facts_ref')})
        if not isinstance(explanation, dict):
            raise WorkflowError('必须提交Agent撰写的解释')
        allowed = {'headline', 'body', 'factors', 'limitations', 'influences', 'suggestions', 'analysis_model', 'analysis_source_id'}
        if set(explanation) - allowed:
            raise WorkflowError('解释包含不允许的字段，不能覆盖事实')
        clean = {k: _text(explanation.get(k), k) for k in ('headline', 'body')}
        for field in ('factors', 'limitations', 'influences', 'suggestions'):
            if not isinstance(explanation.get(field), list):
                raise WorkflowError('分析列表字段无效：' + field)
        if not explanation['factors'] or not explanation['limitations'] or not explanation['influences']:
            raise WorkflowError('解释必须包含因素、限制和证据影响')
        clean['factors'] = []
        for factor in explanation['factors']:
            if not isinstance(factor, dict):
                raise WorkflowError('因素必须为对象')
            clean['factors'].append({k: _text(factor.get(k), k) for k in ('title', 'value', 'detail')})
        clean['limitations'] = [_text(x, 'limitations') for x in explanation['limitations']]
        price=run['result']['analytics']['price_trend']
        if price['previous'] is None or price['current'] is None:
            # Known failure slice: a missing price observation is not zero change.
            # Reject the assertion before releasing any narrative/report; keep
            # the original facts available for a fresh Agent run.
            narrative='\n'.join([clean['headline'],clean['body']]+[str(v) for f in explanation['factors'] for v in f.values()]+[str(f.get('detail','')) for f in explanation['influences'] if isinstance(f,dict)])
            assertions=re.finditer(r'(?:价格|单价)[^。；\n]{0,12}(?:环比|同比|变化|变动)[^。；\n]{0,6}(?:均为|等于|为|是)\s*(?:0(?:\.0+)?%?|零)',narrative)
            if any(not re.search(r'不|非|无',m.group()) for m in assertions):
                raise WorkflowError('历史价格趋势缺少观测值，解释不得写为零变化；请明确无法计算')
        clean['limitations'].extend(x for x in run['result']['provenance']['data_warnings'] if x not in clean['limitations'])
        clean['influences'] = []
        valid = set(run['evidence_refs'])
        for influence in explanation['influences']:
            if not isinstance(influence, dict):
                raise WorkflowError('影响必须为对象')
            clean['influences'].append({'title': _text(influence.get('title'), 'title'),
                                        'detail': _text(influence.get('detail'), 'detail'),
                                        'evidence_refs': self._refs(influence, valid)})
        targets = {(t['spec'], t['customer']): t for t in run['suggestion_targets']}; seen = set(); suggestions = []
        for suggestion in explanation['suggestions']:
            if not isinstance(suggestion, dict):
                raise WorkflowError('建议必须为对象')
            if set(suggestion) - {'spec', 'customer', 'reason', 'evidence_refs', 'quantity', 'amount', 'period'}:
                raise WorkflowError('建议包含未知数值或范围字段')
            key = (suggestion.get('spec'), suggestion.get('customer'))
            if key not in targets or key in seen:
                raise WorkflowError('建议范围重复或不是可预测物料客户')
            target = targets[key]; seen.add(key)
            for field in ('quantity', 'amount', 'period'):
                if field in suggestion and (type(suggestion[field]) is bool or suggestion[field] != target[field]):
                    raise WorkflowError('解释不得修改预测数量、金额或期间')
            refs = self._refs(suggestion, valid)
            if not set(refs).intersection(target['evidence_refs']):
                raise WorkflowError('建议必须引用对应物料和客户的预测证据')
            foreign = {r for t in targets.values() if (t['spec'], t['customer']) != key for r in t['evidence_refs']}
            if foreign.intersection(refs):
                raise WorkflowError('建议不得引用其他物料或客户的预测证据')
            suggestions.append({k: _clone(target[k]) for k in ('spec', 'customer', 'quantity', 'amount', 'period')}
                               | {'reason': _text(suggestion.get('reason'), 'reason'), 'evidence_refs': refs})
        if seen != set(targets):
            raise WorkflowError('建议必须完整覆盖每个可预测物料和客户')
        for field in ('analysis_model', 'analysis_source_id'):
            if field in explanation:
                clean[field] = _text(explanation[field], field)
        clean.setdefault('analysis_model', '待平台任务独立核验')
        clean.setdefault('analysis_source_id', 'AGENT-' + run['id'])
        result = _clone(run['result']); result['explanation'] = clean
        result['report_dimensions']['suggestions'] = suggestions
        result['message'] = clean['headline']
        result['steps'].append({'id': 'analysis', 'title': 'Agent提交基于证据的解释与建议', 'status': 'completed',
                                'detail': '输出已校验；等待平台执行独立核验'})
        run.update(result=result, state='awaiting_native_verification')
        return {'state': run['state'], 'facts_ref': run['facts_ref'], 'final_sha256': digest(result), 'reports': None}

    def verification_contract(self, runid, token):
        """Byte identities to match against independently read platform tool outputs."""
        run = self._run(runid, token)
        with run['lock']:
            run = self._run(runid, token)
            return {**run['hashes'],
                    'actions': {name: item['receipt']['action_sha256']
                                for name, item in run['successes'].items()}}

    def verify(self, runid, token, native_evidence, *, deadline=None):
        """Server-only entry point AFTER independent authoritative task inspection.

        No HTTP client-supplied field can prove native execution. The HTTP server
        must keep this method behind its own platform-status verifier.
        """
        run = self._run(runid, token)
        self._check_active(run)
        with run['lock']:
            run = self._run(runid, token)
            if run['state'] == 'completed':
                return self.get(runid, token)
            self._check_active(run)
            if run['state'] != 'awaiting_native_verification':
                raise WorkflowError('尚未完成解释校验，不能生成报告', 409)
            self._frozen(run)
            if self._hashes() != run['hashes']:
                raise WorkflowError('执行后Skill文件已改变，不能核验', 409)
            if not isinstance(native_evidence, dict) or any(not native_evidence.get(k) for k in ('chat_id', 'session_version_id', 'model', 'tool_action_sha')):
                raise WorkflowError('平台原生执行证据不完整', 409)
            contract = self.verification_contract(runid, token)
            if native_evidence['tool_action_sha'] != contract['actions']:
                raise WorkflowError('平台工具执行与工作流动作回执不匹配', 409)
            # Only explicit metadata is retained, never a raw task transcript/token.
            allowed = ('chat_id', 'session_version_id', 'model', 'model_id', 'model_name', 'skill_catalog_hash', 'tool_action_sha', 'task_detail_sha256', 'execution_tool', 'native_tool_key', 'native_tool_id', 'verified_at', 'status', 'completion_gate')
            evidence = {k: _clone(native_evidence[k]) for k in allowed if k in native_evidence}
            result = _clone(run['result'])
            result['explanation']['analysis_model'] = _text(native_evidence.get('model_name') or native_evidence['model'], 'native.model')
            result['explanation']['analysis_source_id'] = 'NATIVE-' + str(native_evidence['chat_id'])
            result['provenance'].update(execution='native_verified', native_agent=evidence,
                                        analysis_source='平台真实Agent + procurement-forecast-fast Skill')
            result['steps'].append({'id': 'report', 'title': '按物料、客户、月份生成报告', 'status': 'completed',
                                    'detail': '平台执行已独立核验；数量与金额引用已校验事实'})
            # The HTTP report route can read files without the cache. Generate in
            # a private staging directory so an expired run cannot expose files
            # produced by an already-running renderer after its deadline.
            with tempfile.TemporaryDirectory(prefix='.pending-report-', dir=self.runtime) as staging:
                blobs = save_report(result, staging, getattr(self.app, 'public_prefix', ''))
                staged = Path(staging) / runid
                staged.chmod(0o700)
                for name in blobs:
                    (staged / name).chmod(0o600)
                with run['status_lock']:
                    if deadline is not None and time.monotonic()>=deadline:
                        self.expire(runid,token,'分析超过30秒预算；本次未生成已核验报告。')
                    self._check_active(run)
                    directory = self.runtime / 'reports'
                    directory.mkdir(mode=0o700, exist_ok=True)
                    directory.chmod(0o700)
                    staged.replace(directory / runid)
                    for name, blob in blobs.items():
                        self.app.report_cache[(runid, name)] = blob
                    run.update(result=result, state='completed', stage='completed', error=None)
                    self._publish(run)
            self._audit(run, 'native_verify', 'completed')
            return self.get(runid, token)
