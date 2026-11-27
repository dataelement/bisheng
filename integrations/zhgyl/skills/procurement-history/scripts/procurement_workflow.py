"""Manual procurement dialogue workflow. No HTTP, generated code or customer-system writes."""
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from types import SimpleNamespace
import uuid
from zoneinfo import ZoneInfo

MAX_ITEMS = 20
MAX_CONFIRMATIONS = 100
LEGACY = {'history', 'show', 'filter', 'compare', 'suppliers', 'reset'}
EXTRA = {'batch', 'batch_summary', 'resolve', 'choose', 'confirm', 'confirmations', 'unconfirm', 'explain_limits', 'api_failure', 'help'}
CRITERIA = {'set', 'unset', 'sort', 'page_size', 'purchaser'}
PHASES = {'ready', 'awaiting_model_check', 'candidates', 'selected', 'no_similar', 'no_recommendation'}
BASE = Path('uploads/procurement-runtime')


def now():
    return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')


def save(p, path, value):
    p.batch_session.save_state(p.inside(path), value)


def read(p, path, default=None):
    file = p.inside(path)
    return p.read_json(file) if file.exists() else deepcopy(default)


def allowed(p, req, keys):
    if set(req) - (set(keys) | {'action', 'item_index'}):
        raise p.Stop('invalid_request', '动作包含不受支持的字段；未改动已有记录。')


def pending_pattern(model):
    """Use a literal family boundary, never an unconstrained all-history regex."""
    token = model.strip().split()[0]
    if token == model.strip() and '-' in token:
        token = token.rsplit('-', 1)[0]
    if len(re.sub(r'[^\w]', '', token)) < 4:
        return None, None
    pattern = '.*' + re.escape(token).replace(r'\-', '-') + '.*'
    return (token, pattern) if len(pattern) <= 256 else (None, None)


def context(p, registry):
    value = registry.get('workflow', {}) if registry else {}
    if not isinstance(value, dict) or (value and value.get('phase') not in PHASES):
        raise p.Stop('state_integrity_error', '型号处理状态无法核验；未将状态错误当作无历史。')
    if value.get('selected_model') and value['selected_model'] not in [e['model'] for e in registry['entries']]:
        raise p.Stop('state_integrity_error', '已选相近型号不属于当前候选；未借用其他型号数据。')
    return deepcopy(value)


def criteria(p, reg, req, old):
    result = deepcopy(old.get('criteria', {}))
    if reg['entries']:
        state = p.read_json(p.inside(reg['entries'][0]['session']))
        result.update(set=state.get('filters', {}), sort=state.get('sort', 'time_desc'),
                      page_size=state.get('page_size', 20))
        if state.get('purchaser'):
            result['purchaser'] = state['purchaser']
    else:
        result.setdefault('set', {})
        result['set'].update(req.get('set', {}))
        for key in req.get('unset', []):
            result['set'].pop(key, None)
        for key in ('sort', 'page_size', 'purchaser'):
            if key in req:
                result[key] = req[key]
    result.pop('unset', None)
    if req.get('action') == 'reset':
        result.update(set={}, sort='time_desc')
    return result


