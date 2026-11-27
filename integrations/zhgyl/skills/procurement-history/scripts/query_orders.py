#!/usr/bin/env python3
"""Read-only procurement evidence query. No network, generated SQL or workbook writes."""
import argparse
from copy import deepcopy
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import sys
import unicodedata
import zipfile

VERSION = '0.2.0'
# Zero-based source position + exact header; repeated display names never become dict keys.
FIELDS = {
    'order_id': (0, '主键'), 'order_no': (1, '订单号'),
    'supplier_id': (5, '供应商标识'), 'supplier_name': (6, '供应商名称'),
    'manufacturer_id': (7, '制造商标识'), 'manufacturer_name': (8, '制造商名称'),
    'currency': (9, '币种'), 'header_total': (11, '订单总价'),
    'incoterms': (14, 'incoterms'), 'incoterms_place': (15, 'incoterms引申字段'),
    'confirmed_at': (24, '确认时间'), 'line_id': (77, '订单明细主表'),
    'customer_id': (29, '客户标识'), 'customer_name': (30, '客户名单'),
    'order_fk': (78, '订单主键外键'), 'line_order_no': (79, '订单号'),
    'line_no': (80, '订单行号'), 'group_code': (84, '集团统一编码'),
    'material_code': (85, '物料编码'), 'material_name': (86, '物料名称'),
    'model': (87, '规格型号'), 'grade': (88, '牌号/描述'),
    'technical_spec': (89, '技术规范'), 'unit': (93, '单位'),
    'quantity': (94, '数量'), 'unit_price': (95, '单价'), 'line_amount': (96, '金额'),
}
CONDITIONS = ('currency', 'unit', 'incoterms', 'incoterms_place')
ALLOWED = {'intent', 'model', 'supplier', 'date_from', 'date_to', 'currency',
           'unit', 'customer', 'incoterms', 'incoterms_place',
           'sort', 'page', 'page_size', 'rows', 'source_sha256'}


class Stop(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def norm(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value)).split()).casefold()


def text(value):
    return None if value is None or str(value).strip() == '' else str(value).strip()


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        raw = str(value).strip()
        if len(raw) > 200:
            return None
        result = Decimal(raw)
        if not result.is_finite() or len(result.as_tuple().digits) > 50:
            return None
        # Technical budget, not a business limit; keep raw input and expose INVALID_*.
        return result if not result or -40 <= result.adjusted() <= 40 else None
    except (InvalidOperation, ValueError):
        return None


def source_datetime(value):
    """Parse source timestamps consistently on Python 3.8+ (Excel uses '.0')."""
    if isinstance(value, datetime):
        return value
    raw = str(value).strip()
    match = re.fullmatch(r'(.*[T ]\d{2}:\d{2}:\d{2})\.(\d{1,6})([+-]\d{2}:\d{2}|Z)?', raw)
    if match:
        raw = match[1] + '.' + match[2].ljust(6, '0') + (match[3] or '')
    if raw.endswith('Z'):
        raw = raw[:-1] + '+00:00'
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def as_date(value):
    if isinstance(value, date):
        return value.date() if isinstance(value, datetime) else value
    parsed = source_datetime(value)
    return parsed.date() if parsed else None


def time_key(value):
    """Sort the source's local clock; never invent a timezone for a naive timestamp."""
    dt = source_datetime(value)
    return (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond) if dt else (0, 0, 0, 0, 0, 0, 0)


