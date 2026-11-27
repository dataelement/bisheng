#!/usr/bin/env python3
"""One workspace-local entry for procurement evidence and final chat answers."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP, localcontext
import hashlib
import html
import json
from pathlib import Path
import re
import sys
import uuid

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import batch_session
import import_api_response
import qualification_lookup
import query_orders as engine
import recommendation

INDEX = HERE.parent / 'assets/qualification-index.json'
ROOT = Path('uploads/procurement-runtime')
_SCOPE = ContextVar('procurement_scope', default=None)

def runtime_root():
    return _SCOPE.get() or ROOT

@contextmanager
def scope(root):
    token = _SCOPE.set(root)
    try:
        yield
    finally:
        _SCOPE.reset(token)

REGISTRY = 'session-registry.json'
RECOMMENDATIONS = 'recommendations.json'
ACTIONS = {'history', 'show', 'filter', 'compare', 'suppliers', 'reset'}
BOOT = {'model', 'match_mode', 'reference_model', 'page_files'}
FIELDS = {'action', 'target_model', 'set', 'unset', 'sort', 'page', 'page_size',
          'positions', 'line_ids', 'purchaser'} | BOOT
FILTER_LABELS = {'supplier': '供应商', 'customer': '历史客户', 'date_from': '确认时间起',
                 'date_to': '确认时间止', 'currency': '币种', 'unit': '单位',
                 'incoterms': '贸易条款', 'incoterms_place': '贸易地点'}
WARNINGS = {
    'CODE_MAPPING_NOT_VERIFIED': '物料编码映射尚未业务核验。',
    'HISTORICAL_OBSERVATIONS_NOT_CURRENT_QUOTES': '历史采购单价不是本次报价。',
    'MULTIPLE_CONDITION_GROUPS_NO_GLOBAL_PRICE_RANK': '条件组不同，价格分别展示，不作跨组排名。',
    'INCOMPLETE_PRICE_COMPARISON_BASIS': '部分价格依据不完整，不能参与有效价格比较。',
    'DATE_FILTER_EXCLUDES_UNKNOWN_DATES': '确认时间不明的记录未参与日期筛选。',
    'LINE_AMOUNT_MISMATCH': '存在数量乘单价与行金额不一致的记录。',
    'ORDER_TOTAL_NOT_RECONCILED_FOR_MODEL_SUBSET': '本次按型号查询，未执行整单金额核对；金额是否存在差异及其原因均未确认。',
    'HEADER_TOTAL_NOT_RECONCILED_IN_SAMPLE': '当前样例尚未完成整单金额核对，现有资料不能用于解释金额差异。',
    'INVALID_QUANTITY': '部分记录数量缺失或数值无效，不能作为完整价格依据。',
    'INVALID_UNIT_PRICE': '部分历史采购单价缺失或数值无效，不参与有效价格比较。',
    'INVALID_LINE_AMOUNT': '部分行金额缺失或数值无效，不能作为完整价格依据。',
    'INVALID_HEADER_TOTAL': '部分订单总额缺失或数值无效，未以其核对本型号金额。',
    'CONFIRMATION_DATE_MISSING_OR_INVALID': '部分确认时间缺失或无效，不能据此确定时间先后。',
}


class Stop(Exception):
    def __init__(self, outcome, message, clarify=False):
        self.outcome, self.message, self.clarify = outcome, message, clarify


def cell(value):
    if value is None or value == '':
        return '未提供'
    if isinstance(value, (list, tuple)):
        return '；'.join(cell(v) for v in value) if value else '无'
    return html.escape(str(value), quote=False).replace('|', '\\|').replace('\r', '').replace('\n', '<br>')


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |',
                      '| ' + ' | '.join(['---'] * len(headers)) + ' |'] +
                     ['| ' + ' | '.join(cell(v) for v in row) + ' |' for row in rows])


def final(outcome, answer, models=None, clarify=False):
    return {'protocol': 'procurement-fixed-entry-v1',
            'status': 'user_clarification' if clarify else 'final', 'outcome': outcome,
            'terminal': True, 'next_action': 'none', 'answer': answer, 'models': models or []}


def read_json(path, maximum=65536):
    with Path(path).open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('File exceeds budget')
    return json.loads(raw, object_pairs_hook=import_api_response.unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def inside(relative):
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('Invalid internal path')
    base = Path.cwd().resolve()
    candidate = base / path
    if not candidate.resolve().is_relative_to(base):
        raise ValueError('Workspace escape')
    for parent in [candidate, *candidate.parents]:
        if parent == base:
            break
        if parent.is_symlink():
            raise ValueError('Symlink not allowed')
    return candidate


@contextmanager
def locked():
    import fcntl
    root = inside(runtime_root())
    root.mkdir(parents=True, exist_ok=True)
    lock = inside(runtime_root() / '.entry.lock')
    with lock.open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def load_registry():
    path = inside(runtime_root() / REGISTRY)
    if not path.exists():
        return None
    registry = read_json(path)
    if (not isinstance(registry, dict) or registry.get('version') != 1 or
            not re.fullmatch(r'[a-f0-9]{32}', str(registry.get('query_id', ''))) or
            not isinstance(registry.get('entries'), list) or len(registry['entries']) > 3):
        raise ValueError('Invalid registry')
    manifest = registry.get('manifest')
    if (not isinstance(manifest, dict) or manifest.get('complete') is not True or
            not isinstance(manifest.get('models'), list) or
            type(manifest.get('total_records')) is not int or manifest['total_records'] < 0 or
            type(manifest.get('matched_models')) is not int or manifest['matched_models'] < 0 or
            type(manifest.get('displayed_models')) is not int or
            type(manifest.get('omitted_models')) is not int or
            manifest.get('displayed_models') != len(registry['entries']) or
            len(manifest['models']) != len(registry['entries']) or
            manifest.get('omitted_models') != manifest['matched_models'] - len(registry['entries']) or
            len(registry['entries']) != min(3, manifest['matched_models']) or
            (not registry['entries'] and manifest['total_records'] != 0) or
            (registry['entries'] and manifest['total_records'] < manifest['matched_models'])):
        raise Stop('state_integrity_error', '采购会话状态与原始批次不一致；请新建对话重新查询，不能据此判断无历史记录。')
    for i, entry in enumerate(registry['entries'], 1):
        prefix = runtime_root() / 'queries' / registry['query_id']
        if (not isinstance(entry, dict) or not isinstance(entry.get('model'), str) or
                entry.get('batch') != str(prefix / 'batches' / ('model-' + str(i) + '.json')) or
                entry.get('session') != str(prefix / ('session-model-' + str(i) + '.json'))):
            raise ValueError('Invalid registry entry')
        inside(entry['batch'])
        inside(entry['session'])
        declared = manifest['models'][i - 1]
        if (not isinstance(declared, dict) or entry['model'] != declared.get('model') or
                entry.get('batch_sha256') != declared.get('sha256') or
                type(declared.get('records')) is not int or declared['records'] <= 0):
            raise Stop('state_integrity_error', '型号与采购批次的绑定不一致；请新建对话重新查询，本轮未展示旧数据。')
        batch, _ = batch_session.json_read(inside(entry['batch']))
        session = read_json(inside(entry['session']))
        if (not isinstance(batch, dict) or not isinstance(session, dict) or
                engine.norm(batch.get('model', '')) != engine.norm(entry['model']) or
                engine.norm(session.get('model', '')) != engine.norm(entry['model']) or
                session.get('batch_sha256') != entry['batch_sha256'] or
                batch.get('total_records') != declared.get('records')):
            raise Stop('state_integrity_error', '采购型号、会话与批次记录不一致；本轮未返回部分结果，请新建对话重新查询。')
    if len({engine.norm(e['model']) for e in registry['entries']}) != len(registry['entries']):
        raise ValueError('Duplicate registry models')
    if sum(item['records'] for item in manifest['models']) > manifest['total_records']:
        raise Stop('state_integrity_error', '采购批次记录数与会话声明不一致；本轮停止，不能解释为无历史记录。')
    return registry


def validate_request(request):
    if not isinstance(request, dict) or set(request) - FIELDS:
        raise Stop('invalid_request', '请求结构不受支持；本轮未继续执行。')
    action = request.get('action', 'history')
    if not isinstance(action, str) or action not in ACTIONS:
        raise Stop('invalid_request', '仅支持历史查询、筛选、展示、比较、供应商及重置。')
    if 'purchaser' in request and (not isinstance(request['purchaser'], str) or not 0 < len(request['purchaser'].strip()) <= 100):
        raise Stop('invalid_request', '本次甲方须为1—100字的明确名称。')
    if 'purchaser' in request and action not in {'history', 'show', 'filter', 'suppliers'}:
        raise Stop('invalid_request', '此动作不接受甲方修改。')
    if 'set' in request and action not in {'filter', 'history', 'suppliers'}:
        raise Stop('invalid_request', '此动作不接受筛选设置。')
    if 'unset' in request and action not in {'filter', 'history', 'suppliers'}:
        raise Stop('invalid_request', '取消筛选须使用filter。')
    if any(k in request for k in ('positions', 'line_ids')) and action != 'compare':
        raise Stop('invalid_request', '记录选择仅用于比较。')
    if action in {'compare', 'reset'} and any(k in request for k in ('sort', 'page', 'page_size', 'set', 'unset')):
        raise Stop('invalid_request', '比较或重置不能同时改排序、分页或筛选。')
    if any(k in request for k in ('match_mode', 'reference_model')) and 'page_files' not in request:
        raise Stop('invalid_request', '匹配控制仅用于首次导入原始API文件。')
    if 'page_files' in request and action not in {'history', 'suppliers'}:
        raise Stop('invalid_request', '新API结果须通过history或suppliers导入。')
    if 'target_model' in request and (not isinstance(request['target_model'], str) or not request['target_model'].strip()):
        raise Stop('invalid_request', '目标型号须为已返回的完整型号。')
    if 'set' in request and action not in {'filter', 'history', 'suppliers'} and 'page_files' not in request:
        raise Stop('invalid_request', '续问设置条件须使用filter。')
    values, removed = request.get('set', {}), request.get('unset', [])
    if (not isinstance(values, dict) or set(values) - batch_session.FILTERS or
            not isinstance(removed, list) or any(not isinstance(k, str) or k not in batch_session.FILTERS for k in removed) or
            set(values) & set(removed)):
        raise Stop('invalid_request', '筛选字段、撤销条件或请求结构无效。')
    try:
        engine.request({'model': 'validation-only', **values,
                        **{k: request[k] for k in ('sort', 'page', 'page_size') if k in request}})
    except engine.Stop:
        raise Stop('invalid_request', '筛选日期、排序或分页参数无效；未改动有效会话。') from None
    return action


def raw_paths(files):
    if not isinstance(files, list) or not 1 <= len(files) <= 100:
        raise Stop('source_unavailable', '未取得本次完整API原始JSON文件，无法形成采购结果。')
    result = []
    for name in files:
        if not isinstance(name, str):
            raise Stop('source_unavailable', 'API结果文件句柄无效。')
        relative = name[1:] if name.startswith('/') else name
        path = Path(relative)
        allowed = ((len(path.parts) == 2 and path.parts[0] == 'large_tool_results') or
                   (len(path.parts) == 3 and path.parts[:2] == ('uploads', 'procurement-api')))
        if not allowed or path.suffix != '.json' or any(v in ('', '.', '..') for v in path.parts):
            raise Stop('source_unavailable', '只能读取本任务API工具返回的原始JSON文件句柄。')
        result.append(str(inside(path)))
    return result


def initialize(request, previous):
    model = request.get('model')
    if not isinstance(model, str) or not model.strip():
        raise Stop('needs_clarification', '请提供需要查询的完整规格型号。', True)
    paths = raw_paths(request['page_files'])
    try:
        payload = import_api_response.read_response_files(page_files=paths)
        mode, reference = request.get('match_mode', 'exact'), request.get('reference_model')
        signature = hashlib.sha256(json.dumps([model, mode, reference, payload], ensure_ascii=False,
                                               allow_nan=False, sort_keys=True).encode()).hexdigest()
        if previous and previous.get('input_signature') == signature:
            return previous, False, {}
        batches, manifest = import_api_response.import_pages(payload, model, mode, reference)
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        raise Stop('import_error', 'API原始文件或完整性校验失败；未形成可分析的完整批次。') from None
    query_id = uuid.uuid4().hex
    prefix = runtime_root() / 'queries' / query_id
    import_api_response.fetch_history.write_batches(inside(prefix / 'batches'), batches, manifest)
    entries, initial_views = [], {}
    for i, item in enumerate(manifest['models'], 1):
        entry = {'model': item['model'], 'batch': str(prefix / 'batches' / item['batch']),
                 'session': str(prefix / ('session-model-' + str(i) + '.json')),
                 'batch_sha256': item['sha256'], 'last_action': 'load', 'view': 'history'}
        loaded = batch_session.run(inside(entry['batch']), inside(entry['session']),
                                   {'action': 'load', 'model': entry['model'],
                                    **{k: request[k] for k in ('sort', 'page', 'page_size') if k in request}}, INDEX)
        if loaded.get('status') not in {'ok', 'no_records'}:
            raise Stop('initialization_error', '批次校验或会话初始化失败，本轮未返回部分结果。')
        entries.append(entry)
        initial_views[entry['model']] = loaded
    registry = {'version': 1, 'query_id': query_id, 'input_signature': signature,
            'source_version': manifest.get('snapshot_id'), 'manifest': manifest,
            'source': payload['pages'][0]['data']['data']['source'],
            'entries': entries}
    if len((json.dumps(registry, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode()) > batch_session.STATE_JSON_MAX:
        raise Stop('state_budget_exceeded', '采购来源或会话元数据超过容量限制；本轮未更新有效会话，请缩减异常元数据后重新查询。')
    return registry, True, initial_views


def select_entries(registry, request, action):
    entries = registry['entries']
    if 'target_model' in request:
        entries = [entry for entry in entries if engine.norm(entry['model']) == engine.norm(request['target_model'])]
        if not entries:
            raise Stop('needs_clarification', '该型号不在当前返回结果中，请从已显示型号中选择。', True)
    if action == 'compare' and len(entries) != 1:
        raise Stop('needs_clarification', '当前有多个型号，请明确比较哪个型号的已展示记录。', True)
    return entries


def failure(result):
    outcome = result.get('status', 'execution_error')
    clarify = outcome in {'needs_clarification', 'invalid_selection', 'page_out_of_range'}
    messages = {
        'invalid_selection': '所选记录不属于上一有效价格展示。请明确当前展示的序号；未改动有效会话。',
        'page_out_of_range': '指定页码没有结果。请确认页码；未改动有效会话。',
        'stale_source': '历史批次已变化，旧展示序号已失效。需要重新取得并校验API原始文件。',
        'invalid_request': '筛选、排序或请求参数无效；未改动有效会话。',
        'needs_clarification': '请明确需要比较的2—10条当前展示记录。',
    }
    raise Stop(outcome, messages.get(outcome, '批次、会话或执行资源不可用；不能将此错误解释为无历史记录。'), clarify)


def compact(result, entry, snapshot):
    return {'model': entry['model'], 'outcome': result['status'],
            'action': 'history' if result.get('action') == 'load' else result.get('action'),
            'active_filters': result.get('active_filters', {}),
            'counts': {k: result.get(k, 0) for k in ('original_batch_records', 'total_matches', 'shown')},
            'page': result.get('query', {}).get('page'), 'has_more': result.get('has_more', False),
            'source': {'file': result.get('source', {}).get('origin_file'),
                       'sheet': result.get('source', {}).get('sheet'),
                       'snapshot_id': snapshot, 'batch_sha256': entry['batch_sha256']},
            'purchaser': result.get('purchaser'),
            'view': result.get('view', 'history'),
            'supplier_counts': {k: result.get(k, 0) for k in ('historical_supplier_groups', 'excluded_supplier_groups', 'total_items')},
            'qualification': [{'supplier_id': item.get('supplier_id'),
                               'status': item.get('qualification', {}).get('status'),
                               'information_status': item.get('qualification', {}).get('information_status'),
                               'evidence_count': item.get('qualification', {}).get('evidence_count', 0),
                               'whitelist_status': item.get('qualification', {}).get('whitelist_status'),
                               'approval_verdict': None}
                              for item in result.get('suppliers', []) if isinstance(item.get('qualification'), dict)]}


def qualification_text(value):
    if not isinstance(value, dict):
        return '名录信息不足；不能自动判断合格。'
    membership = value.get('whitelist_status')
    name = {'qpl': '空客QPL', 'qsl': '商飞QSL'}.get(value.get('list'), '本次指定名录')
    if membership == 'listed':
        return '已列入所提供的' + name + '，满足本次甲方名录条件；产品适用范围仍须复核'
    if membership == 'not_listed':
        return '未列入所提供的' + name + '，不符合本次甲方名录要求，已排除本次推荐'
    if membership in {'unresolved', 'unavailable'}:
        return '本次名录核验未能确定，暂不推荐；不能据此判为不在名单'
    status = value.get('status')
    if value.get('information_status') == 'insufficient_information' or value.get('missing'):
        return '信息不足，不能自动判断合格'
    title = {'not_requested': '未提供本次甲方，未触发名录核验',
             'not_required': '按本次甲方无需核验；不表示合格',
             'evidence_found_scope_review': '有名录证据，主体及适用范围待复核',
             'insufficient_information': '信息不足，不能自动判断合格',
             'no_evidence_found': '所给版本未找到证据，不表示不合格',
             'index_unavailable': '名录资源不可用，不能判断资质'}.get(status, '核验信息待人工确认')
    return title


def render_qualification(supplier):
    value = supplier.get('qualification', {})
    if not isinstance(value, dict):
        return []
    parts = []
    missing = value.get('missing', [])
    if missing:
        parts.append('缺口：' + cell(missing))
    source = value.get('source', {})
    if source:
        parts.append('名录来源：' + cell(source.get('file')) + '；资料日期：' + cell(source.get('document_date')) + '。')
        parts.append('所给版本证据不代表现行有效；主体、场所与产品适用范围仍须复核。')
    labels = [('supplier_name', '主体'), ('company_name', '主体'), ('supplier_code', '主体编码'),
              ('company_code', '主体编码'), ('standard_code', '规范'), ('standard_name', '规范名称'),
              ('category', '类别'), ('material_category', '材料类别'), ('standard', '标准'),
              ('standard_version', '标准版本'), ('technical_standard', '技术标准'),
              ('technical_standard_version', '技术标准版本'), ('grade', '牌号'), ('type', '类型'),
              ('class', '分类'), ('level', '等级'), ('specification', '规格'),
              ('material_designation', '材料标识'), ('status', '状态'), ('form', '形态'),
              ('product_form', '产品形态'), ('part_number', '件号'),
              ('supplier_part_number', '供应商件号'), ('aircraft', '适用机型'), ('registered_at', '登记时间'),
              ('product_range', '产品范围'), ('product_scope', '产品范围'), ('applicable_models', '适用型号'),
              ('applicability', '适用范围'), ('restrictions', '限制'), ('product_group', '产品组'),
              ('product_group_code', '产品组编码'), ('address', '场所'), ('city', '城市'), ('country', '国家'),
              ('match_role', '命中角色'), ('parse_status', '解析状态'), ('review_notes', '待复核说明')]
    for evidence in value.get('evidence', []):
        if not isinstance(evidence, dict):
            continue
        fields = [label + '：' + cell(evidence[key]) for key, label in labels if evidence.get(key)]
        where = []
        for key, label in [('source_row', '原行'), ('source_page', '原页'), ('pages', '原页'),
                           ('product_group_source_page', '产品组来源页'), ('product_group_source_row', '产品组来源行')]:
            if evidence.get(key):
                where.append(label + cell(evidence[key]))
        # Raw text is shown only when no structured evidence is available.
        if not fields:
            for key in ('excerpt', 'raw_text'):
                if evidence.get(key):
                    fields.append('原文：' + cell(evidence[key]))
                    break
        parts.append('证据：' + '；'.join(fields + where))
    if value.get('truncated'):
        parts.append('名录共命中' + cell(value.get('evidence_count')) + '项，本次返回前' +
                     str(len(value.get('evidence', []))) + '项证据；不能据此自动认定合格。')
    return parts


def comparison_text(result):
    info = result.get('comparison', {})
    records = result.get('records', [])
    if not info.get('basis_complete'):
        return ['所选记录的币种、单位、贸易条件或有效价格不完整一致，不计算价差和比值。']
    base = records[0]
    pairs = []
    with localcontext() as context:
        context.prec = 200
        p0 = Decimal(base['unit_price'])
        for row in records[1:]:
            p1 = Decimal(row['unit_price'])
            ratio = (p1 / p0).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP) if p0 else None
            pairs.append([row['line_id'], base['line_id'], str(p1 - p0), str(ratio) if ratio is not None else '基准为0，无法计算'])
    return ['差额固定为“比较明细单价－基准明细单价”；比值固定为“比较明细单价÷基准明细单价”（四位小数）。',
            table(['比较明细', '基准明细（所选第1条）', '历史单价差额', '历史单价比值'], pairs),
            '上述可计算仅限已知价格条件，不证明原厂、税费或技术等完全可比，也不解释价差原因。']


def record_context(records):
    """Keep long related fields outside the price table; source rows stay internal."""
    fields = [('customer_name', '历史客户'), ('incoterms', '贸易条款'),
              ('incoterms_place', '贸易地点'), ('order_no', '订单号'),
              ('confirmed_at', '完整确认时间'), ('line_id', '明细ID')]
    shared, separate = [], []
    for key, label in fields:
        values = [cell(row.get(key)) for row in records]
        if values and len(set(values)) == 1:
            shared.append(label + '：' + values[0])
        else:
            separate.append((key, label))
    parts = ['关联条件：' + '；'.join(shared) + '。'] if shared else []
    if separate:
        parts.append('关联明细：\n' + '\n'.join(
            '- 第' + str(i) + '条：' + '；'.join(label + '：' + cell(row.get(key))
                                                 for key, label in separate)
            for i, row in enumerate(records, 1)))
    return parts


def confirmed_date(value):
    text = str(value) if value is not None else ''
    # The full original value remains in related information and stored data.
    return text[:10] if len(text) >= 10 and text[4:5] == '-' and text[7:8] == '-' else value


def recommendation_cache():
    path = inside(runtime_root() / RECOMMENDATIONS)
    saved = read_json(path, batch_session.STATE_JSON_MAX) if path.exists() else {}
    if not isinstance(saved, dict) or ('' in saved and (type(saved['']) is not int or saved[''] < 1)):
        raise Stop('state_integrity_error', '名录候选记录无法核验，请重新查看当前候选。')
    return path, saved


def invalidate_recommendation(model):
    path, saved = recommendation_cache()
    if saved.pop(engine.norm(model), None) is not None:
        saved.setdefault('', 11)
        batch_session.save_state(path, saved)


def expire_recommendation(model, query_id, filters, purchaser):
    """Expire shown candidates after scope changes without generating new ones."""
    if not inside(runtime_root() / RECOMMENDATIONS).exists():
        return
    _, saved = recommendation_cache()
    previous = saved.get(engine.norm(model))
    if previous and (previous.get('selection') != {'query_id': query_id, 'filters': filters}
                     or previous.get('purchaser') != purchaser):
        invalidate_recommendation(model)


def recommend_for(model, purchaser, materials=(), history_suppliers=(), *,
                  query_id, filters, publish=True):
    """Keep history and catalog leads separate, persist only displayed items for confirmation."""
    try:
        index = qualification_lookup.load(INDEX)
    except (OSError, ValueError, KeyError):
        index = None
    rec = recommendation.recommend(model, purchaser, materials, history_suppliers, index)
    if not publish:
        return recommendation.render(rec, cell, table)

    path, saved = recommendation_cache()
    key = engine.norm(model)
    previous = saved.get(key, {})
    # Empty model names are invalid. This key keeps the next number across models
    # and empty views. Legacy sessions reserve the original C01–C10 range.
    next_ref = saved.get('', 11 if saved else 1)
    selection = {'query_id': query_id, 'filters': filters}
    item_fields = ('rank', 'tier', 'name', 'supplier_id', 'list', 'code', 'country', 'reason',
                   'evidence_rows', 'group', 'match_kind', 'match_label')
    items = [{field: item.get(field) for field in item_fields} for item in rec['items']]
    catalog = [item for item in items if item['group'] == 'catalog']
    old_catalog = [item for item in previous.get('items', []) if item.get('group') == 'catalog']
    if (previous.get('selection') == selection and previous.get('purchaser') == purchaser
            and previous.get('source') == rec['source']
            and [{k: v for k, v in item.items() if k != 'candidate_ref'} for item in old_catalog] == catalog):
        refs = [item['candidate_ref'] for item in old_catalog]
    else:
        refs = [f'C{number:02d}' for number in range(next_ref, next_ref + len(catalog))]
        next_ref += len(catalog)
    for item, visible, ref in zip(catalog, rec['catalog_items'], refs):
        item['candidate_ref'] = visible['candidate_ref'] = ref
    saved = {model_key: value for model_key, value in saved.items()
             if model_key and value.get('selection', {}).get('query_id') == query_id}
    saved[''] = next_ref
    saved[key] = {'model': model, 'purchaser': purchaser, 'selection': selection, 'items': items,
                  'source': rec['source'], 'profile': rec['profile']}
    answer = recommendation.render(rec, cell, table)
    batch_session.save_state(path, saved)
    return answer


def render(result, entry, query_id, *, publish_catalog):
    parts = ['### ' + cell(entry['model'])]
    filters = result.get('active_filters', {})
    if publish_catalog and result.get('view') != 'suppliers':
        expire_recommendation(entry['model'], query_id, filters, result.get('purchaser'))
    parts.append('生效条件：' + ('；'.join(FILTER_LABELS[k] + '=' + cell(v) for k, v in filters.items()) if filters else '无额外筛选') + '。')
    if result['status'] == 'no_records':
        if publish_catalog:
            invalidate_recommendation(entry['model'])
        parts.append('当前型号在本批和这些条件下没有记录；不表示全部历史无记录。')
    else:
        summary = result.get('summary', {})
        parts.append('命中' + str(result.get('total_matches', 0)) + '条历史明细，' +
                     str(summary.get('order_count', 0)) + '张订单、' + str(summary.get('supplier_count', 0)) +
                     '家供应商；本页展示' + str(result.get('shown', 0)) + '项。')
        if result.get('view') == 'suppliers' or result.get('action') == 'suppliers':
            parts.append(recommend_for(entry['model'], result.get('purchaser'), result.get('materials', []),
                                       result.get('suppliers', []), query_id=query_id, filters=filters,
                                       publish=publish_catalog))
            parts.append('**历史供应商明细**')
            rows = []
            for i, supplier in enumerate(result.get('suppliers', []), 1):
                rows.append([i, supplier.get('supplier_names'), supplier.get('record_count'),
                             str(supplier.get('historical_min_unit_price') if supplier.get('historical_min_unit_price') is not None else '未提供') + ' — ' +
                             str(supplier.get('historical_max_unit_price') if supplier.get('historical_max_unit_price') is not None else '未提供'),
                             supplier.get('latest_confirmed_date')])
            parts.append('本次甲方：' + cell(result.get('purchaser') or '未指定') + '。')
            sort = result.get('query', {}).get('sort')
            if sort in {'price_asc', 'price_desc'}:
                parts.append('排序依据：各供应商在相同币种、单位、贸易条款及地点组内的历史最低单价' + ('升序' if sort == 'price_asc' else '降序') + '；历史单价范围用于参考，不代表本次报价或综合最优。')
            if len({item.get('supplier_id') for item in result.get('suppliers', [])}) == 1:
                parts.append('本页只有1家供应商，不能据此证明多家优选结果。')
            if rows:
                parts.append(table(['序号', '供应商', '历史明细数', '历史单价范围', '最近确认日期'], rows))
            else:
                parts.append('当前没有满足本次名录条件的本型号历史供应商；名录候选单独列在上方。')
            parts.append('名录筛选前' + str(result.get('historical_supplier_groups', len(rows))) + '项供应商条件组；排除/暂不推荐' + str(result.get('excluded_supplier_groups', 0)) + '项，保留' + str(result.get('total_items', len(rows))) + '项。历史采购记录保留，可通过历史查询查看。')
            for i, supplier in enumerate(result.get('suppliers', []), 1):
                c = supplier.get('conditions', {})
                parts.append('**候选' + str(i) + ' · ' + cell(supplier.get('supplier_names')) + '**\n\n' +
                             '价格条件：币种' + cell(c.get('currency')) + '；单位' + cell(c.get('unit')) +
                             '；贸易条款' + cell(c.get('incoterms')) + '；地点' + cell(c.get('incoterms_place')) + '。\n\n' +
                             '名录核验：' + qualification_text(supplier.get('qualification')) + '。')
                evidence = render_qualification(supplier)
                if evidence:
                    parts.append('\n\n'.join(evidence))
            excluded = result.get('excluded_suppliers', [])
            if excluded:
                parts.append('**排除及待核验记录（不属于推荐候选）**')
                parts.append(table(['历史供应商', '名录结论'],
                                   [[cell(item.get('supplier_names')), qualification_text(item.get('qualification'))]
                                    for item in excluded]))
                seen_sources = set()
                for item in excluded:
                    value = item.get('qualification', {})
                    src = value.get('source', {})
                    key = (src.get('file'), src.get('document_date'))
                    if src and key not in seen_sources:
                        parts.append('名录来源：' + cell(src.get('file')) + '；资料日期：' + cell(src.get('document_date')) + '。结论仅针对所给版本的本次名录条件。')
                        seen_sources.add(key)
                if result.get('excluded_suppliers_truncated'):
                    parts.append('排除/待核验明细仅列前20项，完整数量以上方统计为准。')
        else:
            parts.append(table(['序号', '确认日期', '供应商', '采购数量', '历史采购单价', '币种'],
                               [[i, confirmed_date(r.get('confirmed_at')), r.get('supplier_name'),
                                 str(r.get('quantity') if r.get('quantity') is not None else '未提供') + ' ' + str(r.get('unit') or '未提供'),
                                 r.get('unit_price'), r.get('currency')]
                                for i, r in enumerate(result.get('records', []), 1)]))
            parts.extend(record_context(result.get('records', [])))
            if result.get('action') == 'compare':
                parts.extend(comparison_text(result))
        if result.get('has_more'):
            parts.append('当前第' + str(result.get('query', {}).get('page', 1)) + '页，仍有后续结果；本页未作全量展示。')
        warnings = [WARNINGS.get(w, '数据提示：' + w) for w in result.get('warnings', [])
                    if w != 'HISTORICAL_OBSERVATIONS_NOT_CURRENT_QUOTES']
        if warnings:
            parts.append('限制：' + ' '.join(cell(w) for w in warnings))
    source = result.get('source', {})
    parts.append('来源：' + cell(source.get('origin_file')) + ' / ' + cell(source.get('sheet')) +
                 '。样例覆盖' + str(result.get('original_batch_records', source.get('data_rows', 0))) + '条本型号明细。')
    return '\n\n'.join(parts)


def execute(request, *, publish_catalog=True):
    action = validate_request(request)
    registry = load_registry()
    new, initial_views = False, {}
    if 'page_files' in request:
        registry, new, initial_views = initialize(request, registry)
    elif registry is None:
        if not request.get('model'):
            raise Stop('needs_clarification', '请提供需要查询的完整规格型号。', True)
        raise Stop('source_unavailable', '需要本次API工具返回的原始JSON文件；尚未形成可分析的历史结果。')
    elif 'model' in request and engine.norm(request['model']) != engine.norm(registry['manifest'].get('query', {}).get('model', '')):
        raise Stop('needs_new_api_files', '型号已变化，需要该型号本次API返回的原始文件，不能复用旧数据。')
    if not registry['entries']:
        registry.update(last_action=action, last_view='history')
        batch_session.save_state(inside(runtime_root() / REGISTRY), registry)
        return final('no_records', '本次API完整返回0条记录；仅代表所查样例范围没有该型号历史，不重复查询或补造候选。\n\n来源：' +
                     cell(registry.get('source', {}).get('file')) + ' / ' + cell(registry.get('source', {}).get('sheet')) + '。')
    entries = select_entries(registry, request, action)
    before = {entry['session']: inside(entry['session']).read_bytes() for entry in entries}
    updated = deepcopy(registry)
    outputs = []
    try:
        for entry in entries:
            args = {key: request[key] for key in ('sort', 'page', 'page_size', 'positions', 'line_ids', 'purchaser', 'set', 'unset') if key in request}
            if new and action == 'history' and 'set' not in args and 'unset' not in args and 'purchaser' not in args:
                result = initial_views[entry['model']]
            elif ('set' in args or 'unset' in args) and action not in {'filter', 'history'}:
                changes = {key: args.pop(key) for key in ('set', 'unset') if key in args}
                filtered = batch_session.run(inside(entry['batch']), inside(entry['session']),
                                             {'action': 'filter', **changes}, INDEX)
                if filtered.get('status') not in {'ok', 'no_records'}:
                    failure(filtered)
                result = batch_session.run(inside(entry['batch']), inside(entry['session']),
                                           {'action': 'history' if action == 'history' else action, **args}, INDEX)
            else:
                result = batch_session.run(inside(entry['batch']), inside(entry['session']),
                                           {'action': 'history' if action == 'history' else action, **args}, INDEX)
            if result.get('status') not in {'ok', 'no_records'}:
                failure(result)
            outputs.append((entry, result))
        manifest = registry['manifest']
        answer = []
        if manifest.get('matched_models', 0) > 1:
            answer.append('共匹配' + str(manifest['matched_models']) + '个型号，当前展示最多3个，省略' +
                          str(manifest.get('omitted_models', 0)) + '个；各型号价格独立，字符串相近不代表可替代。')
        for entry, result in outputs:
            reference = manifest.get('reference_model')
            if (manifest.get('query', {}).get('match_mode') == 'regex' and reference and
                    engine.norm(reference) != engine.norm(entry['model'])):
                answer.append('型号差异：原始目标为' + cell(reference) + '，本节返回型号为' +
                              cell(entry['model']) + '；规格差异与可替代性尚未核验。')
            answer.append(render(result, entry, registry['query_id'], publish_catalog=publish_catalog))
        answer.append('历史采购单价仅供本批历史参考，不构成本次报价；时间字段为确认时间。供应商及名录证据不自动等于准入合格。')
        response = final('no_records' if all(result['status'] == 'no_records' for _, result in outputs) else 'ok',
                         '\n\n'.join(answer), [compact(result, entry, registry.get('source_version')) for entry, result in outputs])
        for entry, result in outputs:
            target = next(e for e in updated['entries'] if e['model'] == entry['model'])
            target.update(last_action=action, view=result.get('view', 'history'))
            batch_session.save_state(inside(runtime_root() / 'queries' / updated['query_id'] /
                                           (Path(entry['session']).stem + '-result.json')), result)
        updated.update(last_action=action, last_view=result.get('view', 'history'))
        batch_session.save_state(inside(runtime_root() / REGISTRY), updated)
    except Exception:
        for name, raw in before.items():
            batch_session.save_state(inside(name), json.loads(raw))
        raise
    return response


def run(request):
    """Perform one bounded action and return a complete terminal chat response."""
    try:
        with locked():
            import procurement_workflow
            return procurement_workflow.dispatch(globals(), request)
    except Stop as error:
        return final(error.outcome, cell(error.message), clarify=error.clarify)
    except Exception:
        return final('execution_error', '本任务的文件、状态或执行资源不可用；未返回部分结果，也不能解释为无历史记录。')


if __name__ == '__main__':
    try:
        raw = sys.stdin.read(65537)
        result = run(json.loads(raw)) if len(raw) <= 65536 else final('invalid_request', '请求超过输入预算。')
    except (ValueError, TypeError):
        result = final('invalid_request', '请求JSON无法读取。')
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
