#!/usr/bin/env python3
"""Single-model batch processing and persisted local conversation views. No network."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile

import query_orders as engine
import qualification_lookup
from import_api_response import unique_object

STATE_JSON_MAX = 65536

FILTERS = {'supplier', 'customer', 'date_from', 'date_to', 'currency', 'unit',
           'incoterms', 'incoterms_place'}
KEYS = {'action', 'model', 'set', 'unset', 'sort', 'page', 'page_size', 'positions', 'line_ids', 'purchaser'}


def json_read(path, maximum=25 * 1024 * 1024):
    data = Path(path).read_bytes()
    if len(data) > maximum:
        raise engine.Stop('file_error', '本地JSON文件超过读取预算。')
    return json.loads(data, object_pairs_hook=unique_object,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x))), data


def load_batch(path):
    b, data = json_read(path)
    if not isinstance(b, dict) or b.get('schema_version') != 1:
        raise engine.Stop('schema_error', '不支持的单型号批次结构。')
    if not isinstance(b.get('model'), str) or not b['model'].strip():
        raise engine.Stop('schema_error', '批次缺少明确型号。')
    if b.get('complete') is not True:
        raise engine.Stop('incomplete_batch', '当前批次未完整取得；请补齐后再分析完整结果。')
    columns, rows, source_rows = b.get('columns'), b.get('rows'), b.get('source_rows')
    if not isinstance(columns, list) or not isinstance(rows, list) or not isinstance(source_rows, list):
        raise engine.Stop('schema_error', '批次需包含columns、rows和source_rows数组。')
    if len(rows) > 100000 or len(columns) * len(rows) > 2000000:
        raise engine.Stop('file_error', '批次超过本地初版处理预算。')
    if type(b.get('total_records')) is not int or b['total_records'] != len(rows) or len(source_rows) != len(rows):
        raise engine.Stop('incomplete_batch', '批次行数与声明总数不一致。')
    if any(type(v) is not int or v < 2 for v in source_rows) or len(set(source_rows)) != len(source_rows):
        raise engine.Stop('data_integrity_error', '原始行引用无效或重复。')
    for name, (index, label) in engine.FIELDS.items():
        if index >= len(columns) or columns[index] != label:
            raise engine.Stop('schema_error', '批次字段位置或名称不符：' + name)
    records = []
    for row, source_row in zip(rows, source_rows):
        if not isinstance(row, list) or len(row) != len(columns):
            raise engine.Stop('schema_error', '返回行宽与表头不一致。')
        if any(isinstance(v, (list, dict)) for v in row):
            raise engine.Stop('schema_error', '单元格必须是标量，不能包含嵌套结构。')
        r = engine.normalize_record(row, source_row)
        if engine.norm(r['model'] or '') != engine.norm(b['model']):
            raise engine.Stop('model_mismatch', '返回批次混入其他型号或缺少型号。')
        records.append(r)
    engine.validate_records(records, reconcile_order_totals=False)
    dates = sorted(engine.as_date(r['confirmed_at']) for r in records if engine.as_date(r['confirmed_at']))
    origin = b.get('provenance', {})
    if not isinstance(origin, dict):
        raise engine.Stop('schema_error', '批次来源需为对象。')
    source = {'file': Path(path).name, 'source_sha256': hashlib.sha256(data).hexdigest(),
              'model': b['model'], 'complete': True, 'data_rows': len(records),
              'scope': 'single_model_mock_response_from_authorized_excel_not_live_api',
              'origin_file': origin.get('file'), 'origin_sha256': origin.get('sha256'),
              'sheet': origin.get('sheet'),
              'confirmation_date_from': str(dates[0]) if dates else None,
              'confirmation_date_to': str(dates[-1]) if dates else None}
    return records, source


def save_state(path, state):
    raw = (json.dumps(state, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode('utf-8')
    is_state = isinstance(state, dict) and state.get('version') == 1 and ('filters' in state or 'entries' in state)
    if is_state and len(raw) > STATE_JSON_MAX:
        raise engine.Stop('state_budget_exceeded', '会话状态超过容量限制；未写入无法恢复的状态。')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.session-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(raw)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run(batch_path, session_path, raw, qualification_index=None):
    try:
        if Path(batch_path).resolve() == Path(session_path).resolve():
            raise engine.Stop('invalid_request', '原始批次与会话状态必须使用不同文件。')
        if not isinstance(raw, dict) or set(raw) - KEYS:
            raise engine.Stop('invalid_request', '请求包含未知字段或不是对象。')
        action = raw.get('action', 'show')
        if action not in {'load', 'history', 'show', 'filter', 'reset', 'compare', 'suppliers'}:
            raise engine.Stop('unsupported', '当前支持加载、查询、筛选、比较及供应商选取。')
        if 'purchaser' in raw and (action not in {'load', 'history', 'show', 'filter', 'suppliers'} or
                not isinstance(raw['purchaser'], str) or not 0 < len(raw['purchaser'].strip()) <= 100):
            raise engine.Stop('invalid_request', '本次甲方须为明确名称，可用于加载、展示、筛选或供应商动作。')
        if action == 'load' and not raw.get('model'):
            raise engine.Stop('needs_clarification', '请提供需要查询的完整规格型号。')
        if 'model' in raw and (not isinstance(raw['model'], str) or not raw['model'].strip()):
            raise engine.Stop('invalid_request', '型号必须为非空文本。')
        if ('set' in raw or 'unset' in raw) and action not in {'filter', 'history'}:
            raise engine.Stop('invalid_request', 'set/unset只用于筛选或历史查询，不能静默忽略。')
        if ('positions' in raw or 'line_ids' in raw) and action != 'compare':
            raise engine.Stop('invalid_request', '选择参数只用于比较。')
        if action == 'compare' and any(k in raw for k in ('sort', 'page', 'page_size')):
            raise engine.Stop('invalid_request', '比较引用上一有效展示；排序或翻页应先单独执行。')
        records, source = load_batch(batch_path)
        old = None
        if Path(session_path).exists():
            old, _ = json_read(session_path, STATE_JSON_MAX)
            if not isinstance(old, dict) or old.get('version') != 1 or not isinstance(old.get('filters'), dict):
                raise engine.Stop('session_error', '会话状态不可读取。')
            if set(old['filters']) - FILTERS:
                raise engine.Stop('session_error', '会话包含未支持的筛选字段。')
        if action != 'load' and old is None:
            raise engine.Stop('needs_clarification', '请先按完整型号加载查询结果。')
        if action != 'load' and old['batch_sha256'] != source['source_sha256']:
            raise engine.Stop('stale_source', '批次已变化，请重新加载后再选择记录。')
        model = raw.get('model', source['model'] if action == 'load' else old['model'])
        if engine.norm(model) != engine.norm(source['model']):
            raise engine.Stop('needs_new_batch', '当前批次仅包含另一型号；请取得所需型号的新批次。')
        state = deepcopy(old) if old else {'version': 1, 'filters': {}, 'sort': 'time_desc', 'page_size': 20}
        if 'purchaser' in raw:
            if raw['purchaser'].strip() != state.get('purchaser') and 'page' not in raw:
                state['page'] = 1
            state['purchaser'] = raw['purchaser'].strip()
        if action == 'load':
            state.update(model=source['model'], batch_sha256=source['source_sha256'], displayed=[], page=1)
        if action == 'reset':
            state.update(filters={}, sort='time_desc', page=1)
        if action == 'filter' or (action == 'history' and ('set' in raw or 'unset' in raw)):
            update, remove = raw.get('set', {}), raw.get('unset', [])
            if not isinstance(update, dict) or set(update) - FILTERS:
                raise engine.Stop('invalid_request', '筛选字段不受支持。')
            if not isinstance(remove, list) or any(not isinstance(k, str) or k not in FILTERS for k in remove):
                raise engine.Stop('invalid_request', '取消的筛选字段不受支持。')
            if set(update) & set(remove):
                raise engine.Stop('invalid_request', '不能同时设置并取消同一条件。')
            state['filters'].update(update)
            for key in remove:
                state['filters'].pop(key, None)
            state['page'] = 1
        view = 'suppliers' if action == 'suppliers' else 'history' if action in {'load', 'history', 'compare'} else state.get('view', 'history')
        if state.get('view', 'history') != view and 'page' not in raw:
            state['page'] = 1
        state['view'] = view
        for key in ('sort', 'page_size', 'page'):
            if key in raw:
                state[key] = raw[key]
        if ('sort' in raw or 'page_size' in raw) and 'page' not in raw:
            state['page'] = 1
        q = {'model': state['model'], **state['filters'], 'sort': state['sort'],
             'page': state['page'], 'page_size': state['page_size']}
        if view == 'suppliers':
            q['intent'] = 'suppliers'
        if action == 'compare':
            shown = state.get('displayed', [])
            positions, ids = raw.get('positions'), raw.get('line_ids')
            if (positions is None) == (ids is None):
                raise engine.Stop('needs_clarification', '请选择上一展示中的2—10条明细位置或明细标识。')
            if positions is not None:
                if not isinstance(positions, list) or any(type(x) is not int or not 1 <= x <= len(shown) for x in positions):
                    raise engine.Stop('invalid_selection', '位置不属于上一有效展示。')
                selected = [shown[x - 1] for x in positions]
            else:
                if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids):
                    raise engine.Stop('invalid_selection', '明细标识必须是文本数组。')
                by_id = {r['line_id']: r for r in shown}
                if any(x not in by_id for x in ids):
                    raise engine.Stop('invalid_selection', '所选明细不属于上一有效展示。')
                selected = [by_id[x] for x in ids]
            q.update(intent='compare', rows=[r['source_row'] for r in selected],
                     source_sha256=state['batch_sha256'])
        excluded, excluded_count, historical_count, qualification_cache = [], 0, 0, {}
        index = qualification_lookup.load(qualification_index) if view == 'suppliers' and qualification_index and \
            qualification_lookup.route(state.get('purchaser')) in {'qpl', 'qsl'} else None

        def select_supplier(supplier, matched):
            nonlocal excluded_count, historical_count
            historical_count += 1
            rows = set(supplier['evidence_rows'])
            manufacturers = sorted({r['manufacturer_name'] for r in matched
                                    if r['source_row'] in rows and r['manufacturer_name']})
            key = (tuple(supplier['supplier_names']), tuple(manufacturers))
            if key not in qualification_cache:
                qualification_cache[key] = qualification_lookup.lookup(
                    index, state.get('purchaser'), supplier['supplier_names'], manufacturers)
            qualification = deepcopy(qualification_cache[key])
            supplier['qualification'] = qualification
            if qualification.get('whitelist_status') in {'listed', 'not_requested', 'not_required'}:
                return True
            excluded_count += 1
            if len(excluded) < 20:
                excluded.append({'supplier_id': supplier['supplier_id'],
                                 'supplier_names': supplier['supplier_names'], 'qualification': qualification})
            return False

        result = engine.query_records(records, source, q,
                                      supplier_selector=select_supplier if view == 'suppliers' else None)
        if result['status'] not in {'ok', 'no_records'}:
            return result
        if view == 'suppliers':
            # Material text of the whole batch feeds catalog recommendation; values stay as given.
            materials = sorted({str(r[k]) for r in records for k in ('material_name', 'grade', 'technical_spec') if r.get(k)})
            result.update(purchaser=state.get('purchaser'), materials=materials[:20],
                          historical_supplier_groups=historical_count,
                          excluded_supplier_groups=excluded_count,
                          excluded_suppliers=excluded,
                          excluded_suppliers_truncated=excluded_count > len(excluded))
        result['purchaser'] = state.get('purchaser')
        result['view'] = view
        state['displayed'] = [{'line_id': r['line_id'], 'source_row': r['source_row']}
                              for r in result.get('records', [])]
        save_state(session_path, state)
        result['active_filters'] = state['filters']
        result['original_batch_records'] = len(records)
        result['action'] = action
        return result
    except engine.Stop as e:
        return {'version': engine.VERSION, 'status': e.status, 'message': e.message}
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        return {'version': engine.VERSION, 'status': 'file_or_state_error',
                'message': '批次、会话或请求无法读取；未替换有效会话状态。'}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--batch', required=True)
    p.add_argument('--session', required=True)
    p.add_argument('--request-file')
    p.add_argument('--qualification-index', help='Executor-bound local QSL/QPL index')
    args = p.parse_args()
    try:
        if args.request_file:
            raw, _ = json_read(args.request_file, 65536)
        else:
            import sys
            raw = json.loads(sys.stdin.read(65537))
        result = run(args.batch, args.session, raw, args.qualification_index)
    except (OSError, ValueError):
        result = {'status': 'invalid_request', 'message': '请求JSON无法读取。'}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
