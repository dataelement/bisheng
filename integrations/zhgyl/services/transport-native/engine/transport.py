"""Network-free fixed entry; caller binds one workspace per user/chat.

run(request, workspace) is the only business entry. Text in source cells is data.
This local adapter does not claim BISHENG tool binding or cross-user isolation.
"""
from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
import fcntl
import html
import os
from pathlib import Path
import re
import tempfile
import inquiry

from contract import (SCHEMA, MAX_BYTES, QUERY_KEYS, ContractError, BILL_FIELDS, DETAIL_FIELDS,
                      MAX_ROWS, active_query, encode, integer, loads, matches, merge_pages, norm, number, query,
                      require, sha, validate_entities, validate_source)

PROTOCOL = 'transport-fixed-entry-v1'
LIMITS_ANSWER = ('**运输历史参考的能力边界**\n\n'
    '当前工具展示历史账单及完整覆盖，不按重量自动分摊、不计算每公斤运价，也不生成本次正式报价。'
    '现有数据为联调Mock，不能把共享账单总额当成某个分单的独立费用。\n\n'
    '现有字段未提供账单作废/有效状态或合同责任条款。不能仅凭历史日期推断账单已作废，'
    '也不能据此判断运费差额由哪一方承担。\n\n'
    '如需单票费用或本次报价，请补充对应费用行明细、经业务确认的分摊依据或供应商当期报价，'
    '由业务人员确认。历史费用和完整账单覆盖仍可继续查询。')
STATE = 'uploads/transport-runtime/session.json'
SORTS = {'source'}
LEGACY_SORTS = SORTS | {'invoice_date_asc','invoice_date_desc'}
QUERY_LABELS = {'master_numbers':'主单号','house_numbers':'分单号','bill_numbers':'费用单号','model':'规格型号',
                'origin':'起运港','destination':'目的港','mode':'运输方式','dangerous_goods':'危化品属性',
                'carrier':'运输服务商','currency':'运费币种','gross_weight_kg':'毛重KG','length_cm':'包装长CM',
                'width_cm':'包装宽CM','height_cm':'包装高CM',
                'date_from':'日期起','date_to':'日期止','date_field':'日期依据'}
MESSAGES = {
    'invalid_request':'运输请求参数无效，未改变当前查询。请检查条件、动作或分页参数。',
    'state_error':'运输会话完整性校验失败，已停止；这不表示没有历史费用。',
    'import_error':'原始运输JSON或完整分页校验失败，已停止；这不表示没有历史费用。',
    'execution_error':'运输固定入口未完成处理，已停止；这不表示没有历史费用。',
}


def final(outcome, answer, **meta):
    return {'protocol':PROTOCOL, 'status':'final', 'outcome':outcome,
            'terminal':True, 'next_action':'none', 'answer':answer, **meta}


def safe(root, relative):
    root = Path(root).resolve()
    relative = Path(relative)
    require(not relative.is_absolute() and '..' not in relative.parts, 'Invalid workspace path')
    current = root
    for part in relative.parts:
        current = current / part
        require(not current.is_symlink(), 'Symlink workspace path')
    require(current.resolve().is_relative_to(root), 'Path outside workspace')
    return current


def read(path):
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    return raw, loads(raw)


