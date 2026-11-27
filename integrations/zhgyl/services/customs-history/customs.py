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

from contract import (customs_fee, FEE_FIELDS, SCHEMA, MAX_BYTES, QUERY_KEYS, ContractError, BILL_FIELDS, DETAIL_FIELDS,
                      ACTIVE_REVISION, encode, integer, loads, matches, merge_pages, norm, number, query,
                      require, sha, validate_entities, validate_source)

PROTOCOL = 'customs-fixed-entry-v1'
LIMITS_ANSWER=('报关代理推荐基于历史报关单据排序，费用区间是历史报关费，不是现行费率或本次正式报价；共享费用不自动分摊到分单或物料。')

STATE = 'uploads/customs-runtime/session.json'
SORTS = {'source','history_date_asc','history_date_desc'}
QUERY_LABELS = {'house_numbers':'分单号','bill_numbers':'费用单号','model':'规格型号',
                'destination':'目的港','dangerous_goods':'危化品属性',
                'carrier':'报关代理','currency':'费用币种','gross_weight_kg':'毛重KG','length_cm':'包装长CM',
                'width_cm':'包装宽CM','height_cm':'包装高CM','package_count':'包装数量',
                'date_from':'日期起','date_to':'日期止','date_field':'日期依据','material_code':'物料编码','destination_code':'目的港代码','contract_numbers':'合同号','master_numbers':'主单号'}
