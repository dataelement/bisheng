"""Transport fixture contract and deterministic integrity checks (no network)."""
import hashlib
import json
import math
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

SCHEMA = 'transport-history-v2'
CALL = '/openapi/tic-definition/integrationInterface/call'
FUNCTION = 'mock_transport_history_v1'
MAX_BYTES = 16 * 1024 * 1024
MAX_ROWS = 10000
DETAIL_FIELDS = dict(zip(
    'sequence contract_no model pieces net_weight_kg origin destination goods_currency goods_foreign goods_cny currency fee_foreign fee_cny fee_ratio mode material_type dangerous_goods length_cm width_cm height_cm package_count carrier master_no house_no etd eta order_no goods_invoice_no bill_no month'.split(),
    ['序号','合同号','规格型号','件数','净重（KG）','起运港','目的港','货值币种','货值（外币）','货值（人民币）','运费币种','运费（美元/欧元）','运费人民币（开票）','运费占比','运输方式','物料类型','危化品属性','包装长（CM）','包装宽（CM）','包装高（CM）','包装数量','运输服务商','主单号','分单号','ETD离港时间','ETA到达时间','订单号','货物发票号','费用单号','月份']))
BILL_FIELDS = dict(zip(
    'bill_no invoice_date currency foreign_total cny_total carrier master_no house_numbers contracts detail_count quote_time'.split(),
    ['费用单号','开票日期','运费币种','运费（外币）','运费人民币（开票）','运输服务商','主单号','关联分单号','关联合同号','关联明细数','报价时间']))
TEXT_QUERY = {'model','origin','destination','mode','dangerous_goods','carrier','currency'}
NUM_QUERY = {'gross_weight_kg','net_weight_kg','length_cm','width_cm','height_cm','package_count'}
LIST_QUERY = {'master_numbers','house_numbers','bill_numbers'}
QUERY_KEYS = TEXT_QUERY | NUM_QUERY | LIST_QUERY | {'date_field','date_from','date_to'}


class ContractError(ValueError):
    pass


def require(condition, message='Data contract failed'):
    if not condition:
        raise ContractError(message)


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, 'Duplicate JSON key')
        result[key] = value
    return result


def loads(raw):
    require(isinstance(raw, (str, bytes)) and len(raw) <= MAX_BYTES, 'JSON exceeds budget')
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ContractError('Non-finite JSON')))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ContractError('Invalid JSON') from exc


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def norm(value):
    return ' '.join(unicodedata.normalize('NFKC', value).split()).casefold()


def number(value):
    require(type(value) in (int, float, str) and len(str(value)) <= 80, 'Invalid number')
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ContractError('Invalid number') from exc
    require(result.is_finite() and (not result or -30 <= result.adjusted() <= 30), 'Number outside budget')
    return result


def timestamp(value):
    require(isinstance(value, str) and len(value) <= 40, 'Invalid date')
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ContractError('Invalid date') from exc
    require(parsed.tzinfo is None, 'Unexpected date timezone')
    return parsed


def integer(value, minimum, maximum):
    require(type(value) is int and minimum <= value <= maximum, 'Invalid integer or budget')
    return value


def query(raw, allow_empty=False):
    require(isinstance(raw, dict) and not set(raw) - QUERY_KEYS, 'Unknown query field')
    require(allow_empty or set(raw) - {'date_field'}, 'A bounded query is required')
    result = {}
    for key, value in raw.items():
        if key in TEXT_QUERY:
            require(isinstance(value, str) and 0 < len(value.strip()) <= 256, 'Invalid text query')
            result[key] = value.strip()
        elif key in LIST_QUERY:
            require(isinstance(value, list) and 1 <= len(value) <= 100, 'Invalid identifier list')
            require(all(isinstance(v, str) and 0 < len(v.strip()) <= 256 for v in value), 'Invalid identifier')
            require(len({norm(v) for v in value}) == len(value), 'Duplicate query identifier')
            result[key] = [v.strip() for v in value]
        elif key in NUM_QUERY:
            require(type(value) in (int, float) and number(value) > 0, 'Invalid numeric query')
            if key == 'package_count':
                integer(value, 1, 1000000)
            result[key] = value
        elif key in {'date_from','date_to'}:
            require(isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value), 'Invalid query date')
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise ContractError('Invalid query date') from exc
            result[key] = value
        else:
            require(value in ('etd','eta','invoice_date'), 'Unknown date field')
            result[key] = value
    if 'date_from' in result or 'date_to' in result:
        result.setdefault('date_field', 'etd')
    require('date_field' not in result or 'date_from' in result or 'date_to' in result,
            'Date field needs a date bound')
    require(result.get('date_from', '0001-01-01') <= result.get('date_to', '9999-12-31'), 'Reversed date range')
    return result