@contextmanager
def locked(root):
    for name in ['uploads', 'uploads/transport-runtime']:
        safe(root, name).mkdir(exist_ok=True)
    path = safe(root, 'uploads/transport-runtime/.lock')
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        # Do not wait without a bound if another action holds this workspace.
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def validate_batch(batch):
    require(isinstance(batch, dict) and set(batch) == {'schemaVersion','snapshotId','source','query','records','bills','coverage'})
    require(batch['schemaVersion'] == SCHEMA and isinstance(batch['snapshotId'], str) and re.fullmatch('[a-f0-9]{64}', batch['snapshotId']))
    validate_source(batch['source']); require(query(batch['query']) == batch['query'])
    require(isinstance(batch['coverage'], list) and isinstance(batch['records'], list))
    related = []
    for item in batch['coverage']:
        require(isinstance(item, dict) and set(item) == {'bill_no','complete','details','matched_ids'} and item['complete'] is True)
        require(isinstance(item['details'], list) and isinstance(item['matched_ids'], list))
        related.extend(item['details'])
    groups, bills = validate_entities(related, batch['bills'])
    require(len({c['bill_no'] for c in batch['coverage']}) == len(batch['coverage']) == len(bills))
    lookup = {r['id']: r for r in related}
    require(all(isinstance(r, dict) and lookup.get(r.get('id')) == r for r in batch['records']))
    ids = [r['id'] for r in batch['records']]
    expected = {r['id'] for r in related if matches(r, bills[r['bill_no']], batch['query'])}
    require(len(ids) == len(set(ids)) and set(ids) == expected, 'Stored match set is incomplete')
    for c in batch['coverage']:
        require(c['bill_no'] in bills and c['details'] == groups[c['bill_no']])
        hits = {r['id'] for r in c['details'] if matches(r, bills[c['bill_no']], batch['query'])}
        require(hits and len(set(c['matched_ids'])) == len(c['matched_ids']) and set(c['matched_ids']) == hits)


def candidate_result(batch, specification=None):
    if specification:
        return inquiry.evaluate(batch['records'],batch['bills'],specification['target'])
    return {'match_type':'history','records':batch['records']}


def references(batch, specification=None):
    order = list(dict.fromkeys(r['bill_no'] for r in candidate_result(batch,specification)['records']))
    return {'F%02d' % i: bill for i, bill in enumerate(order, 1)}


def query_id(batch, specification=None):
    identity={'snapshot':batch['snapshotId'], 'query':batch['query']}
    if specification:
        identity['inquiry']=specification
    return sha(encode(identity))[:12]


def validate_state(state):
    require(isinstance(state, dict) and set(state)-{'inquiry','advice'} == {'protocol','batch','refs','query_id','filters','view','sha256'})
    if 'advice' in state:
        require('inquiry' not in state); validate_advice(state['advice'])
    require(state['protocol'] == PROTOCOL and state['sha256'] == sha(encode({k:v for k,v in state.items() if k != 'sha256'})), 'State checksum differs')
    validate_batch(state['batch'])
    specification=state.get('inquiry')
    if specification is not None:
        require(isinstance(specification,dict) and set(specification)=={'strategy','target'} and specification['strategy']==inquiry.STRATEGY)
        prepared=inquiry.prepare(specification['target'])
        require(prepared['ready'] and prepared['target']==specification['target'])
        require(state['batch']['query']==inquiry.scope(specification['target']), 'Wrong inquiry pool scope')
    require(state['refs'] == references(state['batch'],specification) and state['query_id'] == query_id(state['batch'],specification), 'Wrong fee binding')
    require(query(state['filters'], allow_empty=True) == state['filters'])
    require(set(state['view']) == {'sort','page','page_size'} and state['view']['sort'] in LEGACY_SORTS)
    integer(state['view']['page'], 1, 10000); integer(state['view']['page_size'], 1, 20)


def previous_inquiry(state):
    specification = state.get('inquiry') if isinstance(state, dict) else None
    return isinstance(specification, dict) and specification.get('strategy') in ('transport-flowchart301-v1','transport-flowchart301-v2-recommend')


def refresh_inquiry():
    return final('needs_query', '该历史询价使用旧重量口径。请提供毛重和包装尺寸重新查询。')


