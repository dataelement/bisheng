"""Customs fixture contract and deterministic integrity checks (no network)."""
import hashlib
import json
import math
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

SCHEMA='customs-history-v1'
ACTIVE_REVISION=4
CALL='/openapi/tic-definition/integrationInterface/call'
FUNCTION='mock_customs_history_v1'
MAX_BYTES=16*1024*1024
MAX_ROWS=10000
DETAIL_FIELDS={'sequence': '序号', 'contract_no': '合同号', 'material_code': '物料编码', 'model': '规格型号', 'dangerous_goods': '危化品属性', 'gross_weight_kg': '毛重（KG）', 'length_cm': '包装长（CM）', 'width_cm': '包装宽（CM）', 'height_cm': '包装高（CM）', 'package_count': '包装数量', 'pieces': '件数', 'destination_code': '目的港代码', 'destination': '目的港', 'carrier': '报关代理', 'master_no': '主单号', 'house_no': '分单号', 'history_date': '历史日期', 'bill_no': '费用单号', 'coverage_houses': '费用覆盖分单', 'currency': '币种', 'total_amount': '费用合计', 'fee_01': '报关服务费', 'fee_02': '抽单费', 'fee_03': '仓储费', 'fee_04': '换单费', 'fee_05': '船公司单证费', 'fee_06': '清关费', 'fee_07': '海关查验', 'fee_08': '港杂费/仓储费', 'fee_09': '提货拆箱服务费(动卫检场地费）', 'fee_10': '口岸/目的地查验服务费（危）', 'fee_11': '进出仓费', 'fee_12': '地面服务费', 'fee_13': '检验检疫', 'fee_14': '电脑预录费', 'fee_15': '舱单费', 'fee_16': '理货费', 'fee_17': '留场费', 'fee_18': '铲车费', 'fee_19': '查验仓储费', 'fee_20': '海关查验杂费'}
FEE_FIELDS={k:v for k,v in DETAIL_FIELDS.items() if k.startswith('fee_')}
BILL_FIELDS={k:k for k in ['bill_no','carrier','currency','total_amount','history_date','house_numbers','contracts','detail_count','fee_items','source_row']}
TEXT_QUERY={'model','material_code','destination','destination_code','dangerous_goods','carrier','currency'}
NUM_QUERY={'gross_weight_kg','length_cm','width_cm','height_cm','package_count'}
LIST_QUERY={'house_numbers','bill_numbers','contract_numbers','master_numbers'}
QUERY_KEYS=TEXT_QUERY|NUM_QUERY|LIST_QUERY|{'date_field','date_from','date_to'}
PORTS={'pvg':'上海浦东机场','浦东机场':'上海浦东机场','上海浦东':'上海浦东机场','上海浦东机场':'上海浦东机场','上海港':'上海港','1':'上海港','42':'上海浦东机场'}
DG={'危化品':'危化品','危险品':'危化品','非危化品':'非危化品','非危险品':'非危化品','普货':'非危化品','是':'危化品','否':'非危化品'}


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
            result[key] = (PORTS.get(norm(value),value.strip()) if key=='destination' else DG.get(value.strip(),value.strip()) if key=='dangerous_goods' else value.strip())
            if key=='dangerous_goods':require(result[key] in ('危化品','非危化品'),'Unknown hazard attribute')
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
            require(value in ('history_date',), 'Unknown date field')
            result[key] = value
    if 'date_from' in result or 'date_to' in result:
        result.setdefault('date_field', 'history_date')
    require('date_field' not in result or 'date_from' in result or 'date_to' in result,
            'Date field needs a date bound')
    require(result.get('date_from', '0001-01-01') <= result.get('date_to', '9999-12-31'), 'Reversed date range')
    return result


def matches(row,bill,conditions):
    for key,value in conditions.items():
        if key in TEXT_QUERY and norm(row[key])!=norm(value):return False
        if key in NUM_QUERY and number(row[key])!=number(value):return False
        if key in LIST_QUERY:
            field={'house_numbers':'house_no','bill_numbers':'bill_no','contract_numbers':'contract_no','master_numbers':'master_no'}[key]
            if norm(row[field]) not in {norm(v) for v in value}:return False
    actual=row['history_date'][:10]
    return conditions.get('date_from','0001-01-01')<=actual<=conditions.get('date_to','9999-12-31')



def customs_fee(entity):
    """Verified customs charge only; legacy fee_01 is explicitly 报关服务费.

    total_amount is a legacy all-fee total and is never a customs-fee fallback.
    Missing and explicit zero remain distinct.
    """
    if 'customs_fee_amount' in entity:
        return entity['customs_fee_amount']
    if 'fee_01' in entity:
        return entity['fee_01']
    return entity.get('fee_items', {}).get('fee_01')