def active_query(raw, allow_empty=False):
    """Current business conditions; legacy query() remains for stored receipt validation."""
    result = query(raw, allow_empty=allow_empty)
    require(not {'net_weight_kg','package_count'} & set(result), 'Use gross weight and dimensions')
    require(result.get('date_field') != 'invoice_date', 'Invoice dates are outside the active scope')
    return result


def waybill_matches(row, masters=(), houses=()):
    """Match a concrete waybill row at master level, then at house level."""
    if masters and norm(row['master_no']) not in {norm(value) for value in masters}:
        return False
    return not houses or norm(row['house_no']) in {norm(value) for value in houses}


def matches(row, bill, conditions):
    if not waybill_matches(row, conditions.get('master_numbers', ()), conditions.get('house_numbers', ())):
        return False
    for key, value in conditions.items():
        if key in TEXT_QUERY and norm(row[key]) != norm(value):
            return False
        if key in NUM_QUERY and (row.get(key) is None or number(row[key]) != number(value)):
            return False
        if key == 'bill_numbers' and norm(row['bill_no']) not in {norm(v) for v in value}:
            return False
    field = conditions.get('date_field', 'etd')
    actual = (bill['invoice_date'] if field == 'invoice_date' else row[field])[:10]
    return conditions.get('date_from', '0001-01-01') <= actual <= conditions.get('date_to', '9999-12-31')


def validate_entities(details, bills):
    require(isinstance(details, list) and isinstance(bills, list) and len(details) <= MAX_ROWS and len(bills) <= MAX_ROWS)
    groups, ids, source_rows, bill_map = defaultdict(list), set(), set(), {}
    for row in details:
        require(isinstance(row, dict) and set(row) - {'gross_weight_kg'} == set(DETAIL_FIELDS) | {'id','source_row'},
                'Invalid detail schema')
        if row.get('gross_weight_kg') is not None:
            require(type(row['gross_weight_kg']) in (int, float) and number(row['gross_weight_kg']) > 0,
                    'Invalid gross weight')
        integer(row['source_row'], 2, 1000000)
        require(row['id'] == 'cargo:' + str(row['source_row']) and row['id'] not in ids, 'Invalid detail identity')
        require(row['source_row'] not in source_rows, 'Duplicate detail source row')
        ids.add(row['id']); source_rows.add(row['source_row'])
        for key in DETAIL_FIELDS:
            value = row[key]
            require(type(value) in (str, int, float) and not isinstance(value, bool), 'Cells must be scalar')
            if isinstance(value, str):
                require((key == 'house_no' or value) and len(value) <= 4096 and not value.startswith('='),
                        'Invalid text or formula')
            else:
                number(value)
        for key in ['net_weight_kg','length_cm','width_cm','height_cm']:
            require(type(row[key]) in (int, float) and number(row[key]) > 0, 'Invalid weight or dimensions')
        integer(row['sequence'], 1, 1000000); integer(row['package_count'], 1, 1000000)
        for key in ['goods_foreign','goods_cny','fee_foreign','fee_cny','fee_ratio']:
            require(type(row[key]) in (int, float) and number(row[key]) >= 0, 'Invalid money')
        numeric_fields = {'sequence','package_count','net_weight_kg','length_cm','width_cm','height_cm',
                          'goods_foreign','goods_cny','fee_foreign','fee_cny','fee_ratio'}
        require(all(isinstance(row[k], str) for k in set(DETAIL_FIELDS)-numeric_fields), 'Text field has wrong type')
        require(timestamp(row['etd']) <= timestamp(row['eta']), 'Invalid voyage dates')
        groups[row['bill_no']].append(row)
    for bill in bills:
        require(isinstance(bill, dict) and set(bill) == set(BILL_FIELDS) | {'source_row'}, 'Invalid bill schema')
        integer(bill['source_row'], 2, 1000000)
        for key in set(BILL_FIELDS) - {'foreign_total','cny_total','detail_count','quote_time'}:
            require(isinstance(bill[key], str) and (key == 'house_numbers' or bill[key]) and len(bill[key]) <= 4096,
                    'Invalid bill text')
        if bill['quote_time'] is not None:
            timestamp(bill['quote_time'])
        require(bill['bill_no'] not in bill_map, 'Duplicate bill identity')
        integer(bill['detail_count'], 1, MAX_ROWS)
        for key in ['foreign_total','cny_total']:
            require(type(bill[key]) in (int, float) and number(bill[key]) >= 0, 'Invalid bill amount')
        bill_map[bill['bill_no']] = bill
        members = groups.get(bill['bill_no'], [])
        require(len(members) == bill['detail_count'], 'Incomplete bill members')
        houses = bill['house_numbers'].split(';') if bill['house_numbers'] else []
        contracts = bill['contracts'].split(';')
        require(len(houses) == len(set(houses)) and len(contracts) == len(set(contracts)), 'Duplicate bill member label')
        require(set(houses) == {r['house_no'] for r in members if r['house_no']}, 'Bill house membership differs')
        require(set(contracts) == {r['contract_no'] for r in members}, 'Bill contract membership differs')
        for row in members:
            require(all(row[k] == bill[k] for k in ['currency','carrier','master_no']), 'Bill context differs')
            require(number(row['fee_foreign']) == number(bill['foreign_total']) and
                    number(row['fee_cny']) == number(bill['cny_total']), 'Bill amount differs')
            require(timestamp(row['eta']) <= timestamp(bill['invoice_date']), 'Invalid bill date')
            if bill['quote_time'] is not None:
                require(timestamp(bill['quote_time']) <= timestamp(row['etd']), 'Quote follows departure')
    require(set(groups) == set(bill_map), 'Orphan detail/bill')
    require(len({b['source_row'] for b in bills}) == len(bills), 'Duplicate bill source row')
    return groups, bill_map