def one(p, request, *, publish_catalog=True):
    req = deepcopy(request)
    file = p.inside(p.runtime_root() / p.REGISTRY)
    before = file.read_bytes() if file.exists() else None
    catalog_file = p.inside(p.runtime_root() / p.RECOMMENDATIONS)
    catalog_before = catalog_file.read_bytes() if publish_catalog and catalog_file.exists() else None
    previous = p.load_registry()
    old = context(p, previous)
    if 'page_files' not in req and old.get('selected_model') and 'target_model' not in req:
        req['target_model'] = old['selected_model']
    try:
        result = p.execute(req, publish_catalog=publish_catalog)
        if result['outcome'] not in {'ok', 'no_records'}:
            return result
        reg = p.load_registry()
        if reg is None:
            return result
        same = previous and previous.get('input_signature') == reg.get('input_signature')
        ctx = old if 'page_files' not in req or same else {}
        query = reg['manifest']['query']
        target = query['model'] if query.get('match_mode', 'exact') == 'exact' else reg['manifest'].get('reference_model', query['model'])
        ctx.setdefault('original_target', target)
        ctx.setdefault('intent', 'suppliers' if req['action'] == 'suppliers' else 'history')
        if req['action'] in {'history', 'suppliers'}:
            ctx['intent'] = req['action']
        ctx['criteria'] = criteria(p, reg, req, ctx)
        if not reg['entries'] and query.get('match_mode', 'exact') == 'exact':
            family, pattern = pending_pattern(target)
            ctx.update(phase='awaiting_model_check', original_target=target, family=family, pattern=pattern)
            result['answer'] += '\n\n未找到精确型号 **' + p.cell(target) + '**。请核对是否需要修正：提供新型号后我会重新精确查询；确认“型号无误／不需要修正”后，我会找最多3个近似型号，各自独立展示。'
            if ctx.get('intent') == 'suppliers':
                result['answer'] += '\n\n在核对型号之前，先按当前物料信息给出无历史供应商推荐：\n\n' + p.recommend_for(target, ctx['criteria'].get('purchaser'), query_id=reg['query_id'],
                                                 filters=ctx['criteria']['set'])
            else:
                p.invalidate_recommendation(target)
                result['answer'] += '\n\n如需按物料推荐供应商，可直接说“推荐供应商”。'
        elif not reg['entries']:
            ctx.update(phase='no_similar')
            result['answer'] = ('在本次已限定范围内，没有找到 **' + p.cell(ctx['original_target']) + '** 的近似型号历史，不重复放宽查询或补造历史记录。本次结束。\n\n来源：' + p.cell(reg.get('source', {}).get('file')) + '。')
            if ctx.get('intent') == 'suppliers':
                result['answer'] += '\n\n以下按物料信息给出无历史供应商推荐：\n\n' + p.recommend_for(
                    ctx['original_target'], ctx['criteria'].get('purchaser'),
                    query_id=reg['query_id'], filters=ctx['criteria']['set'])
            else:
                p.invalidate_recommendation(ctx['original_target'])
        elif query.get('match_mode') == 'regex' and ('page_files' in req and not same):
            ctx.update(phase='candidates', original_target=target)
            ctx.pop('selected_model', None)
            result['answer'] += '\n\n相近型号选择（不是历史明细序号）：\n\n' + p.table(['型号序号', '相近型号'], [[i, e['model']] for i, e in enumerate(reg['entries'], 1)])
            example = 2 if len(reg['entries']) > 1 else 1
            result['answer'] += '\n\n可以说“选第' + str(example) + '个型号继续”；选中后只处理该型号，不跨型号计算价格。'
        elif result['outcome'] == 'no_records':
            ctx.setdefault('phase', 'ready')
            result['answer'] += '\n\n该型号原批次有历史记录，只是当前筛选后为空；请调整或撤销筛选，无需修改型号，也不自动转近似查询。'
        else:
            if ctx.get('phase') not in {'candidates', 'selected'}:
                ctx['phase'] = 'no_recommendation' if req['action'] == 'suppliers' and all(m.get('supplier_counts', {}).get('total_items') == 0 for m in result.get('models', [])) else 'ready'
        # A corrected exact import has the same trace regardless of whether
        # the model called history/suppliers or the explicit resolve action.
        if ('page_files' in req and not same and old.get('phase') == 'awaiting_model_check'
                and query.get('match_mode', 'exact') == 'exact'
                and old.get('original_target') != target):
            ctx['corrected_from'] = old['original_target']
            result['answer'] = '已将待查型号从 **' + p.cell(old['original_target']) + '** 修正为 **' + p.cell(target) + '**。\n\n' + result['answer']
        reg['workflow'] = ctx
        save(p, p.runtime_root() / p.REGISTRY, reg)
        result['workflow'] = {k: ctx.get(k) for k in ('phase', 'original_target', 'selected_model', 'corrected_from')}
        return result
    except Exception:
        if before is not None:
            file.write_bytes(before)
        elif file.exists():
            file.unlink()
        if publish_catalog:
            if catalog_before is not None:
                catalog_file.write_bytes(catalog_before)
            elif catalog_file.exists():
                catalog_file.unlink()
        raise