MESSAGES = {
    'invalid_request':'报关请求参数无效，未改变当前查询。请检查条件、动作或分页参数。',
    'state_error':'报关会话完整性校验失败，已停止；这不表示没有历史费用。',
    'import_error':'原始报关JSON或完整分页校验失败，已停止；这不表示没有历史费用。',
    'execution_error':'报关固定入口未完成处理，已停止；这不表示没有历史费用。',
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
    for name in ['uploads', 'uploads/customs-runtime']:
        safe(root, name).mkdir(exist_ok=True)
    path = safe(root, 'uploads/customs-runtime/.lock')
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
    require(set(state['view']) == {'sort','page','page_size'} and state['view']['sort'] in SORTS)
    integer(state['view']['page'], 1, 10000); integer(state['view']['page_size'], 1, 20)


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
        require(isinstance(relative, str) and re.fullmatch(r'uploads/customs-api/[a-f0-9]{32}\.json', relative), 'Invalid raw file handle')
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


def customs_table(rows):
    # Only the formatter supplies line breaks. Every source value is still escaped.
    return '\n'.join(['| 查询关系 | 分单号 | 报关条件及匹配说明 |', '| --- | --- | --- |']+
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
        if not show_identifiers and key in ['house_numbers','bill_numbers']:
            parts.append(('分单范围：指定'+str(len(value))+'条（本次查询条件）') if key=='house_numbers' else
                         '费用账单：指定'+str(len(value))+'张（按费用单精确筛选）')
            continue
        if key=='date_field':
            value={'history_date':'历史业务日期'}[value]
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
    if state['view']['sort'] != 'source':
        order.sort(key=lambda ref: (bills[state['refs'][ref]]['history_date'], bills[state['refs'][ref]]['source_row']),
                   reverse=state['view']['sort'] == 'history_date_desc')
    return records, order


def bill_sections(state,ref,hits,member_page=1,member_size=20,detail=False):
    batch=state['batch'];no=state['refs'][ref]
    bill=next(b for b in batch['bills'] if b['bill_no']==no)
    members=next(c['details'] for c in batch['coverage'] if c['bill_no']==no)
    start=(member_page-1)*member_size;require(start<len(members))
    displayed=members[start:start+member_size]
    houses=list(dict.fromkeys(r['house_no'] for r in members))
    parts=['**'+ref+' 报关记录与报关费**']
    if len(houses)>1:parts.append('**共享报关费，未分摊：覆盖'+str(len(houses))+'个分单，不能作为单一分单或物料的独立费用。**')
    elif len(members)>1:parts.append('本费用单覆盖同一分单的多条物料/包装明细，合计仅计一次，未按物料分摊。')
    if detail:parts+=['费用单号：'+cell(no)+'。']
    parts+=['历史报关费：'+cell(bill['currency'])+' '+(amount(customs_fee(bill)) if customs_fee(bill) is not None else '未提供')+'。']
    lines=[]
    for r in displayed:
        description=['规格型号：'+r['model'],'目的港：'+r['destination']+'；'+r['dangerous_goods'],
          '毛重：'+numeric(r['gross_weight_kg'])+'KG；包装：'+' × '.join(numeric(r[k]) for k in ['length_cm','width_cm','height_cm'])+'CM × '+str(r['package_count'])+'件',
          '历史日期：'+r['history_date'][:10]]
        if state.get('inquiry') and r['id'] in hits:
            changes=inquiry.differences(r,state['inquiry']['target'])
            description+=['匹配差异：'+('；'.join(QUERY_LABELS[c['field']]+' 本次'+str(c['requested'])+' / 历史'+str(c['historical']) for c in changes) if changes else '物料、毛重和尺寸均一致')]
        lines.append(['本次命中' if r['id'] in hits else '同费用单关联补充，未命中',r['house_no'],description])
    parts.append(customs_table(lines))
    parts+=['**单据追溯**',table(['分单号','合同号','主单号'],[[r['house_no'],r['contract_no'],r['master_no']] for r in displayed])]
    if start+len(displayed)<len(members):parts.append('完整关联明细共'+str(len(members))+'条，可按'+ref+'详情翻页查看。')
    if detail:parts.append('来源：'+cell(batch['source']['file'])+'，第'+cell('、'.join(str(r['source_row']) for r in displayed))+'行。')
    return '\n\n'.join(parts)



def match_note(rows,target):
    """Compact differences only from matched rows, never associated bill members."""
    if target is None:return '按历史单据/条件命中'
    changes=[]
    for row in rows:
        for change in inquiry.differences(row,target):
            field=change['field'];requested=change['requested'];historical=change['historical']
            a=numeric(requested) if field!='model' else requested
            b=numeric(historical) if field!='model' else historical
            text=QUERY_LABELS[field]+' 本次'+a+' / 历史'+b
            if text not in changes:changes.append(text)
    if not changes:return '物料、毛重和尺寸均一致'
    return '；'.join(changes[:3]+(['另有'+str(len(changes)-3)+'项差异，见详情'] if len(changes)>3 else []))


def reference_strength(records,target,match_type):
    if match_type!='approximate' or not records:return match_type
    # No model/weight/size equality in ANY final candidate means only protected
    # conditions remain. Do not invent a similarity score or change selection.
    weak=all(norm(r['model'])!=norm(target['model']) and
             number(r['gross_weight_kg'])!=number(target['gross_weight_kg']) and
             not inquiry.size_equal(r,target) for r in records)
    return 'protected_only' if weak else 'partial'


ADVICE_KEYS = ('destination','dangerous_goods','model','gross_weight_kg','length_cm','width_cm','height_cm','package_count')


def plain_items(result):
    return [{k:v for k,v in item.items() if k!='fee_median'} for item in result['items']]


def validate_advice(advice):
    # Accept previously saved state; history never renders or refreshes its advice.
    require(isinstance(advice,dict) and set(advice)=={'basis','profiles','total','items'})
    require(isinstance(advice['basis'],dict) and set(advice['basis'])=={'house_no',*ADVICE_KEYS})
    require(isinstance(advice['items'],list) and len(advice['items'])<=20)
    integer(advice['profiles'],1,10000); integer(advice['total'],0,10000)


def recommendation_section(state):
    target=state['inquiry']['target'];batch=state['batch']
    result=inquiry.recommend(batch['records'],batch['bills'],target)
    return recommendation_parts(plain_items(result),result['total_agents']),result


def recommendation_parts(items,total):
    if not items:
        return ['**报关代理推荐**','当前数据中没有任何报关代理历史，暂无法推荐。']
    first=items[0]
    def reason(item):
        parts=[inquiry.TIERS[item['tier']]+' '+str(item['tier_bills'])+'票']
        if item['same_model_rows']:parts.append('同型号明细'+str(item['same_model_rows'])+'条')
        parts.append('累计'+str(item['total_bills'])+'票')
        return '；'.join(parts)
    def fee(item):
        if item['fee_min'] is None:return '报关费未提供'
        low,high=amount(item['fee_min']),amount(item['fee_max'])
        return item['currency']+' '+(low if low==high else low+'–'+high)
    rows=[[('首选' if item['rank']==1 else str(item['rank'])),item['carrier'],reason(item),item['latest'],fee(item)]
          for item in items]
    parts=['**报关代理推荐**',
           '首选：**'+cell(first['carrier'])+'**。依据：'+cell(reason(first))+'；最近一次'+first['latest']+'；同类历史报关费 '+cell(fee(first))+'。',
           table(['排序','报关代理','推荐依据','最近历史日期','同类历史报关费'],rows),
           '排序规则：先看经验层级（同港同危化且同型号 → 同港同危化 → 同危化其他港 → 同港不同危化 → 其他），再看该层级票数、累计票数、最近日期，最后同币种比较历史费用中位数。共评估'+str(total)+'家代理。']
    if first['tier']>=3:
        parts.append('**提示：没有代理办理过本次目的港与危化属性一致的历史业务，以上为按相近经验给出的推荐，请与代理确认资质与报价。**')
    parts.append('费用区间为历史报关费（含共享费用，未分摊），仅供比价参考，不是本次正式报价。')
    return parts


def render(state,detail_ref=None,member_page=1):
    batch=state['batch'];records,order=selection(state);hits={r['id'] for r in records}
    if detail_ref:
        require(detail_ref in order,'Current reference unavailable');displayed=[detail_ref]
    else:
        size,page=state['view']['page_size'],state['view']['page']
        require(page<=max(1,(len(order)+size-1)//size));displayed=order[(page-1)*size:page*size]
    bill_map={b['bill_no']:b for b in batch['bills']};cover={c['bill_no']:c['details'] for c in batch['coverage']}
    analysis=candidate_result(batch,state.get('inquiry'))
    label={'history':'历史追溯','full':'全量匹配（目的港、物料、毛重、尺寸一致，危化属性一致）','approximate':'近似匹配','no_records':'暂无同目的港及危化属性一致的历史'}[analysis['match_type']]
    recommendation=None
    if state.get('inquiry') and not detail_ref:
        head,recommendation=recommendation_section(state)
        parts=['**报关查询与推荐**','**一、报关代理推荐**','本次条件：'+conditions_text(state['inquiry']['target'])+'。']+head[1:]+['**二、历史参考明细**','匹配方式：'+label+'。']
    else:
        parts=['**报关历史费用查询**']+['匹配方式：'+label+'。','取数条件：'+conditions_text(inquiry.protected_scope(state['inquiry']['target']) if state.get('inquiry') else batch['query'])+'。']
    if state['filters']:parts.append('附加筛选：'+conditions_text(state['filters'])+'。')
    if state.get('inquiry'):
        if detail_ref:parts.append('本次条件：'+conditions_text(state['inquiry']['target'])+'。')
        if analysis.get('steps'):
            labels={'material':'物料','weight':'毛重','size':'尺寸'}
            parts.append('同港同危化候选'+str(analysis['pool_count'])+'条；'+ ' → '.join(labels[x['criterion']]+' '+str(x['before'])+'→'+str(x['after'])+('（无相同，保留）' if x['decision']=='keep_previous' else '') for x in analysis['steps'])+'。')
    strength=reference_strength(records,state.get('inquiry',{}).get('target'),analysis['match_type'])
    if strength=='protected_only':
        parts.append('**弱匹配提示：当前仅满足目的港、危化属性等保护条件；物料、毛重和尺寸均未匹配，可比性较弱。请核对详情，不宜直接据此比较费用或确定本次报价。**')
    elif strength=='partial':
        parts.append('近似参考存在条件差异，请逐项核对；历史费用不代表本次报价。')
    parts.append('命中'+str(len(records))+'条报关明细、'+str(len(order))+'张费用单，本次展示'+str(len(displayed))+'张。')
    metadata=[]
    if displayed:
        rows=[]
        for ref in displayed:
            no=state['refs'][ref];b=bill_map[no];members=cover[no];matched=sum(r['id'] in hits for r in members)
            houses={r['house_no'] for r in members}
            matched_rows=[r for r in members if r['id'] in hits]
            coverage=str(matched)+'/'+str(len(members))+'条；'+str(len(houses))+'分单'
            if len(houses)>1:coverage+='；共享报关费，未分摊'
            elif len(members)>1:coverage+='；多明细合计，未分摊'
            rows.append([ref,b['carrier'],b['history_date'][:10],b['currency']+' '+(amount(customs_fee(b)) if customs_fee(b) is not None else '未提供'),match_note(matched_rows,state.get('inquiry',{}).get('target')),coverage])
            metadata.append({'reference':ref,'bill_no':no,'carrier':b['carrier'],'coverage_count':len(members),'house_count':len(houses),'matched_count':matched,'customs_fee_amount':customs_fee(b),'currency':b['currency']})
        parts+=['**历史费用总览（一费用单一行）**',table(['费用引用','报关代理','历史日期','历史报关费','匹配差异','命中/覆盖'],rows)]
        if detail_ref:
            parts.append(bill_sections(state,detail_ref,hits,member_page,detail=True))
        else:
            parts.append('报关费、完整关联明细及合同/主单/分单在对应费用详情中查看。')
    else:parts.append('当前目的港、危化属性及筛选条件下暂无可用历史记录。')
    has_more=not detail_ref and state['view']['page']*state['view']['page_size']<len(order)
    parts.append('还有下一页，可继续问“下一页”。' if has_more else '本次结果已到末页。')
    next_detail=('可继续问“查看'+displayed[0]+'详情”。') if displayed else ''
    parts.append('历史费用仅作参考；历史日期按表中业务日期展示，不作为本次报价。'+next_detail)
    answer='\n\n'.join(parts);require(len(answer.encode())<=128*1024)
    extra={}
    if recommendation is not None:
        extra['recommendation']=[{'rank':i['rank'],'carrier':i['carrier'],'tier':i['tier'],'tier_bills':i['tier_bills'],
                                  'total_bills':i['total_bills'],'latest':i['latest'],'currency':i['currency'],
                                  'fee_min':str(i['fee_min']) if i['fee_min'] is not None else None,'fee_max':str(i['fee_max']) if i['fee_max'] is not None else None} for i in recommendation['items']]
    outcome='ok' if records else ('recommended' if recommendation and recommendation['items'] else 'no_records')
    return final(outcome,answer,**extra,query_id=state['query_id'],match={k:v for k,v in analysis.items() if k!='records'},reference_strength=strength,active_filters=state['filters'],counts={'matched_details':len(records),'unique_bills':len(order),'shown_bills':len(displayed)},has_more=has_more,bills=metadata)



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
    if action=='inquiry':
        require('target' in request); inquiry.prepare(request['target'])
    if 'set' in request:
        query(request['set'], allow_empty=True)
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
            if old is not None:
                validate_state(old)
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
                elif old is not None and old['batch']['query']==required_scope and old['batch']['source']['revision']==ACTIVE_REVISION:
                    batch=deepcopy(old['batch'])
                else:
                    return final('needs_new_query','需要先取得完整的报关代理历史候选，再按询价流程推荐与匹配。',
                                 query=required_scope,normalized_target=target)
                state={'protocol':PROTOCOL,'batch':batch,'inquiry':specification,
                       'refs':references(batch,specification),'query_id':query_id(batch,specification),
                       'filters':query(request.get('set',{}),allow_empty=True),
                       'view':{'sort':request.get('sort','source'),'page':1,'page_size':request.get('page_size',5)}}
            elif old is None:
                return final('needs_query','请先通过本地API取数并导入完整回执，再查看报关费用。')
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
    except (ContractError, ValueError, TypeError, KeyError, OSError, OverflowError, RecursionError) as error:
        # Bounded diagnostic codes contain no supplied values or file paths.
        # The user-facing answer stays fixed; this helps audit parameter failures.
        rule=str(error) if isinstance(error,ContractError) else type(error).__name__
        return final(phase,MESSAGES[phase],validation_rule=rule)
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