def validate_entities(details,bills):
    require(isinstance(details,list) and isinstance(bills,list) and len(details)<=MAX_ROWS and len(bills)<=MAX_ROWS)
    groups=defaultdict(list);ids=set();rows=set();by_bill={}
    numeric={'sequence','package_count','pieces','gross_weight_kg','length_cm','width_cm','height_cm','total_amount','customs_fee_amount'}|set(FEE_FIELDS)
    for row in details:
        require(isinstance(row,dict) and (set(DETAIL_FIELDS)-set(FEE_FIELDS)-{'total_amount'})|{'id','source_row'} <= set(row) <= set(DETAIL_FIELDS)|{'id','source_row','customs_fee_amount'},'Detail schema')
        integer(row['source_row'],2,1000000);integer(row['sequence'],1,MAX_ROWS)
        require(row['id']=='cargo:'+str(row['source_row']) and row['id'] not in ids and row['source_row'] not in rows,'Detail identity')
        ids.add(row['id']);rows.add(row['source_row'])
        for k in set(row)-{'id','source_row'}:
            if k in numeric:require(type(row[k]) in (int,float) and number(row[k])>=0,'Numeric field')
            else:require(isinstance(row[k],str) and 0<len(row[k])<=4096 and not row[k].startswith('='),'Text field')
        for k in ['gross_weight_kg','length_cm','width_cm','height_cm']:require(number(row[k])>0)
        integer(row['package_count'],1,1000000);integer(row['pieces'],1,1000000)
        require(row['dangerous_goods'] in ('危化品','非危化品'))
        timestamp(row['history_date'])
        if set(FEE_FIELDS)<=set(row) and 'total_amount' in row:
            require(sum(number(row[k]) for k in FEE_FIELDS)==number(row['total_amount']),'Fee components differ')
        if 'customs_fee_amount' in row and 'fee_01' in row:
            require(number(row['customs_fee_amount'])==number(row['fee_01']),'Customs fee differs')
        groups[row['bill_no']].append(row)
    for b in bills:
        require(isinstance(b,dict) and set(BILL_FIELDS)-{'total_amount','fee_items'} <= set(b) <= set(BILL_FIELDS)|{'customs_fee_amount'} and b['bill_no'] not in by_bill,'Bill schema')
        by_bill[b['bill_no']]=b;members=groups.get(b['bill_no'],[])
        require(members and len(members)==b['detail_count'])
        require(b['source_row']==min(r['source_row'] for r in members))
        require(b['history_date']==min(r['history_date'] for r in members))
        require(set(b['house_numbers'].split(';'))=={r['house_no'] for r in members},'Incomplete houses')
        require(set(b['contracts'].split(';'))=={r['contract_no'] for r in members},'Incomplete contracts')
        fee_items=b.get('fee_items',{})
        require(isinstance(fee_items,dict) and set(fee_items)<=set(FEE_FIELDS))
        for value in [*fee_items.values(),*[b[k] for k in ['customs_fee_amount','total_amount'] if k in b]]:
            require(type(value) in (int,float) and number(value)>=0,'Numeric bill fee')
        if 'customs_fee_amount' in b and 'fee_01' in fee_items:
            require(number(b['customs_fee_amount'])==number(fee_items['fee_01']),'Customs fee differs')
        for r in members:
            require(all(r[k]==b[k] for k in ['carrier','currency']),'Bill context differs')
            require(customs_fee(r)==customs_fee(b),'Customs fee context differs')
            if 'total_amount' in r and 'total_amount' in b:
                require(number(r['total_amount'])==number(b['total_amount']),'Legacy total differs')
            require(set(r['coverage_houses'].split(';'))=={x['house_no'] for x in members},'Declared coverage differs')
            require(all(k in r and number(r[k])==number(v) for k,v in fee_items.items()),'Bill fee differs')
        if set(fee_items)==set(FEE_FIELDS) and 'total_amount' in b:
            require(sum(number(v) for v in fee_items.values())==number(b['total_amount']))
    require(set(groups)==set(by_bill),'Orphan bill')
    return groups,by_bill



def validate_source(source):
    require(isinstance(source,dict) and set(source)=={'file','sha256','dataset_kind','revision','sheets'})
    require(source['file']=='报关数据宽表.xlsx' and re.fullmatch('[a-f0-9]{64}',source['sha256']))
    require(source['dataset_kind']=='synthetic_integration_fixture' and source['revision'] in (3,4))
    require(source['sheets']=={'details':'报关数据'})



def select(details, bills, conditions):
    by_bill = {b['bill_no']: b for b in bills}
    selected = [r for r in details if matches(r, by_bill[r['bill_no']], conditions)]
    for list_key, field in [('bill_numbers','bill_no'), ('house_numbers','house_no')]:
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