def resolve(p, req):
    allowed(p, req, {'decision', 'model', 'page_files', 'match_mode', 'reference_model', 'intent', *CRITERIA})
    reg = p.load_registry()
    ctx = context(p, reg)
    if not reg or ctx.get('phase') != 'awaiting_model_check':
        # A new, fully bound exact response does not need a previous failed
        # query. Natural language may call a model switch a correction; both
        # routes are read-only imports of the same verified new API pages.
        # Never normalize an unsolicited regex/keep into an approved match.
        if req.get('decision') != 'correct':
            raise p.Stop('invalid_request', '当前没有待核对的精确型号；筛选后为空不能当作型号查不到。')
        if not req.get('page_files'):
            raise p.Stop('source_unavailable', '新型号尚未取得本轮精确API结果，不能复用旧型号数据。')
        if (not isinstance(req.get('model'), str) or not req['model'].strip() or
                req.get('match_mode', 'exact') != 'exact' or 'reference_model' in req):
            raise p.Stop('invalid_request', '新型号须绑定新的精确结果，不能借修正动作提前近似。')
        intent = req.get('intent', 'history')
        if intent not in {'history', 'suppliers'}:
            raise p.Stop('invalid_request', '新查询目的仅支持历史或供应商。')
        base = {'action': intent, 'model': req['model'], 'page_files': req['page_files']}
        base.update(deepcopy(ctx.get('criteria', {})))
        base.update({k: req[k] for k in CRITERIA if k in req})
        result = one(p, base)
        if result['outcome'] in {'ok', 'no_records'}:
            result['answer'] = '已按新型号 **' + p.cell(req['model']) + '** 查询，本轮使用新的精确API结果。\n\n' + result['answer']
        return result
    decision = req.get('decision')
    if decision not in {'keep', 'correct'}:
        raise p.Stop('needs_clarification', '请给出修正后的型号，或确认原型号无误。', True)
    if not req.get('page_files'):
        raise p.Stop('source_unavailable', '本轮尚未取得相应API原始结果；不能用旧型号文件代替本次查询。')
    old_target = ctx['original_target']
    if decision == 'keep':
        family, pattern = pending_pattern(old_target)
        if not pattern:
            raise p.Stop('needs_clarification', '型号过短或无法确定有限的近似范围，请补充主号；无需再次确认是否允许近似查询。', True)
        if req.get('model') != pattern or req.get('reference_model', old_target) != old_target or req.get('match_mode', 'regex') != 'regex':
            raise p.Stop('invalid_request', '近似查询范围与已核对型号不一致；应限定原型号主号，不得扩大到全部历史。')
        base = dict(action=req.get('intent', ctx['intent']), model=pattern, match_mode='regex', reference_model=old_target, page_files=req['page_files'])
    else:
        if not isinstance(req.get('model'), str) or not req['model'].strip() or req.get('match_mode', 'exact') != 'exact' or 'reference_model' in req:
            raise p.Stop('invalid_request', '修正后须按新的完整型号精确查询。')
        base = dict(action=req.get('intent', ctx['intent']), model=req['model'], page_files=req['page_files'])
    base.update(deepcopy(ctx.get('criteria', {})))
    base.update({k: req[k] for k in CRITERIA if k in req})
    result = one(p, base)
    if (decision == 'correct' and result['outcome'] in {'ok', 'no_records'}
            and result.get('workflow', {}).get('corrected_from') != old_target):
        result['answer'] = '已将待查型号从 **' + p.cell(old_target) + '** 修正为 **' + p.cell(req['model']) + '**。\n\n' + result['answer']
    return result


def choose(p, req):
    allowed(p, req, {'candidate_position', 'target_model', 'intent', *CRITERIA})
    reg = p.load_registry()
    ctx = context(p, reg)
    if not reg or ctx.get('phase') not in {'candidates', 'selected'}:
        raise p.Stop('needs_clarification', '请先取得当前相近型号候选，再选择其中一个型号。', True)
    pos, name = req.get('candidate_position'), req.get('target_model')
    if pos is None and name is None:
        raise p.Stop('needs_clarification', '请提供相近型号序号或完整候选型号。', True)
    if pos is not None:
        if type(pos) is not int or not 1 <= pos <= len(reg['entries']):
            raise p.Stop('invalid_selection', '型号序号不属于当前候选；未默认选择或跨型号组合。', True)
        selected = reg['entries'][pos - 1]['model']
        # A natural request can identify one candidate by both its displayed
        # position and model. Accept redundant agreement, never choose a side
        # when the two selectors conflict or the model is not an exact candidate.
        if name is not None and (not isinstance(name, str) or name != selected):
            raise p.Stop('needs_clarification', '候选序号与型号不一致，请确认要选择哪一个；当前选择未改变。', True)
        name = selected
    elif not isinstance(name, str) or name not in [e['model'] for e in reg['entries']]:
        raise p.Stop('invalid_selection', '所选型号不属于当前候选。', True)
    intent = req.get('intent', ctx.get('intent', 'history'))
    if intent not in {'history', 'suppliers'}:
        raise p.Stop('invalid_request', '型号选中后只支持历史明细或供应商视图。')
    changes = {k: req[k] for k in CRITERIA if k in req}
    if changes:
        p.validate_request({'action': 'filter', 'target_model': name, **changes})
    ctx.update(phase='selected', selected_model=name, intent=intent)
    reg['workflow'] = ctx
    save(p, p.runtime_root() / p.REGISTRY, reg)
    result = one(p, {'action': intent, 'target_model': name, **changes, 'page': 1})
    result['answer'] = '已选中相近型号 **' + p.cell(name) + '**；原始目标是 **' + p.cell(ctx['original_target']) + '**，两者不自动视为可替代。\n\n' + result['answer']
    return result