def request(raw):
    if not isinstance(raw, dict):
        raise Stop('invalid_request', '请求必须是JSON对象。')
    unknown = set(raw) - ALLOWED
    if unknown:
        raise Stop('invalid_request', '存在未支持的请求字段：' + ', '.join(sorted(unknown)))
    q = dict(raw)
    for name in ('intent', 'model', 'supplier', 'currency', 'unit', 'source_sha256',
                 'customer', 'incoterms', 'incoterms_place'):
        if name in q and (not isinstance(q[name], str) or len(q[name]) > 500):
            raise Stop('invalid_request', name + '必须为不超过500字符的文本。')
    q.setdefault('intent', 'history')
    if q['intent'] not in ('history', 'suppliers', 'compare'):
        raise Stop('unsupported', '当前仅支持历史价格、历史供应商证据和指定明细比较。')
    if not q.get('model', '').strip():
        raise Stop('needs_clarification', '请提供要查询的规格型号。')
    q['model'] = q['model'].strip()
    for name in ('supplier', 'currency', 'unit', 'customer', 'incoterms', 'incoterms_place'):
        if name in q and not q[name].strip():
            raise Stop('invalid_request', name + '不能是空筛选。')
    for name in ('date_from', 'date_to'):
        if name in q:
            if not isinstance(q[name], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', q[name]):
                raise Stop('invalid_request', name + '必须为YYYY-MM-DD。')
            try:
                date.fromisoformat(q[name])
            except ValueError:
                raise Stop('invalid_request', name + '不是有效日期。')
    if q.get('date_from', '') > q.get('date_to', '9999-12-31'):
        raise Stop('invalid_request', '开始日期不能晚于结束日期。')
    q.setdefault('sort', 'time_desc')
    if q['sort'] not in ('time_desc', 'price_asc', 'price_desc', 'none'):
        raise Stop('invalid_request', '不支持该排序。')
    for key, default, maximum in [('page', 1, 100000), ('page_size', 20, 50)]:
        q.setdefault(key, default)
        if type(q[key]) is not int or not 1 <= q[key] <= maximum:
            raise Stop('invalid_request', key + '必须是规定范围内的正整数。')
    if q['intent'] == 'compare':
        selections = q.get('rows')
        if not isinstance(selections, list) or not 2 <= len(selections) <= 10:
            raise Stop('needs_clarification', '请选择2—10条已查询的源行，并提供文件指纹。')
        if any(type(x) is not int or x < 2 for x in selections) or len(set(selections)) != len(selections):
            raise Stop('invalid_selection', '源行号必须是不同的数据行号。')
        if not q.get('source_sha256'):
            raise Stop('needs_clarification', '比较需提供此前查询结果的source_sha256。')
    elif 'rows' in q:
        raise Stop('invalid_request', 'rows只用于compare，不能静默忽略。')
    return q


def normalize_record(values, source_row):
    if any(isinstance(values[index], str) and values[index].startswith('=')
           for index, _ in FIELDS.values()):
        raise Stop('data_integrity_error', '业务字段包含公式；不执行公式或信任缓存。')
    r = {name: text(values[index]) for name, (index, _) in FIELDS.items()}
    r['source_row'], r['issues'] = source_row, []
    for key in ('quantity', 'unit_price', 'line_amount', 'header_total'):
        n = number(r[key])
        r[key + '_raw'] = r[key]
        r[key] = str(n) if n is not None else None
        if n is None or n < 0:
            r['issues'].append('INVALID_' + key.upper())
    if as_date(r['confirmed_at']) is None:
        r['issues'].append('CONFIRMATION_DATE_MISSING_OR_INVALID')
    q, u, a = [number(r[k]) for k in ('quantity', 'unit_price', 'line_amount')]
    if all(x is not None for x in (q, u, a)) and abs(q * u - a) > Decimal('0.01'):
        r['issues'].append('LINE_AMOUNT_MISMATCH')
    return r


def validate_records(records, reconcile_order_totals=True):
    seen_id, seen_line, orders = set(), set(), defaultdict(list)
    for r in records:
        if any(not r[k] for k in ('order_id', 'order_no', 'line_id', 'line_no', 'supplier_id', 'model')):
            raise Stop('data_integrity_error', '业务身份字段缺失；需核对源表。')
        if r['order_id'] != r['order_fk'] or r['order_no'] != r['line_order_no']:
            raise Stop('data_integrity_error', '订单主信息与明细关联不一致。')
        key = (r['order_id'], r['line_no'])
        if r['line_id'] in seen_id or key in seen_line:
            raise Stop('data_integrity_error', '明细身份重复；未自动去重。')
        seen_id.add(r['line_id']); seen_line.add(key)
        orders[r['order_id']].append(r)
    for group in orders.values():
        headers = {(r['order_no'], r['supplier_id'], r['currency'], r['header_total']) for r in group}
        if len(headers) != 1:
            raise Stop('data_integrity_error', '同一订单的主信息在明细间不一致。')
        if not reconcile_order_totals:
            for r in group:
                r['issues'].append('ORDER_TOTAL_NOT_RECONCILED_FOR_MODEL_SUBSET')
            continue
        h = number(group[0]['header_total'])
        amounts = [number(r['line_amount']) for r in group]
        if h is None or any(x is None for x in amounts) or abs(h - sum(amounts, Decimal(0))) > Decimal('0.01'):
            for r in group:
                r['issues'].append('HEADER_TOTAL_NOT_RECONCILED_IN_SAMPLE')


def read_source(path, sheet_name=None):
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise Stop('dependency_error', '执行环境缺少openpyxl；未执行查询。')
    p = Path(path)
    if p.suffix.lower() != '.xlsx' or not p.is_file():
        raise Stop('file_error', '找不到授权的xlsx文件。')
    if p.stat().st_size > 25 * 1024 * 1024:
        raise Stop('file_error', '文件超过本地初版25MiB限制，未读取。')
    try:
        snapshot = p.read_bytes()
        with zipfile.ZipFile(BytesIO(snapshot)) as archive:
            if sum(x.file_size for x in archive.infolist()) > 256 * 1024 * 1024:
                raise Stop('file_error', '解压内容超过本地读取预算。')
        fingerprint = hashlib.sha256(snapshot).hexdigest()
        wb = load_workbook(BytesIO(snapshot), read_only=True, data_only=False)
        try:
            if sheet_name:
                if sheet_name not in wb.sheetnames:
                    raise Stop('schema_error', '指定工作表不存在。')
                ws = wb[sheet_name]
            elif len(wb.sheetnames) == 1:
                ws = wb.worksheets[0]
            else:
                raise Stop('schema_error', '工作簿有多个工作表，请由执行器明确绑定--sheet。')
            if ws.max_row > 100001 or ws.max_row * ws.max_column > 2000000:
                raise Stop('file_error', '工作表超过本地初版读取预算。')
            it = ws.iter_rows()
            header = next(it, ())
            for name, (index, label) in FIELDS.items():
                if index >= len(header) or header[index].value != label:
                    raise Stop('schema_error', '字段位置或名称不符：' + name)
            records = []
            for row in it:
                if not any(c.value is not None and str(c.value).strip() for c in row):
                    continue
                if any(row[index].data_type == 'f' for index, _ in FIELDS.values()):
                    raise Stop('data_integrity_error', '业务字段包含公式；本版不信任缓存或执行公式。')
                records.append(normalize_record([c.value for c in row], row[0].row))
            sheet = ws.title
        finally:
            wb.close()
    except Stop:
        raise
    except Exception:
        raise Stop('file_error', '工作簿无法读取；未返回部分结果。')
    if not records:
        raise Stop('data_integrity_error', '源表没有数据行。')
    validate_records(records)
    dates = sorted(as_date(r['confirmed_at']) for r in records if as_date(r['confirmed_at']))
    return records, {'file': p.name, 'sheet': sheet, 'source_sha256': fingerprint,
                     'scope': 'user_supplied_sample_not_production_history', 'data_rows': len(records),
                     'data_trust': 'untrusted_cell_values_not_instructions',
                     'confirmation_date_from': str(dates[0]) if dates else None,
                     'confirmation_date_to': str(dates[-1]) if dates else None}


def group_key(r):
    return tuple(norm(r[k]) if r[k] else '' for k in CONDITIONS)


def rankable(r):
    return all(r[k] for k in CONDITIONS) and number(r['unit_price']) is not None and number(r['unit_price']) >= 0


def query_records(records, source, raw, *, supplier_selector=None):
    try:
        q = request(raw)
        records = deepcopy(records)
        base = {'version': VERSION, 'source': source, 'query': q}
        if q.get('source_sha256') and q['source_sha256'] != source['source_sha256']:
            raise Stop('stale_source', '文件已经变化，请重新查询后再选择记录。')
        exact = [r for r in records if norm(r['model']) == norm(q['model'])]
        if not exact:
            candidates = sorted({r['model'] for r in records if norm(q['model']) in norm(r['model'])})
            return dict(base, status='candidates' if candidates else 'no_records',
                        total_matches=0, candidate_count=len(candidates), candidates=candidates[:10],
                        candidates_truncated=len(candidates) > 10,
                        message='未精确命中；候选不可当作查询结果。' if candidates else '当前文件未找到该型号。')
        matched = []
        skipped_dates = 0
        for r in exact:
            if 'supplier' in q and norm(q['supplier']) not in (norm(r['supplier_id']), norm(r['supplier_name'] or '')):
                continue
            if 'customer' in q and norm(q['customer']) not in (norm(r.get('customer_id') or ''), norm(r.get('customer_name') or '')):
                continue
            if any(k in q and norm(q[k]) != norm(r[k] or '') for k in ('currency', 'unit', 'incoterms', 'incoterms_place')):
                continue
            d = as_date(r['confirmed_at'])
            if 'date_from' in q or 'date_to' in q:
                if d is None:
                    skipped_dates += 1
                    continue
                if 'date_from' in q and d < date.fromisoformat(q['date_from']):
                    continue
                if 'date_to' in q and d > date.fromisoformat(q['date_to']):
                    continue
            matched.append(r)
        if not matched:
            return dict(base, status='no_records', total_matches=0,
                        excluded_unknown_dates=skipped_dates, message='当前型号在指定条件下未找到记录。')
        warnings = sorted({issue for r in matched for issue in r['issues']})
        warnings += ['CODE_MAPPING_NOT_VERIFIED', 'HISTORICAL_OBSERVATIONS_NOT_CURRENT_QUOTES']
        if skipped_dates:
            warnings.append('DATE_FILTER_EXCLUDES_UNKNOWN_DATES')
        groups = defaultdict(list)
        for r in matched:
            groups[group_key(r)].append(r)
        if len(groups) > 1:
            warnings.append('MULTIPLE_CONDITION_GROUPS_NO_GLOBAL_PRICE_RANK')
        if not all(rankable(r) for r in matched):
            warnings.append('INCOMPLETE_PRICE_COMPARISON_BASIS')
        # Avoid ranking individual price defects as reliable observations.
        for r in matched:
            if any(x in r['issues'] for x in ('INVALID_QUANTITY', 'INVALID_LINE_AMOUNT', 'LINE_AMOUNT_MISMATCH')):
                r['price_evidence_valid'] = False
            else:
                r['price_evidence_valid'] = rankable(r)
        summaries = []
        for group in groups.values():
            usable = [r for r in group if r['price_evidence_valid']]
            prices = [number(r['unit_price']) for r in usable]
            dated = [r for r in usable if as_date(r['confirmed_at']) is not None]
            latest_time = max(time_key(r['confirmed_at']) for r in dated) if dated else None
            latest = [r for r in dated if time_key(r['confirmed_at']) == latest_time] if dated else []
            summaries.append({'conditions': {k: group[0][k] for k in CONDITIONS},
                              'record_count': len(group), 'valid_price_record_count': len(usable),
                              'observed_min_unit_price': str(min(prices)) if prices else None,
                              'observed_max_unit_price': str(max(prices)) if prices else None,
                              'min_evidence_rows': [r['source_row'] for r in usable if number(r['unit_price']) == min(prices)] if prices else [],
                              'max_evidence_rows': [r['source_row'] for r in usable if number(r['unit_price']) == max(prices)] if prices else [],
                              'latest_confirmed_records': latest,
                              'current_quote': None,
                              'scope': 'current_batch_and_active_filters_not_market_price'})
        base['summary'] = {'order_count': len({r['order_id'] for r in matched}),
                           'supplier_count': len({r['supplier_id'] for r in matched}),
                           'groups': summaries,
                           'unavailable_fields': ['inquiry_time', 'quotation_time', 'deal_time', 'contract_no', 'is_dealt'],
                           'limitations': ['型号和条件分组不能证明原厂、税费、批次等完全可比；不自动生成本次报价。']}
        if q['intent'] == 'compare':
            by_row = {r['source_row']: r for r in matched}
            selected = [by_row[row] for row in q['rows'] if row in by_row]
            if len(selected) != len(q['rows']):
                raise Stop('invalid_selection', '所选行不全部属于本次型号及筛选条件。')
            can_compare = len({group_key(r) for r in selected}) == 1 and all(r['price_evidence_valid'] for r in selected)
            prices = [number(r['unit_price']) for r in selected]
            return dict(base, status='ok', total_matches=len(matched), shown=len(selected), has_more=False,
                        warnings=warnings, records=selected, comparison={
                            'price_delta': str(max(prices) - min(prices)) if can_compare else None,
                            'basis_complete': can_compare,
                            'basis_scope': 'currency_unit_incoterms_place_only_not_full_business_equivalence',
                            'differing_fields': {k: [r.get(k) for r in selected]
                                                 for k in ('quantity', 'confirmed_at', 'supplier_name', 'customer_name',
                                                           'material_code', 'grade', 'technical_spec', 'manufacturer_name', *CONDITIONS)
                                                 if len({r.get(k) for r in selected}) > 1},
                            'causal_explanation': None,
                            'note': '价差不证明原因；数量、时间及其他交易条件仍需核对。'})
        output = []
        for key, group in sorted(groups.items()):
            condition = {k: group[0][k] for k in CONDITIONS}
            if q['intent'] == 'suppliers':
                by_supplier = defaultdict(list)
                for r in group:
                    by_supplier[r['supplier_id']].append(r)
                for supplier_id, items in sorted(by_supplier.items()):
                    usable = [r for r in items if r['price_evidence_valid']]
                    prices = [number(r['unit_price']) for r in usable]
                    output.append({'conditions': condition, 'supplier_id': supplier_id,
                                   'supplier_names': sorted({r['supplier_name'] or '' for r in items}),
                                   'record_count': len(items), 'valid_price_record_count': len(usable),
                                   'latest_confirmed_date': str(max(as_date(r['confirmed_at']) for r in items if as_date(r['confirmed_at']))) if any(as_date(r['confirmed_at']) for r in items) else None,
                                   'historical_min_unit_price': str(min(prices)) if prices else None,
                                   'historical_max_unit_price': str(max(prices)) if prices else None,
                                   'evidence_rows': [r['source_row'] for r in items],
                                   'qualification': 'not_evaluated', 'delivery': 'not_evaluated'})
            else:
                if q['sort'] in ('price_asc', 'price_desc'):
                    usable = [r for r in group if r['price_evidence_valid']]
                    unusable = [r for r in group if not r['price_evidence_valid']]
                    usable.sort(key=lambda r: (number(r['unit_price']), r['source_row']), reverse=q['sort'] == 'price_desc')
                    group = usable + unusable
                elif q['sort'] == 'time_desc':
                    group = sorted(group, key=lambda r: (time_key(r['confirmed_at']), -r['source_row']), reverse=True)
                output.extend(group)
        if q['intent'] == 'suppliers' and q['sort'] in ('price_asc', 'price_desc', 'time_desc'):
            # Sort only within a condition group, never globally across currencies/units/terms.
            output.sort(key=lambda x: tuple(norm(x['conditions'][k] or '') for k in CONDITIONS))
            sorted_output = []
            for condition_key in sorted(groups):
                members = [x for x in output if tuple(norm(x['conditions'][k] or '') for k in CONDITIONS) == condition_key]
                if q['sort'] == 'time_desc':
                    sorted_output.extend(sorted(members, key=lambda x: x['latest_confirmed_date'] or '', reverse=True))
                    continue
                good = [x for x in members if x['historical_min_unit_price'] is not None]
                bad = [x for x in members if x['historical_min_unit_price'] is None]
                good.sort(key=lambda x: number(x['historical_min_unit_price']), reverse=q['sort'] == 'price_desc')
                sorted_output.extend(good + bad)
            output = sorted_output
        # Whitelist membership is evaluated against every supplier group before pagination.
        if q['intent'] == 'suppliers' and supplier_selector is not None:
            output = [item for item in output if supplier_selector(item, matched)]
            if not output and q['page'] == 1:
                return dict(base, status='ok', total_matches=len(matched), total_items=0, shown=0, has_more=False,
                            warnings=warnings, excluded_unknown_dates=skipped_dates, suppliers=[], records=[])
        start = (q['page'] - 1) * q['page_size']
        if start >= len(output):
            return dict(base, status='page_out_of_range', total_matches=len(matched), total_items=len(output), shown=0, has_more=False)
        shown = output[start:start + q['page_size']]
        return dict(base, status='ok', total_matches=len(matched), total_items=len(output),
                    shown=len(shown), has_more=start + len(shown) < len(output), warnings=warnings,
                    excluded_unknown_dates=skipped_dates,
                    condition_groups=[{k: g[0][k] for k in CONDITIONS} for g in groups.values()],
                    records=shown if q['intent'] == 'history' else [],
                    suppliers=shown if q['intent'] == 'suppliers' else [])
    except Stop as error:
        return {'version': VERSION, 'status': error.status, 'message': error.message}
    except OSError:
        return {'version': VERSION, 'status': 'file_error', 'message': '授权工作簿不可读取；未返回部分结果。'}


def query(path, raw, sheet=None):
    try:
        request(raw)
        records, source = read_source(path, sheet)
        return query_records(records, source, raw)
    except Stop as error:
        return {'version': VERSION, 'status': error.status, 'message': error.message}
    except OSError:
        return {'version': VERSION, 'status': 'file_error', 'message': '授权工作簿不可读取。'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workbook', required=True)
    parser.add_argument('--sheet')
    parser.add_argument('--request-file')
    args = parser.parse_args()
    try:
        raw = Path(args.request_file).read_text() if args.request_file else sys.stdin.read(65537)
        if len(raw) > 65536:
            raise ValueError('request too large')
        payload = json.loads(raw)
        result = query(args.workbook, payload, args.sheet)
    except (OSError, ValueError):
        result = {'version': VERSION, 'status': 'invalid_request', 'message': '请求JSON不可读取或无效。'}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