def save(root, state):
    value = deepcopy(state)
    value['sha256'] = sha(encode({k:v for k,v in value.items() if k != 'sha256'}))
    validate_state(value)
    raw = encode(value)
    require(len(raw) <= MAX_BYTES, 'State write/read budget exceeded')
    target = safe(root, STATE)
    descriptor, temporary = tempfile.mkstemp(prefix='.session-', dir=target.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def import_receipts(root, receipts, conditions):
    require(isinstance(receipts, list) and 1 <= len(receipts) <= 100)
    payloads, paths, byte_count = [], set(), 0
    for receipt in receipts:
        require(isinstance(receipt, dict) and set(receipt) == {'path','bytes','sha256'}, 'Invalid raw receipt')
        relative = receipt['path']
        require(isinstance(relative, str) and re.fullmatch(r'uploads/transport-api/[a-f0-9]{32}\.json', relative), 'Invalid raw file handle')
        require(relative not in paths, 'Duplicate raw file handle'); paths.add(relative)
        integer(receipt['bytes'], 1, MAX_BYTES)
        raw, payload = read(safe(root, relative))
        byte_count += len(raw)
        require(byte_count <= MAX_BYTES and len(raw) == receipt['bytes'] and sha(raw) == receipt['sha256'], 'Raw receipt differs')
        payloads.append(payload)
    return merge_pages(payloads, conditions)


def cell(value):
    # Escape HTML and Markdown links/backticks; no source text becomes markup.
    text = html.escape(str(value), quote=False).replace('\r',' ').replace('\n',' ')
    for character in ['\\','|','[',']','*','_','`']:
        text = text.replace(character, '\\' + character)
    return text


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |', '| '+' | '.join(['---']*len(headers))+' |'] +
                     ['| '+' | '.join(cell(v) for v in row)+' |' for row in rows])


def transport_table(rows):
    # Only the formatter supplies line breaks. Every source value is still escaped.
    return '\n'.join(['| 查询关系 | 分单号 | 运输条件及匹配说明 |', '| --- | --- | --- |']+
                     ['| '+cell(relation)+' | '+cell(house)+' | '+
                      '<br>'.join(cell(line) for line in description)+' |'
                      for relation,house,description in rows])


def amount(value):
    number_value = number(value)
    places = max(2, -number_value.as_tuple().exponent)
    return format(number_value, ',.' + str(places) + 'f')


def numeric(value):
    return format(number(value).normalize(), 'f')


def conditions_text(conditions, show_identifiers=True):
    if not conditions:
        return '无'
    parts=[]
    for key,value in conditions.items():
        if key in ('net_weight_kg', 'package_count') or (key == 'date_field' and value == 'invoice_date'):
            parts.append('已保存的旧筛选条件。如需按当前毛重和包装尺寸口径查询，请重新查询。')
            continue
        if not show_identifiers and key == 'master_numbers':
            parts.append('主单范围：指定'+str(len(value))+'条（本次查询条件）')
            continue
        if not show_identifiers and key in ['house_numbers','bill_numbers']:
            parts.append(('分单范围：指定'+str(len(value))+'条（本次查询条件）') if key=='house_numbers' else
                         '费用账单：指定'+str(len(value))+'张（按费用单精确筛选）')
            continue
        if key=='date_field':
            value={'etd':'ETD离港日期','eta':'ETA到达日期','invoice_date':'账单开票日期'}[value]
        if isinstance(value,list):
            value='、'.join(value)
        parts.append(QUERY_LABELS[key]+'：'+cell(value))
    return '；'.join(parts)


def selection(state):
    batch = state['batch']; bills = {b['bill_no']: b for b in batch['bills']}
    base=candidate_result(batch,state.get('inquiry'))['records']
    records = [r for r in base if matches(r, bills[r['bill_no']], state['filters'])]
    selected = {r['bill_no'] for r in records}
    order = [key for key in state['refs'] if state['refs'][key] in selected]
    return records, order