def validate_source(source):
    require(isinstance(source, dict) and set(source) == {'file','sha256','dataset_kind','revision','sheets'}, 'Invalid source')
    require(isinstance(source['file'], str) and 0 < len(source['file']) <= 256, 'Invalid source name')
    require(isinstance(source['sha256'], str) and re.fullmatch('[a-f0-9]{64}', source['sha256']), 'Invalid source hash')
    require(source['dataset_kind'] == 'synthetic_integration_fixture' and source['revision'] == 4, 'Unexpected data identity')
    require(source['sheets'] == {'details': '货物汇总', 'bills': '运费账单'}, 'Unexpected source sheets')


def select(details, bills, conditions):
    by_bill = {b['bill_no']: b for b in bills}
    selected = [r for r in details if matches(r, by_bill[r['bill_no']], conditions)]
    for list_key, field in [('bill_numbers','bill_no'), ('house_numbers','house_no'), ('master_numbers','master_no')]:
        if list_key in conditions:
            order = {norm(v): i for i, v in enumerate(conditions[list_key])}
            selected.sort(key=lambda r: (order[norm(r[field])], r['source_row']))
    return selected


def response_page(snapshot, snapshot_id, conditions, page, size):
    conditions = query(conditions)
    integer(page, 1, 10000); integer(size, 1, 100)
    records = select(snapshot['details'], snapshot['bills'], conditions)
    total = len(records)
    pages = max(1, math.ceil(total / size))
    require(pages <= 100, 'Query exceeds the 100-page budget; increase page size or narrow scope')
    require(page <= pages, 'Page outside result range')
    current = records[(page - 1) * size:page * size]
    bill_nos = list(dict.fromkeys(r['bill_no'] for r in current))
    groups = defaultdict(list)
    for row in snapshot['details']:
        groups[row['bill_no']].append(row)
    bills = {b['bill_no']: b for b in snapshot['bills']}
    return {'schemaVersion': SCHEMA, 'snapshotId': snapshot_id, 'source': snapshot['source'],
            'query': conditions, 'pageNum': page, 'pageSize': size, 'totalPages': pages,
            'totalElements': total, 'totalBills': len({r['bill_no'] for r in records}),
            'hasNext': page < pages, 'records': current,
            'bills': [bills[k] for k in bill_nos],
            'coverage': [{'bill_no': k, 'complete': True, 'details': groups[k],
                          'matched_ids': [r['id'] for r in records if r['bill_no'] == k]} for k in bill_nos]}