def batch_state(p):
    value = read(p, BASE / 'manual-batch.json')
    if value is None:
        return None
    if (not isinstance(value, dict) or value.get('version') != 1 or
            not re.fullmatch(r'[a-f0-9]{32}', str(value.get('id', ''))) or
            not isinstance(value.get('items'), list) or not 1 <= len(value['items']) <= MAX_ITEMS):
        raise p.Stop('state_integrity_error', '多型号处理状态损坏，不能按空结果展示。')
    for i, item in enumerate(value['items'], 1):
        if item.get('index') != i or item.get('root') != str(BASE / 'manual-batches' / value['id'] / ('item-' + str(i))):
            raise p.Stop('state_integrity_error', '多型号行号与隔离状态不一致。')
    return value


def item_result(p, item, req):
    with p.scope(Path(item['root'])):
        try:
            result = dispatch_local(p, req)
            reg = p.load_registry() if result['outcome'] in {'ok', 'no_records', 'confirmed', 'already_confirmed'} else None
            ctx = context(p, reg)
        except p.Stop as err:
            result = p.final(err.outcome, p.cell(err.message), clarify=err.clarify)
            ctx = {}
        except Exception:
            result = p.final('execution_error', '该项状态或原始文件无法核验；不是无历史，其他项继续处理。')
            ctx = {}
    phase = ctx.get('phase', 'error')
    item.update(status=phase, last_outcome=result['outcome'], updated_at=now(),
                selected_model=ctx.get('selected_model'), current_model=ctx.get('original_target', item['model']))
    if result['outcome'] not in {'ok', 'no_records', 'confirmed', 'already_confirmed'}:
        item['status'] = 'error'
    item['shown'] = sum(m.get('counts', {}).get('shown', 0) for m in result.get('models', []))
    return result


def validate_rows(p, state):
    for item in state['items']:
        if item['status'] == 'not_fetched':
            continue
        try:
            with p.scope(Path(item['root'])):
                reg = p.load_registry()
                ctx = context(p, reg)
                if not reg or not ctx:
                    raise ValueError('Missing item state')
                if item.get('last_outcome') not in {'ok', 'no_records', 'confirmed', 'already_confirmed'}:
                    item['status'] = 'error'
                    continue
                item['status'] = ctx['phase']
                item['current_model'] = ctx['original_target']
                item['selected_model'] = ctx.get('selected_model')
        except Exception:
            item['status'] = 'error'


def summary(p, state, results=None):
    validate_rows(p, state)
    pending = sum(i['status'] in {'awaiting_model_check', 'candidates', 'not_fetched'} for i in state['items'])
    errors = sum(i['status'] == 'error' for i in state['items'])
    done = len(state['items']) - pending - errors
    names = {'ready': '已查询', 'selected': '已选型号', 'awaiting_model_check': '待核对型号',
             'candidates': '待选近似型号', 'no_similar': '无近似历史', 'no_recommendation': '历史供应商未过名录，已按名录推荐',
             'error': '处理失败，未当作无历史', 'not_fetched': '待取完整数据'}
    answer = ['本批共' + str(len(state['items'])) + '项：完成' + str(done) + '项，待补充/选择' + str(pending) + '项，失败' + str(errors) + '项。型号分别处理，价格不合并。',
              p.table(['输入项', '输入型号', '当前型号', '状态'],
                      [[i['index'], i['model'], i.get('selected_model') or i.get('current_model', i['model']), names.get(i['status'], i['status'])] for i in state['items']])]
    if results and len(results) <= 3 and sum(len(r['answer'].encode()) for _, r in results) <= 90000:
        for item, result in results:
            answer.append('## 第' + str(item['index']) + '项 · ' + p.cell(item['model']) + '\n\n' + result['answer'])
    else:
        answer.append('可说“查看第2项”“修正第2项型号为…”或“第2项不需要修正”；本表保留全部输入项状态，不把待处理项计为完成。')
    return p.final('partial' if pending or errors else 'ok', '\n\n'.join(answer))