def bill_sections(state, ref, hits, member_page=1, member_size=20, detail=False, master_candidate=False):
    batch = state['batch']; no = state['refs'][ref]
    bill = next(b for b in batch['bills'] if b['bill_no'] == no)
    members = next(c['details'] for c in batch['coverage'] if c['bill_no'] == no)
    start = (member_page-1) * member_size
    require(start < len(members), 'Member page outside range')
    displayed = members[start:start+member_size]
    parts = ['**'+ref+' 关联运输与完整覆盖**']
    if detail:
        parts += ['**费用账单**',table(['项目','内容'],[
            ['费用单号',no],['服务商',bill['carrier']]])]
    else:
        parts += ['服务商：'+cell(bill['carrier'])+'。']
    if len(members) > 1:
        parts.append('**共享账单总额，未分摊：不能归给某一型号、分单或运输段，也不按重量自动分配。**')
    else:
        parts.append('独立指当前样例账单仅关联1条明细，不表示费用包含范围或生产关联已确认。')
    if detail:
        parts += ['**运输单据**','主单号：'+cell(bill['master_no'])+'。']
    groups = {}
    for row in displayed:
        key = (row['origin'],row['destination'],row['mode'],row['dangerous_goods'])
        groups.setdefault(key, []).append(row)
    for (origin,destination,mode,dg), group in groups.items():
        parts.append(' → '.join([cell(origin),cell(destination)])+'｜'+cell(mode)+'｜'+cell(dg))
        rows=[]
        for row in group:
            gross = row.get('gross_weight_kg')
            description=['规格型号：'+str(row['model']),
                         '毛重：'+(numeric(gross)+'KG' if gross is not None else '未提供'),
                         '包装：'+' × '.join(numeric(row[k]) for k in ['length_cm','width_cm','height_cm'])+'CM']
            if detail:
                description+=['计划ETD：'+row['etd'][:10],'计划ETA：'+row['eta'][:10]]
            if state.get('inquiry') and row['id'] in hits:
                target=state['inquiry']['target']
                changes=inquiry.differences(row,target)
                if changes:
                    descriptions=[]
                    for change in changes:
                        key=change['field']
                        unit='KG' if key=='gross_weight_kg' else 'CM' if key in ['length_cm','width_cm','height_cm'] else ''
                        historical=change['historical']
                        descriptions.append(QUERY_LABELS[key]+'：本次 '+str(change['requested'])+unit+
                                            '，历史 '+(str(historical)+unit if historical is not None else '未提供'))
                    description+=['近似差异：'+description for description in descriptions]
                else:
                    description+=['物料、毛重、包装尺寸均匹配']
            label = ('主单候选，分单未确认' if master_candidate else
                     '本次命中' if row['id'] in hits else '同账单关联补充，未命中')
            rows.append([label,row['house_no'] or '未提供',description])
        parts.append(transport_table(rows))
    parts.append('账单共覆盖'+str(len(members))+'条明细，本段展示'+str(len(displayed))+'条；'+
                 ('其余成员可按费用引用翻页查看。' if start+len(displayed)<len(members) else '本段已到末页。'))
    if detail:
        parts += ['**业务关联**',table(['分单号','合同号','订单号'],[
            [row['house_no'] or '未提供',row['contract_no'],row['order_no']] for row in displayed]),
            '**数据来源**','来源：货物汇总第'+cell('、'.join(str(r['source_row']) for r in displayed))+
            '行；运费账单第'+str(bill['source_row'])+'行。']
    else:
        parts.append('原始单据编号与来源定位：可继续问“查看 '+ref+' 详情”。')
    return '\n\n'.join(parts)


ADVICE_KEYS = ('origin','destination','dangerous_goods','model','gross_weight_kg','length_cm','width_cm','height_cm','mode')
LEGACY_ADVICE_KEYS = (set(ADVICE_KEYS) - {'gross_weight_kg'}) | {'net_weight_kg','package_count'}


def plain_items(result):
    return [dict(item) for item in result['items']]


def validate_advice(advice):
    require(isinstance(advice,dict) and set(advice)=={'basis','profiles','total','items'})
    require(isinstance(advice['basis'],dict) and set(advice['basis']) in
            ({'house_no',*ADVICE_KEYS}, {'house_no',*LEGACY_ADVICE_KEYS}))
    require(isinstance(advice['items'],list) and len(advice['items'])<=20)
    integer(advice['profiles'],1,MAX_ROWS); integer(advice['total'],0,MAX_ROWS)