def merge_pages(pages, expected_query):
    require(isinstance(pages, list) and 1 <= len(pages) <= 100, 'Invalid page count')
    expected_query = query(expected_query)
    first, all_records, all_bills, all_coverage = None, [], {}, {}
    for index, envelope in enumerate(pages, 1):
        require(isinstance(envelope, dict) and set(envelope) == {'success','code','msg','data','traceId'}, 'Invalid envelope')
        require(envelope['success'] is True and envelope['code'] == 'return.optSuccess' and
                isinstance(envelope['data'], dict) and set(envelope['data']) == {'status','data'} and
                envelope['data']['status'] == 200, 'API failed')
        data = envelope['data']['data']
        keys = {'schemaVersion','snapshotId','source','query','pageNum','pageSize','totalPages',
                'totalElements','totalBills','hasNext','records','bills','coverage'}
        require(isinstance(data, dict) and set(data) == keys and data['schemaVersion'] == SCHEMA, 'Invalid response schema')
        require(data['query'] == expected_query, 'Query differs from requested scope')
        validate_source(data['source'])
        require(isinstance(data['snapshotId'], str) and re.fullmatch('[a-f0-9]{64}', data['snapshotId']), 'Invalid snapshot')
        integer(data['pageNum'], 1, 100); integer(data['pageSize'], 1, 100)
        integer(data['totalElements'], 0, MAX_ROWS); integer(data['totalBills'], 0, MAX_ROWS)
        integer(data['totalPages'], 1, 100)
        require(type(data['hasNext']) is bool and data['hasNext'] == (index < data['totalPages']), 'Wrong next page flag')
        require(data['pageNum'] == index and data['totalPages'] == max(1, math.ceil(data['totalElements'] / data['pageSize'])), 'Wrong paging')
        if first is None:
            first = data
        require(all(data[k] == first[k] for k in ['schemaVersion','snapshotId','source','query','pageSize','totalPages','totalElements','totalBills']), 'Snapshot or paging changed')
        require(isinstance(data['records'], list) and len(data['records']) == min(data['pageSize'], max(0, data['totalElements'] - (index-1)*data['pageSize'])), 'Wrong page size')
        require(isinstance(data['coverage'], list) and isinstance(data['bills'], list), 'Invalid bill lists')
        require(all(isinstance(c, dict) and set(c) == {'bill_no','complete','details','matched_ids'} and
                    c['complete'] is True and isinstance(c['details'], list) and isinstance(c['matched_ids'], list) for c in data['coverage']), 'Incomplete coverage')
        require(len({c['bill_no'] for c in data['coverage']}) == len(data['coverage']), 'Duplicate coverage')
        related = [r for c in data['coverage'] for r in c['details']]
        groups, by_bill = validate_entities(related, data['bills'])
        touched = set(r['bill_no'] for r in data['records'])
        require(set(groups) == touched == {c['bill_no'] for c in data['coverage']}, 'Extra or missing bill coverage')
        related_map = {r['id']: r for r in related}
        require(all(related_map.get(r.get('id')) == r and matches(r, by_bill[r['bill_no']], expected_query)
                    for r in data['records']), 'Wrong or unbound matched row')
        for c in data['coverage']:
            require(all(r['bill_no'] == c['bill_no'] for r in c['details']), 'Crossed bill members')
            expected_ids = {r['id'] for r in c['details'] if matches(r, by_bill[c['bill_no']], expected_query)}
            require(len(set(c['matched_ids'])) == len(c['matched_ids']) and set(c['matched_ids']) == expected_ids, 'Incorrect matched coverage')
            key = c['bill_no']
            require(key not in all_coverage or all_coverage[key] == c, 'Coverage changed across pages')
            all_coverage[key], all_bills[key] = c, by_bill[key]
        all_records.extend(data['records'])
    require(len(pages) == first['totalPages'] and len(all_records) == first['totalElements'], 'Missing pages')
    require(len({r['id'] for r in all_records}) == len(all_records), 'Duplicate matched rows')
    require(len(all_bills) == first['totalBills'], 'Incorrect unique bill total')
    require({r['id'] for r in all_records} == {i for c in all_coverage.values() for i in c['matched_ids']}, 'Missing matched members')
    related = [r for c in all_coverage.values() for r in c['details']]
    validate_entities(related, list(all_bills.values()))
    return {'schemaVersion': SCHEMA, 'snapshotId': first['snapshotId'], 'source': first['source'],
            'query': expected_query, 'records': all_records, 'bills': list(all_bills.values()),
            'coverage': list(all_coverage.values())}
