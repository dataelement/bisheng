"""History integration boundary, independent of Skill credentials or model code.

FORECAST_HISTORY_URL selects a future normalized NL2SQL HTTP service; absent it,
MockHistoryAdapter explicitly runs fixture SQLite and makes no NL2SQL claim.

POST contract:
  {request_id, scope:{specs,customer,window},
   snapshot:{dataset_sha,version,cutoff}}
Response:
  {ok:true, request_id, scope:(exact echo), dataset_sha, window:(exact echo),
   complete:true, records:[normalized order records],
   source:{mode:'nl2sql',query_id:(nonempty),is_synthetic:(explicit bool),label:(nonempty)}}
Units are 件/CNY. The request snapshot is the local reference batch. An external response owns
its dataset_sha: differing hashes are recorded as unaligned history, never
relabeled as the local batch. Scope/window/completeness still must match.
Returned monthly/summary/amount/lead-day values are never trusted as aggregates.
"""
from __future__ import annotations
import copy
import http.client
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'skill/procurement-forecast-fast/scripts'))
from engine import GatewayError, HistoryRepository, money


class HistoryAdapterError(GatewayError):
    pass


def _string(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise HistoryAdapterError('历史数据字段无效：' + field)
    return value


def _date(value, field, optional=False):
    if optional and value is None:
        return None
    if not isinstance(value, str):
        raise HistoryAdapterError('历史日期无效：' + field)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise HistoryAdapterError('历史日期无效：' + field) from exc
    if parsed.isoformat() != value:
        raise HistoryAdapterError('历史日期格式无效：' + field)
    return value


def _scope(source, specs, customer):
    return {'specs': list(specs), 'customer': customer, 'window': copy.deepcopy(source['window'])}


def _aggregate(source, records, specs, customer, provenance):
    clean_source = {**source, 'records': records}
    history = HistoryRepository(clean_source).read(specs, customer)
    history['provenance'] = copy.deepcopy(provenance)
    return history


def select_history(history, source, specs, customer):
    """Recompute an item's statistics from already validated adapter records."""
    return _aggregate(source, history['records'], specs, customer, history['provenance'])


def normalize_history(payload, source, specs, customer, request_id, expected_mode):
    """Reject partial/out-of-scope rows and recompute every deterministic statistic."""
    if not isinstance(payload, dict) or payload.get('ok') is not True or payload.get('complete') is not True:
        raise HistoryAdapterError('历史服务未明确返回完整结果，不能视为无历史')
    if payload.get('request_id') != request_id or payload.get('scope') != _scope(source, specs, customer):
        raise HistoryAdapterError('历史服务请求范围不匹配')
    dataset_sha = _string(payload.get('dataset_sha'), 'dataset_sha')
    if payload.get('window') != source['window']:
        raise HistoryAdapterError('历史服务与冻结窗口不一致')
    if expected_mode == 'mock_sql' and dataset_sha != source['batch']['dataset_sha']:
        raise HistoryAdapterError('模拟历史与冻结批次不一致')
    metadata = payload.get('source')
    if not isinstance(metadata, dict) or metadata.get('mode') != expected_mode:
        raise HistoryAdapterError('历史服务来源模式不匹配')
    query_id = _string(metadata.get('query_id'), 'query_id')
    label = _string(metadata.get('label'), 'source.label')
    synthetic = metadata.get('is_synthetic')
    if type(synthetic) is not bool or (expected_mode == 'mock_sql' and synthetic is not True):
        raise HistoryAdapterError('历史来源必须明确标识真实查询或模拟SQLite')
    rows = payload.get('records')
    if not isinstance(rows, list) or len(rows) > 100000:
        raise HistoryAdapterError('历史记录格式无效或超过限制')
    records = []; seen_orders = set(); seen_sources = set()
    fields = ('order_id', 'spec', 'material', 'customer', 'supplier', 'source_id')
    for raw in rows:
        if not isinstance(raw, dict):
            raise HistoryAdapterError('历史记录必须为对象')
        row = {field: _string(raw.get(field), field) for field in fields}
        if row['spec'] not in specs or row['customer'] not in source['customers'] or (customer != 'all' and row['customer'] != customer):
            raise HistoryAdapterError('历史记录超出物料或客户范围')
        if row['order_id'] in seen_orders or row['source_id'] in seen_sources:
            raise HistoryAdapterError('历史订单或证据ID重复')
        seen_orders.add(row['order_id']); seen_sources.add(row['source_id'])
        row['date'] = _date(raw.get('date'), 'date')
        if not source['window']['start'] <= row['date'] <= source['window']['end']:
            raise HistoryAdapterError('历史订单超出冻结日期窗口')
        for field in ('quantity', 'unit_price'):
            value = raw.get(field)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1e12:
                raise HistoryAdapterError('历史数量或单价无效')
            row[field] = value
        if raw.get('unit') != '件' or raw.get('currency') != 'CNY':
            raise HistoryAdapterError('历史数据单位或币种不匹配')
        expected_amount = money(Decimal(str(row['quantity'])) * Decimal(str(row['unit_price'])))
        if 'amount' in raw and (type(raw['amount']) not in (int, float) or not math.isfinite(raw['amount']) or raw['amount'] != expected_amount):
            raise HistoryAdapterError('历史订单金额与数量单价不一致')
        for field in ('expected_delivery_date', 'actual_delivery_date'):
            row[field] = _date(raw.get(field), field, optional=True)
            if row[field] is not None and row[field] < row['date']:
                raise HistoryAdapterError('交付日期不能早于订单日期')
        records.append(row)
    provenance = {'history_mode': expected_mode, 'history_source': label,
                  'query_id': query_id, 'is_synthetic': synthetic,
                  'history_dataset_sha': dataset_sha,
                  'history_batch_aligned': dataset_sha == source['batch']['dataset_sha']}
    return _aggregate(source, records, specs, customer, provenance)


class MockHistoryAdapter:
    mode = 'mock_sql'

    def read(self, source, specs, customer, request_id):
        history = HistoryRepository(source).read(specs, customer)
        return normalize_history({**history, 'ok': True, 'request_id': request_id,
                                  'scope': _scope(source, specs, customer),
                                  'dataset_sha': source['batch']['dataset_sha'],
                                  'source': {'mode': self.mode, 'query_id': 'MOCK-SQL-' + request_id,
                                             'is_synthetic': True, 'label': '冻结模拟订单 + 本地SQLite（非原生NL2SQL）'}},
                                 source, specs, customer, request_id, self.mode)


class HttpHistoryAdapter:
    mode = 'nl2sql'

    def __init__(self, url, timeout=10):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
            raise ValueError('无效历史服务地址；凭据不得嵌入URL')
        self.url = url
        self.timeout = timeout

    def read(self, source, specs, customer, request_id):
        payload = {'request_id': request_id, 'scope': _scope(source, specs, customer),
                   'snapshot': {'dataset_sha': source['batch']['dataset_sha'],
                                'version': source['batch']['version'], 'cutoff': source['cutoff']}}
        request = urllib.request.Request(self.url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                                         headers={'Content-Type': 'application/json', 'X-Request-ID': request_id})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(10_000_001)
                if len(raw) > 10_000_000:
                    raise HistoryAdapterError('历史服务回包超过限制')
                value = json.loads(raw)
        except urllib.error.HTTPError as exc:
            raise HistoryAdapterError('历史服务调用失败：HTTP ' + str(exc.code)) from exc
        except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError, ValueError, http.client.HTTPException) as exc:
            raise HistoryAdapterError('历史服务调用失败：超时或无效回包') from exc
        return normalize_history(value, source, specs, customer, request_id, self.mode)


def history_adapter_from_env():
    url = os.environ.get('FORECAST_HISTORY_URL', '').strip()
    return HttpHistoryAdapter(url) if url else MockHistoryAdapter()