def recommendation_section(state):
    target=state['inquiry']['target'];batch=state['batch']
    bill_map={bill['bill_no']:bill for bill in batch['bills']}
    rows=[row for row in batch['records'] if matches(row,bill_map[row['bill_no']],state['filters'])]
    result=inquiry.recommend(rows,batch['bills'],target)
    return recommendation_parts(plain_items(result),result['total_plans']),result


def recommendation_parts(items,total):
    if not items:
        return ['**运输方案推荐**','当前取数范围内没有任何运输历史，暂无法推荐。']
    def reason(item):
        parts=[inquiry.TIERS[item['tier']]+' '+str(item['tier_bills'])+'票']
        if item['tier']>=3:parts.append('参考路线 '+'、'.join(item['routes']))
        if item['same_model_rows']:parts.append('同型号明细'+str(item['same_model_rows'])+'条')
        parts.append('累计'+str(item['total_bills'])+'票')
        return '；'.join(parts)
    def fee(item):
        ranges = []
        for band in item.get('amount_ranges', []):
            low, high = amount(band['min']), amount(band['max'])
            ranges.append(cell(band['currency'])+' '+(low if low==high else low+'–'+high))
        return ' / '.join(ranges) or '未提供'
    first=items[0]
    rows=[[('首选' if i['rank']==1 else str(i['rank'])),i['carrier'],i['mode'],reason(i),i['latest'],fee(i)] for i in items]
    parts=['**运输方案推荐**',
           '首选方案：**'+cell(first['carrier'])+' · '+cell(first['mode'])+'**。依据：'+cell(reason(first))+'；最近ETD '+first['latest']+'；同类历史账单原币金额 '+fee(first)+'。',
           table(['排序','运输服务商','运输方式','推荐依据','最近ETD','同类历史账单金额（按原币）'],rows),
           '排序规则：先看经验层级（同路线同危化且同型号 → 同路线同危化 → 同危化且起运地或目的地相同 → 同危化其他路线 → 同路线不同危化 → 其他），再看该层级票数、累计票数、最近ETD。同分时按服务商与运输方式名称稳定排序。共评估'+str(total)+'个服务商与运输方式组合。']
    if first['tier']>=3:
        parts.append('**提示：没有服务商承运过本次路线与危化属性一致的历史业务，以上为按相近经验给出的推荐，请与服务商确认承运条件与报价。**')
    parts.append('金额为历史账单整单原币金额，按币种分别展示。共享账单未分摊，仅供历史参考。')
    return parts