def batch(p, req):
    allowed(p, req, {'items', 'intent', *CRITERIA})
    items, intent = req.get('items'), req.get('intent', 'history')
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS or intent not in {'history', 'suppliers'}:
        raise p.Stop('invalid_request', '一次支持1—20个手动输入项，请拆分超量输入；每个型号单独处理。')
    for item in items:
        if not isinstance(item, dict) or set(item) - {'model', 'page_files', 'error_kind', *CRITERIA} or not isinstance(item.get('model'), str) or not item['model'].strip():
            raise p.Stop('invalid_request', '每项须有完整型号及其自己的API原始页，不能混用型号文件。')
    signature = sha256(json.dumps(req, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    old = batch_state(p)
    if old and old.get('signature') == signature:
        old['active'] = True
        save(p, BASE / 'manual-batch.json', old)
        return summary(p, old)
    state = {'version': 1, 'id': uuid.uuid4().hex, 'signature': signature, 'active': True, 'active_index': None, 'items': []}
    results = []
    for i, source in enumerate(items, 1):
        item = {'index': i, 'model': source['model'], 'status': 'not_fetched',
                'root': str(BASE / 'manual-batches' / state['id'] / ('item-' + str(i)))}
        state['items'].append(item)
        if source.get('error_kind'):
            if source.get('page_files') or source['error_kind'] not in {'api_error','invalid_api_response','file_error'}:
                raise p.Stop('invalid_request', '同一输入项不能同时声明有效原始页和接口失败。')
            item.update(status='error', last_outcome='source_unavailable', error_kind=source['error_kind'])
            results.append((item, api_failure(p, {'action':'api_failure','model':source['model'],'error_kind':source['error_kind']})))
            continue
        if not source.get('page_files'):
            continue
        action = {'action': intent, **{k: req[k] for k in CRITERIA if k in req}, **source}
        results.append((item, item_result(p, item, action)))
    save(p, BASE / 'manual-batch.json', state)
    return summary(p, state, results)


def ledger(p):
    value = read(p, BASE / 'confirmations/index.json', {'version': 1, 'records': []})
    if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('records'), list) or len(value['records']) > MAX_CONFIRMATIONS:
        raise p.Stop('state_integrity_error', '确认记录索引无法核验，未覆盖或伪装成空记录。')
    if len({r.get('id') for r in value['records'] if isinstance(r, dict)}) != len(value['records']):
        raise p.Stop('state_integrity_error', '确认记录索引包含重复或无效标识。')
    for record in value['records']:
        if not isinstance(record, dict) or not re.fullmatch(r'[a-f0-9]{32}', str(record.get('id', ''))):
            raise p.Stop('state_integrity_error', '确认记录标识无法核验。')
    return value


def load_confirmation(p, ident):
    if not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9]{32}', ident):
        raise p.Stop('invalid_selection', '请使用本对话已展示的完整确认记录号。', True)
    data = read(p, BASE / 'confirmations' / (ident + '.json'))
    if not isinstance(data, dict) or data.get('id') != ident or not isinstance(data.get('evidence'), dict) or not isinstance(data.get('events'), list):
        raise p.Stop('state_integrity_error', '确认记录不存在或内容无法核验。')
    digest = sha256(json.dumps(data['evidence'], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if (len(data['events']) not in {1, 2} or data['events'][0].get('status') != '已确认' or
            (len(data['events']) == 2 and data['events'][1].get('status') != '已撤销') or
            any(not isinstance(event.get('at'), str) for event in data['events'])):
        raise p.Stop('state_integrity_error', '确认状态变更历史无法核验。')
    if data.get('evidence_sha256') != digest:
        raise p.Stop('state_integrity_error', '确认依据已变化；没有将损坏记录当作有效确认。')
    return data


def confirmation_text(p, data):
    ev, event = data['evidence'], data['events'][-1]
    return ('当前对话确认记录：**' + p.cell(event['status']) + '**\n\n型号：' + p.cell(ev['model']) +
            '；本次甲方：' + p.cell(ev.get('purchaser') or '未指定') + '；供应商：' + p.cell(ev['supplier_names']) +
            '。\n\n记录号：`' + data['id'] + '`\n\n记录时间：' + event['at'] +
            '。确认人为当前对话用户，本功能未单独核验其业务身份。\n\n已保留候选、名录版本及价格依据，可查看或撤销。仅记录本次询价对象选择，不代表已下单或已写入客户业务系统；记录保留当时条件，不自动随当前型号或甲方变化。')


def confirm(p, req):
    allowed(p, req, {'supplier_id', 'supplier_name', 'target_model'})
    sid, name = req.get('supplier_id'), req.get('supplier_name')
    if (sid is None) == (name is None) or not isinstance(sid if sid is not None else name, str) or not (sid or name).strip():
        raise p.Stop('needs_clarification', '请明确选择哪家已展示的历史供应商作为询价对象。', True)
    reg = p.load_registry()
    ctx = context(p, reg)
    target = req.get('target_model') or ctx.get('selected_model')
    catalog = catalog_choice(p, reg, ctx, target, sid, name)
    if catalog:
        return confirm_catalog(p, ctx, *catalog)
    if name and re.fullmatch(r'c[0-9]{2,}', p.engine.norm(name)):
        raise p.Stop('invalid_selection', '该名录候选编号不属于当前结果，请查看当前候选后再确认。', True)
    if not reg or not reg['entries']:
        raise p.Stop('invalid_selection', '当前没有可确认的推荐供应商；请先查看该型号的供应商推荐。', True)
    if not target and len(reg['entries']) != 1:
        raise p.Stop('needs_clarification', '请先选定一个型号，再确认该型号的供应商。', True)
    target = target or reg['entries'][0]['model']
    entry = next((e for e in reg['entries'] if e['model'] == target), None)
    if not entry:
        raise p.Stop('invalid_selection', '型号不属于当前查询结果。', True)
    previous_result = read(p, p.runtime_root() / 'queries' / reg['query_id'] / (Path(entry['session']).stem + '-result.json'))
    if not previous_result or previous_result.get('view') != 'suppliers':
        raise p.Stop('needs_clarification', '请先查看该型号当前的供应商候选及名单结论，再确认询价对象。', True)
    candidates = [s for s in previous_result.get('suppliers', []) if (s['supplier_id'] == sid if sid is not None else any(p.engine.norm(n) == p.engine.norm(name) for n in s['supplier_names']))]
    if not candidates:
        raise p.Stop('invalid_selection', '该供应商不在当前已展示的推荐列表中；被甲方名录排除或尚未展示的供应商不能直接确认。', True)
    if len({s['supplier_id'] for s in candidates}) != 1:
        raise p.Stop('needs_clarification', '存在同名不同主体，请按已展示供应商标识确认。', True)
    fresh = one(p, {'action': 'suppliers', 'target_model': target}, publish_catalog=False)
    if fresh['outcome'] != 'ok':
        return fresh
    reg = p.load_registry()
    actual = read(p, p.runtime_root() / 'queries' / reg['query_id'] / (Path(entry['session']).stem + '-result.json'))
    current = [s for s in actual.get('suppliers', []) if s['supplier_id'] == candidates[0]['supplier_id']]
    if not current:
        raise p.Stop('invalid_selection', '候选或名录状态已变化，请重新查看后确认。', True)
    ev = {'model': target, 'original_target': ctx.get('original_target', target), 'purchaser': actual.get('purchaser'),
          'supplier_id': current[0]['supplier_id'], 'supplier_names': current[0]['supplier_names'],
          'query_id': reg['query_id'], 'source': actual.get('source'), 'active_filters': actual.get('active_filters'),
          'sort': actual.get('query', {}).get('sort'), 'candidate_evidence': current,
          'scope': 'current_chat_inquiry_object_only_not_customer_order'}
    digest = sha256(json.dumps(ev, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    index = ledger(p)
    for old in index['records']:
        if old.get('evidence_sha256') == digest:
            data = load_confirmation(p, old['id'])
            if data['evidence_sha256'] != old['evidence_sha256']:
                raise p.Stop('state_integrity_error', '确认记录与索引依据不一致。')
            if data['events'][-1]['status'] == '已确认':
                return p.final('already_confirmed', '本次选择已有确认记录，未重复保存。\n\n' + confirmation_text(p, data))
    if len(index['records']) >= MAX_CONFIRMATIONS:
        raise p.Stop('state_budget_exceeded', '当前对话确认记录已达100条；保留原记录，本次未再写入。')
    ident = uuid.uuid4().hex
    data = {'version': 1, 'id': ident, 'evidence': ev, 'evidence_sha256': digest, 'events': [{'status': '已确认', 'at': now()}]}
    save(p, BASE / 'confirmations' / (ident + '.json'), data)
    index['records'].append({'id': ident, 'evidence_sha256': digest})
    save(p, BASE / 'confirmations/index.json', index)
    return p.final('confirmed', confirmation_text(p, data))


def saved_recommendation(p, model):
    _, data = p.recommendation_cache()
    value = data.get(p.engine.norm(model)) if model else None
    return value if isinstance(value, dict) and isinstance(value.get('items'), list) else None


def catalog_choice(p, reg, ctx, target, sid, name):
    """Resolve only a catalog lead shown for the active query and criteria."""
    if not reg or sid is not None:
        return None
    selected = ctx.get('selected_model')
    if selected and p.engine.norm(target) != p.engine.norm(selected):
        raise p.Stop('invalid_selection', '该型号已不是当前选中的相近型号，请重新选择后确认。', True)

    model = target or ctx.get('original_target')
    entry = next((e for e in reg['entries'] if p.engine.norm(e['model']) == p.engine.norm(model)), None)
    if entry:
        state = p.read_json(p.inside(entry['session']))
        filters, purchaser = state['filters'], state.get('purchaser')
    elif target:
        return None
    else:
        current = ctx.get('criteria', {})
        filters, purchaser = current.get('set', {}), current.get('purchaser')
    rec = saved_recommendation(p, model)
    if (not rec or rec.get('purchaser') != purchaser
            or rec.get('selection') != {'query_id': reg['query_id'], 'filters': filters}):
        return None
    selector = p.engine.norm(name)
    hits = [item for item in rec['items'] if item.get('group') == 'catalog'
            and selector in (p.engine.norm(item.get('name')), p.engine.norm(item.get('candidate_ref')))]
    return (rec['model'], rec, hits[0]) if len(hits) == 1 else None


def confirm_catalog(p, ctx, model, rec, item):
    ev = {'model': model, 'original_target': ctx.get('original_target', model), 'purchaser': rec.get('purchaser'),
          'supplier_id': None, 'supplier_names': [item['name']], 'recommendation': item,
          'query_id': rec['selection']['query_id'], 'active_filters': rec['selection']['filters'],
          'catalog_source': rec.get('source'), 'material_profile': rec.get('profile'),
          'scope': 'current_chat_inquiry_object_only_not_customer_order'}
    digest = sha256(json.dumps(ev, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    index = ledger(p)
    for old in index['records']:
        if old.get('evidence_sha256') == digest:
            data = load_confirmation(p, old['id'])
            if data['events'][-1]['status'] == '已确认':
                return p.final('already_confirmed', '本次选择已有确认记录，未重复保存。\n\n' + confirmation_text(p, data))
    if len(index['records']) >= MAX_CONFIRMATIONS:
        raise p.Stop('state_budget_exceeded', '当前对话确认记录已达100条；保留原记录，本次未再写入。')
    ident = uuid.uuid4().hex
    data = {'version': 1, 'id': ident, 'evidence': ev, 'evidence_sha256': digest, 'events': [{'status': '已确认', 'at': now()}]}
    save(p, BASE / 'confirmations' / (ident + '.json'), data)
    index['records'].append({'id': ident, 'evidence_sha256': digest})
    save(p, BASE / 'confirmations/index.json', index)
    return p.final('confirmed', confirmation_text(p, data) + '\n\n该对象来自名录候选' + str(item.get('candidate_ref') or '') + '（' + str(item.get('match_label') or '名录线索') + '），本次结果中没有其本型号历史供货证据；候选编号不表示排名，询价前请复核主体与产品适用范围。')


def confirmations(p, req):
    allowed(p, req, {'confirmation_id'})
    index = ledger(p)
    if req.get('confirmation_id'):
        if req['confirmation_id'] not in [r['id'] for r in index['records']]:
            raise p.Stop('invalid_selection', '该记录号不属于当前对话。')
        data = load_confirmation(p, req['confirmation_id'])
        return p.final('ok', confirmation_text(p, data))
    rows = []
    for record in index['records']:
        data = load_confirmation(p, record['id'])
        if data['evidence_sha256'] != record['evidence_sha256']:
            raise p.Stop('state_integrity_error', '确认记录与索引依据不一致。')
        rows.append([data['id'], data['evidence']['model'], data['evidence']['supplier_names'], data['events'][-1]['status']])
    return p.final('ok', '当前对话共' + str(len(rows)) + '条确认记录；未查询或写入客户业务系统。\n\n' + (p.table(['记录号', '型号', '供应商', '状态'], rows) if rows else '尚无确认记录。'))


def unconfirm(p, req):
    allowed(p, req, {'confirmation_id'})
    index = ledger(p)
    ident = req.get('confirmation_id')
    if ident is None and len(index['records']) == 1:
        ident = index['records'][0]['id']
    if ident not in [r['id'] for r in index['records']]:
        raise p.Stop('needs_clarification', '请提供本对话需要撤销的完整确认记录号。', True)
    data = load_confirmation(p, ident)
    if data['events'][-1]['status'] != '已撤销':
        data['events'].append({'status': '已撤销', 'at': now()})
        save(p, BASE / 'confirmations' / (ident + '.json'), data)
    return p.final('ok', confirmation_text(p, data))


def limits(p, req):
    allowed(p, req, {'topic'})
    if req.get('topic') == 'delivery':
        answer = '交付时效当前尚未接通，不能按交付表现排序。客户口径为“货物发票日期－物料交付时间”，需补发票日期与采购明细/批次关联，并确认交付基准及分批、汇总口径。现有合同期望交付日期可作候选基准，订单确认时间不替代交付；本轮未输出交付排名，可继续查看历史价格和供应商。'
    elif req.get('topic') == 'sourcing':
        return sourcing(p)
    else:
        raise p.Stop('invalid_request', '当前能力说明仅支持交付时效或无历史反向寻源。')
    return p.final('capability_unavailable', answer)


def sourcing(p):
    """Recommend suppliers for the current model; history suppliers rank first when they exist."""
    reg = p.load_registry()
    ctx = context(p, reg)
    if not reg:
        raise p.Stop('needs_clarification', '请先提供需要推荐供应商的完整规格型号。', True)
    target = ctx.get('selected_model')
    exact = reg['manifest'].get('query', {}).get('match_mode', 'exact') == 'exact'
    if not target and exact and len(reg['entries']) == 1:
        target = reg['entries'][0]['model']
    if target:
        return one(p, {'action': 'suppliers', 'target_model': target})
    model = ctx.get('original_target') or reg['manifest'].get('query', {}).get('model')
    head = '当前型号 **' + p.cell(model) + '** 没有可用的本型号历史采购记录，按物料信息推荐：' if not reg['entries'] else \
        '当前有多个相近型号候选、尚未选定，先按原始目标型号的物料信息推荐（选定相近型号后可查看其历史供应商）：'
    current = ctx['criteria']
    return p.final('ok', head + '\n\n' + p.recommend_for(model, current.get('purchaser'),
                                                        query_id=reg['query_id'], filters=current['set']))


def api_failure(p, req):
    allowed(p, req, {'model', 'error_kind'})
    if (not isinstance(req.get('model'), str) or not 1 <= len(req['model'].strip()) <= 256 or
            req.get('error_kind') not in {'api_error','invalid_api_response','file_error'}):
        raise p.Stop('invalid_request', '请使用本轮API错误回执的型号与错误类别，不构造有效原始页。')
    names = {'api_error':'接口调用失败', 'invalid_api_response':'接口返回结构无法核验', 'file_error':'原始JSON未成功保存'}
    return p.final('source_unavailable', '**'+p.cell(req['model'])+'**：'+names[req['error_kind']]+'；未获得可分析的完整数据，不等于没有历史。本轮不自动重试或补造结果；其他已获准输入项可继续处理。')


def help_input(p, req):
    allowed(p, req, set())
    return p.final('needs_input', '请直接输入完整规格型号。我可以查历史采购价格、比较记录，并分开展示本型号历史供应商与QPL/QSL名录候选（不混合排名，无历史型号也可按物料寻找候选）；空客只推荐QPL名录内、商飞只推荐QSL名录内供应商。多个型号请逐项列出；确认/撤销询价对象也可直接在对话中提出。')


def dispatch_local(p, req):
    action = req.get('action', 'history')
    if action in LEGACY:
        return one(p, req)
    return {'resolve': resolve, 'choose': choose, 'confirm': confirm,
            'confirmations': confirmations, 'unconfirm': unconfirm, 'explain_limits': limits, 'api_failure': api_failure, 'help': help_input}[action](p, req)


def dispatch(api, request):
    p = SimpleNamespace(**api)
    if not isinstance(request, dict) or request.get('action', 'history') not in LEGACY | EXTRA:
        raise p.Stop('invalid_request', '采购动作无效；未改动现有状态。')
    req = deepcopy(request)
    action = req.get('action', 'history')
    if action == 'batch':
        return batch(p, req)
    if action in {'confirmations', 'unconfirm', 'explain_limits', 'help'} or (action == 'api_failure' and 'item_index' not in req):
        return dispatch_local(p, req)
    state = batch_state(p)
    if action == 'batch_summary':
        allowed(p, req, set())
        return summary(p, state) if state else p.final('ok', '当前没有多型号处理批次。')
    index = req.pop('item_index', None)
    if index is not None and (type(index) is not int or not state or not 1 <= index <= len(state['items'])):
        raise p.Stop('invalid_selection', '输入项序号不属于当前手动批次。', True)
    if state and state.get('active') and ('page_files' not in req or index is not None or action == 'resolve'):
        if index is None:
            index = state.get('active_index')
        if index is None and action in {'resolve', 'choose', 'confirm', 'compare'}:
            phases = {'awaiting_model_check'} if action == 'resolve' else {'candidates'} if action == 'choose' else PHASES
            candidates = [i['index'] for i in state['items'] if i['status'] in phases]
            if len(candidates) == 1:
                index = candidates[0]
            else:
                raise p.Stop('needs_clarification', '请明确处理第几项输入；输入项序号与历史价格序号分别使用，不跨项合并。', True)
        selected = [state['items'][index - 1]] if index else state['items']
        results = [(item, item_result(p, item, req)) for item in selected]
        if index is not None:
            state['active_index'] = index
        save(p, BASE / 'manual-batch.json', state)
        if len(results) == 1:
            result = results[0][1]
            result['answer'] = '第' + str(results[0][0]['index']) + '项 · ' + p.cell(results[0][0]['model']) + '\n\n' + result['answer']
            return result
        return summary(p, state, results)
    if index is not None:
        raise p.Stop('invalid_selection', '当前批次没有可处理的该项输入。', True)
    result = dispatch_local(p, req)
    if state and 'page_files' in req and result['outcome'] in {'ok', 'no_records'}:
        state['active'] = False
        save(p, BASE / 'manual-batch.json', state)
    return result