def render(state, detail_ref=None, member_page=1):
    batch = state['batch']; records, order = selection(state)
    scopes = (batch['query'], state['filters'])
    has_master = any(scope.get('master_numbers') for scope in scopes)
    houses = {norm(number) for scope in scopes for number in scope.get('house_numbers', ())}
    master_candidate = has_master and not houses
    hits = set() if master_candidate else {r['id'] for r in records}
    association = None
    if has_master:
        unconfirmed = houses - {norm(row['house_no']) for row in records}
        if not records:
            status = 'master_not_found' if master_candidate else 'pair_not_confirmed'
        elif master_candidate:
            status = 'master_candidates'
        else:
            status = 'partial_pair_match' if unconfirmed else 'pair_matched'
        association = {'status': status, 'candidate_details': len(records),
                       'unconfirmed_house_count': len(unconfirmed)}
    if detail_ref:
        require(detail_ref in order, 'Reference is not in the active result')
        displayed = [detail_ref]
    else:
        size, page = state['view']['page_size'], state['view']['page']
        require(page <= max(1, (len(order)+size-1)//size), 'Page outside result range')
        displayed = order[(page-1)*size:page*size]
    bill_map = {b['bill_no']:b for b in batch['bills']}
    cover = {c['bill_no']:c['details'] for c in batch['coverage']}
    analysis=candidate_result(batch,state.get('inquiry'))
    match_label={'history':'历史追溯，按提供条件查询','full':'全量匹配（物料、毛重、尺寸、路线全部匹配）',
                 'approximate':'近似匹配（按流程优先级保留候选）','no_records':'当前保护条件下暂无同路线历史'}[analysis['match_type']]
    if master_candidate:
        match_label = '按主单号查找候选费用单，分单待确认'
    elif has_master:
        match_label = '按主单号与分单号组合核对'
    route_only = (analysis['match_type']=='approximate' and len(analysis.get('steps',[]))==3
                  and all(step['equal']==0 for step in analysis['steps']))
    if route_only:
        match_label='近似匹配（仅同路线参考；物料、毛重、尺寸均无已证实的同值）'
    recommendation=None
    title=['**运输历史费用查询**']
    if state.get('inquiry') and not detail_ref:
        head,recommendation=recommendation_section(state)
        title=['**运输查询与推荐**','**一、运输方案推荐**']+head[1:]+['**二、历史参考明细**']
    parts = title+['匹配方式：'+match_label+'。',
             '取数范围：'+conditions_text(inquiry.protected_scope(state['inquiry']['target']) if state.get('inquiry') else batch['query'],bool(detail_ref))+'。',
             '附加筛选：'+conditions_text(state['filters'],bool(detail_ref))+'。',
             ('按主单找到'+str(len(order))+'张候选费用单；本次展示'+str(len(displayed))+'张。'
              if master_candidate else
              '命中'+str(len(hits))+'条运输明细、'+str(len(order))+'张唯一费用账单；本次展示'+str(len(displayed))+'张。')]
    if association:
        status = association['status']
        if status == 'master_candidates':
            parts.append('**分单未确认。请提供分单号；以下仅为同主单的候选费用单。**')
        elif status == 'master_not_found':
            parts.append('当前查询范围内未找到该主单的候选费用单。')
        elif status == 'pair_not_confirmed':
            parts.append('**当前范围内未核实主单与分单组合；未将同主单其他分单列为命中。**')
        elif status == 'partial_pair_match':
            parts.append('另有'+str(association['unconfirmed_house_count'])+'个指定分单号未核实。')
    if state.get('inquiry'):
        target=state['inquiry']['target']
        anchor=parts.index('匹配方式：'+match_label+'。')
        parts.insert(1,'本次询价：'+conditions_text(target)+'。')
        if route_only:
            parts.insert(anchor+2,'**参考范围提示：仅同路线参考。物料、毛重、包装尺寸均无已证实的同值。**')
        parts.append('匹配口径：毛重统一KG，尺寸统一CM后精确相等；长宽高按输入顺序比较，不自动旋转。')
        if 'mode' not in target:
            parts.append('未限定运输方式；推荐按服务商与运输方式组合排序，历史明细按海运/空运分别展示。')
        if analysis.get('steps'):
            labels={'material':'同物料','weight':'同毛重','size':'同尺寸'}
            parts.append('候选按当前集合连续处理：'+str(analysis['pool_count'])+'条同路线及保护条件历史；'+
                         ' → '.join(labels[s['criterion']]+'：'+str(s['before'])+'条中'+str(s['equal'])+'条相同，'+
                                     ('保留匹配的'+str(s['after'])+'条' if s['decision']=='narrow' else '无相同，保留原'+str(s['after'])+'条')
                                     for s in analysis['steps'])+'。')
    metadata = []
    if displayed:
        rows = []
        for ref in displayed:
            no = state['refs'][ref]; bill, members = bill_map[no], cover[no]
            matched = sum(r['id'] in hits for r in members)
            routes = len({(r['origin'],r['destination']) for r in members})
            shared = len(members)>1
            rows.append([ref+(' · 共享' if shared else ' · 独立'),
                         bill['currency']+' '+amount(bill['foreign_total']),
                         str(len(members))+'条明细/'+str(routes)+'条路线',
                         '待确认 / '+str(len(members)) if master_candidate else str(matched)+' / '+str(len(members))])
            metadata.append({'reference':ref,'bill_no':no,'shared':shared,
                             'coverage_count':len(members),'matched_count':matched})
        parts += ['**费用总览（一账单一行）**', table(['费用引用','账单总额（原币）','完整覆盖范围','命中/覆盖'],rows),
                  '共享行按整张费用单展示，命中分单与账单全部成员分别列示。']
        parts.extend(bill_sections(state,ref,hits,member_page if detail_ref else 1,
                                  detail=bool(detail_ref),master_candidate=master_candidate) for ref in displayed)
    else:
        parts.append('当前声明取数范围及筛选下没有记录；不代表全部生产历史无记录。')
    has_more = not detail_ref and state['view']['page']*state['view']['page_size']<len(order)
    parts.append('账单还有下一页，可续问“下一页”。' if has_more else '账单本次展示无后续页。' if detail_ref else '账单已到末页。')
    parts.append('数据来源：'+cell(batch['source']['file'])+'；数据修订4，联调合成扩充。ETD/ETA为计划时间。'+
                 '历史金额不自动分摊或计算每公斤价格，不构成本次报价。')
    answer = '\n\n'.join(parts)
    require(len(answer.encode()) <= 128*1024, 'Answer exceeds display budget')
    matching={k:v for k,v in analysis.items() if k!='records'}
    extra={'association':association} if association else {}
    if recommendation is not None:
        extra['recommendation']=[{'rank':i['rank'],'carrier':i['carrier'],'mode':i['mode'],'tier':i['tier'],'tier_bills':i['tier_bills'],
                                  'total_bills':i['total_bills'],'latest':i['latest'],'amount_ranges':i['amount_ranges']}
                                 for i in recommendation['items']]
    outcome='ok' if records else ('recommended' if recommendation and recommendation['items'] else 'no_records')
    return final(outcome, answer, **extra, query_id=state['query_id'], match=matching,
                 active_filters=state['filters'], counts={'matched_details':len(hits), 'unique_bills':len(order),
                 'shown_bills':len(displayed)}, has_more=has_more, bills=metadata)


def validate_request(request):
    require(isinstance(request, dict) and len(encode(request))<=65536)
    action = request.get('action')
    fields = {'history':{'action','query','receipts','set','sort','page_size'},
              'inquiry':{'action','target','receipts','set','sort','page_size'},
              'show':{'action','sort','page','page_size'}, 'filter':{'action','set','unset'},
              'reset':{'action'}, 'detail':{'action','reference','query_id','page'},
              'explain_limits':{'action'}}
    require(isinstance(action, str) and action in fields and not set(request)-fields[action])
    if action=='history':
        require({'query','receipts'}<=set(request)); query(request['query'])
        active_query(request['query'])
    if action=='inquiry':
        require('target' in request); inquiry.prepare(request['target'])
    if 'set' in request:
        query(request['set'], allow_empty=True)
        active_query(request['set'], allow_empty=True)
    if action=='filter':
        removed=request.get('unset',[])
        require(isinstance(removed,list) and all(isinstance(k,str) for k in removed) and
                len(set(removed))==len(removed) and not set(removed)-QUERY_KEYS)
        require(not set(removed)&set(request.get('set',{})))
    if 'sort' in request:
        require(isinstance(request['sort'],str) and request['sort'] in SORTS)
    if 'page' in request:
        integer(request['page'],1,10000)
    if 'page_size' in request:
        integer(request['page_size'],1,20)
    if action=='detail':
        require(isinstance(request.get('reference'),str) and re.fullmatch('F[0-9]{2,5}',request['reference']))
        require(isinstance(request.get('query_id'),str) and re.fullmatch('[a-f0-9]{12}',request['query_id']))
    return action


def run(request, workspace=None):
    phase='invalid_request'
    try:
        action=validate_request(request)
        if action=='explain_limits':
            return final('capability_limits',LIMITS_ANSWER)
        root=Path(workspace or Path.cwd()).resolve()
        require(root.is_dir(), 'Workspace must exist')
        if action=='inquiry':
            prepared=inquiry.prepare(request['target'])
            if not prepared['ready']:
                return final('needs_clarification','询价关键信息尚不完整或不明确：\n\n'+'\n'.join(prepared['questions']),
                             status='user_clarification',questions=prepared['questions'])
        phase='state_error'
        with locked(root):
            path=safe(root, STATE)
            old=read(path)[1] if path.exists() else None
            if previous_inquiry(old):
                if action not in ('history','inquiry'):
                    return refresh_inquiry()
                old=None
            if old is not None:
                validate_state(old)
                if action not in ('history','inquiry') and any(
                        {'net_weight_kg','package_count'} & set(scope) or scope.get('date_field') == 'invoice_date'
                        for scope in (old['batch']['query'], old['filters'])):
                    return final('needs_query', '该历史查询使用已撤回的筛选口径，请按主分单或当前运输条件重新查询。')
            if action=='history':
                phase='import_error'
                batch=import_receipts(root,request['receipts'],request['query'])
                state={'protocol':PROTOCOL,'batch':batch,'refs':references(batch),'query_id':query_id(batch),
                       'filters':query(request.get('set',{}),allow_empty=True),
                       'view':{'sort':request.get('sort','source'),'page':1,'page_size':request.get('page_size',5)}}
            elif action=='inquiry':
                target=prepared['target']; required_scope=inquiry.scope(target)
                specification={'strategy':inquiry.STRATEGY,'target':target}
                if 'receipts' in request:
                    phase='import_error'
                    batch=import_receipts(root,request['receipts'],required_scope)
                elif old is not None and old['batch']['query']==required_scope:
                    batch=deepcopy(old['batch'])
                else:
                    return final('needs_new_query','需要先取得当前路线及保护条件下的完整API候选，再按询价流程匹配。',
                                 query=required_scope,normalized_target=target)
                state={'protocol':PROTOCOL,'batch':batch,'inquiry':specification,
                       'refs':references(batch,specification),'query_id':query_id(batch,specification),
                       'filters':query(request.get('set',{}),allow_empty=True),
                       'view':{'sort':request.get('sort','source'),'page':1,'page_size':request.get('page_size',5)}}
            elif old is None:
                return final('needs_query','请先通过本地API取数并导入完整回执，再查看运输费用。')
            else:
                state=deepcopy(old)
                if action=='detail':
                    if request['query_id']!=state['query_id']:
                        return final('stale_reference','费用引用来自旧查询，请按当前查询重新选择。')
                    phase='invalid_request'
                    return render(state,request['reference'],request.get('page',1))
                if action=='filter':
                    conditions=deepcopy(state['filters'])
                    for key in request.get('unset',[]):
                        if key in state['batch']['query'] and key not in conditions:
                            return final('needs_new_query','该条件属于原始取数范围，撤销需要重新调用API；当前数据未改。')
                        conditions.pop(key,None)
                    conditions.update(request.get('set',{}))
                    if not {'date_from','date_to'} & set(conditions):
                        conditions.pop('date_field',None)
                    state['filters']=query(conditions,allow_empty=True)
                    state['view']['page']=1
                elif action=='reset':
                    state['filters']={}; state['view']={'sort':'source','page':1,'page_size':5}
                elif action=='show':
                    if 'sort' in request or 'page_size' in request:
                        state['view']['page']=1
                    for key in ['sort','page_size','page']:
                        if key in request:
                            state['view'][key]=request[key]
            phase='invalid_request'
            result=render(state)
            phase='state_error'
            save(root,state)
            return result
    except (ContractError, ValueError, TypeError, KeyError, OSError, OverflowError, RecursionError):
        return final(phase,MESSAGES[phase])
    except Exception:
        return final('execution_error',MESSAGES['execution_error'])


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--request-file',required=True); parser.add_argument('--workspace',required=True)
    args=parser.parse_args()
    try:
        request=loads(Path(args.request_file).read_bytes())
        print(encode(run(request,args.workspace)).decode())
    except (ContractError,OSError):
        print(encode(final('invalid_request',MESSAGES['invalid_request'])).decode())
