"""Read-only verification against BISHENG's authenticated native task records.

This does not submit tasks, execute models, or accept client-authored transcripts.
The caller supplies only a server-configured origin, an in-memory Cookie header,
native identifiers and the workflow's own expected action identities.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
import urllib.error
import urllib.parse
import urllib.request


SKILL = 'procurement-forecast-fast'
ACTIONS = ('forecast', 'history', 'finalize')
HASH = re.compile(r'^[a-f0-9]{64}$')
IDENTIFIER = re.compile(r'^[A-Za-z0-9_-]{1,128}$')
MAX_BYTES = 12 * 1024 * 1024


class NativeBridgeError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = self.status_code = status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Even same-origin redirects are unnecessary for these exact API routes.
        return None


def _json(raw):
    def reject_constant(_):
        raise ValueError('nonfinite')
    return json.loads(raw, parse_constant=reject_constant)


def _objects(value):
    """Decode JSON objects in tool output, including a JSON receipt in log text.

    This helper is called only on the output of the configured native API tool,
    never on task questions, inputs, model answers or unrelated history records.
    """
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from _objects(item)
    elif isinstance(value, str):
        try:
            parsed = _json(value)
        except (ValueError, RecursionError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            yield from _objects(parsed)
            return
        decoder = json.JSONDecoder()
        # The native framework may replace an oversized result with a numbered
        # preview. The service deliberately emits a complete receipt FIRST.
        # Decode only that root object's first value; never search for arbitrary
        # receipt text elsewhere in prose, inputs or an assistant answer.
        for match in re.finditer(r'(?m)^[ \t]*(?:\d+\t)?\{\s*"receipt"\s*:\s*', value):
            try:
                receipt, _end = decoder.raw_decode(value, match.end())
            except (ValueError, RecursionError):
                continue
            if isinstance(receipt, dict):
                yield from _objects(receipt)
        # The API may return a whole JSON line. raw_decode tolerates notices
        # before/after it without interpreting Python source as a receipt.
        for line in value.splitlines():
            line = line.strip()
            if not line.startswith(('{', '[')):
                continue
            try:
                item, end = decoder.raw_decode(line)
            except (ValueError, RecursionError):
                continue
            if line[end:].strip():
                continue
            yield from _objects(item)


def _history(nodes):
    if not isinstance(nodes, list):
        return
    for node in nodes:
        if not isinstance(node, dict):
            continue
        for record in node.get('history') or []:
            if isinstance(record, dict):
                yield record
        yield from _history(node.get('children') or [])


def _input(record):
    for key in ('input', 'tool_input', 'args', 'arguments', 'parameters', 'params'):
        value = record.get(key)
        if isinstance(value, (dict, list, str)):
            return value
    return None


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _skill_read(record, expected_hash=None):
    if record.get('name') != 'read_file':
        return False
    for value in _strings(_input(record)):
        try:
            parsed = _json(value)
        except (ValueError, RecursionError):
            parsed = None
        candidates = list(_strings(parsed)) if parsed is not None else [value]
        for path in candidates:
            if path.lstrip('/') == f'skills/{SKILL}/SKILL.md':
                return record.get('output') is not None and not record.get('error')
    # Current D persists read_file params={} but retains the actual numbered
    # file output. Verify its complete bytes rather than inventing a path input.
    output=record.get('output')
    if expected_hash and isinstance(output,str) and not record.get('error'):
        lines=output.splitlines()
        if lines and all(re.match(r'^\s*\d+\t',line) for line in lines):
            content='\n'.join(re.sub(r'^\s*\d+\t','',line) for line in lines)
            return any(hashlib.sha256(value.encode()).hexdigest()==expected_hash for value in (content,content+'\n'))
    return False


class NativeBridge:
    def __init__(self, base_url, tool_key=None, timeout=10):
        try:
            parsed = urllib.parse.urlsplit(base_url)
            valid = (parsed.scheme in ('http', 'https') and parsed.hostname
                     and parsed.username is None and parsed.password is None
                     and not parsed.query and not parsed.fragment
                     and parsed.path in ('', '/') and parsed.port != 0
                     and not any(c.isspace() or ord(c) < 32 for c in base_url)
                     and '\\' not in base_url)
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise NativeBridgeError('平台地址必须是服务端配置的无凭证HTTP(S)源地址', 500)
        self.timeout = timeout
        self.base_url = base_url.rstrip('/')
        if tool_key is not None and (not isinstance(tool_key, str) or not IDENTIFIER.fullmatch(tool_key)):
            raise NativeBridgeError('服务端原生API工具标识无效', 500)
        self.tool_key = tool_key
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def _get(self, path, cookie):
        request = urllib.request.Request(self.base_url + path,
                                         headers={'Cookie': cookie, 'Accept': 'application/json'}, method='GET')
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise NativeBridgeError('平台执行证据响应过大', 502)
            value = _json(raw)
            if not isinstance(value, dict) or value.get('status_code', 200) != 200 or 'data' not in value:
                raise NativeBridgeError('平台未返回有效执行证据', 502)
            return value['data'], raw
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            if status in (401, 403):
                raise NativeBridgeError('平台登录已失效或无权读取本次任务', status) from None
            raise NativeBridgeError('平台执行证据读取失败', 502) from None
        except (OSError, ValueError, RecursionError, urllib.error.URLError):
            raise NativeBridgeError('平台执行证据连接失败或响应无效', 502) from None

    def verify(self, cookie, chat_id, session_version_id, contract, *, business_checkpoint=False):
        if (not isinstance(cookie, str) or not cookie or len(cookie) > 16384
                or any(ord(c) < 32 or ord(c) == 127 for c in cookie)):
            raise NativeBridgeError('缺少有效的平台登录凭证', 401)
        if any(not isinstance(v, str) or not IDENTIFIER.fullmatch(v) for v in (chat_id, session_version_id)):
            raise NativeBridgeError('原生任务标识无效', 400)
        if (not isinstance(contract, dict) or not isinstance(contract.get('run_id'), str)
                or not IDENTIFIER.fullmatch(contract['run_id'])
                or any(not isinstance(contract.get(k), str) or not HASH.fullmatch(contract[k])
                       for k in ('skill_sha256', 'cli_sha256'))
                or not isinstance(contract.get('actions'), dict) or set(contract['actions']) != set(ACTIONS)
                or any(not isinstance(v, str) or not HASH.fullmatch(v) for v in contract['actions'].values())):
            raise NativeBridgeError('工作流尚未形成完整的服务端核验合同')
        tool_key = self.tool_key or contract.get('native_tool_key')
        if not isinstance(tool_key, str) or not IDENTIFIER.fullmatch(tool_key):
            raise NativeBridgeError('服务端尚未配置原生预测API工具', 503)
        if self.tool_key and contract.get('native_tool_key') not in (None, self.tool_key):
            raise NativeBridgeError('工作流与服务端原生API工具配置不一致')

        prefix = '/workspace/api/v1/linsight/workbench/'
        versions, _ = self._get(prefix + 'session-version-list?' + urllib.parse.urlencode({'session_id': chat_id}), cookie)
        version = next((v for v in versions if isinstance(v, dict) and v.get('id') == session_version_id), None) if isinstance(versions, list) else None
        if (not version or version.get('session_id') != chat_id
                or version.get('status') not in ({'completed', 'in_progress', 'running'} if business_checkpoint else {'completed'}) or not version.get('model')
                or not isinstance(version.get('skills'), list) or SKILL not in version['skills']):
            raise NativeBridgeError('原生任务未完成、会话不匹配或未选中预测Skill')
        # These skills enable other scenes' fixed terminal middleware.
        if set(version['skills']) & {'procurement-history', 'order-tracking', 'transport-history', 'customs-history'}:
            raise NativeBridgeError('预测任务混入了其他场景的固定执行Skill')
        def selected_tools(groups):
            for group in groups if isinstance(groups, list) else []:
                if isinstance(group, dict):
                    yield group
                    yield from selected_tools(group.get('children'))
        selected_api = [tool for tool in selected_tools(version.get('tools')) if tool.get('tool_key') == tool_key]
        if len(selected_api) != 1 or not isinstance(selected_api[0].get('id'), int):
            raise NativeBridgeError('原生任务未选择服务端配置的预测API工具')
        selected_id = selected_api[0]['id']

        catalog, _ = self._get('/api/v1/linsight/skill/runtime/catalog', cookie)
        if isinstance(catalog, dict):
            catalog = catalog.get('skills', catalog.get('items', []))
        entries = [s for s in catalog if isinstance(s, dict) and s.get('name') == SKILL] if isinstance(catalog, list) else []
        entries = [s for s in entries if s.get('enabled') is not False and HASH.fullmatch(str(s.get('content_hash', '')))]
        if len(entries) != 1:
            raise NativeBridgeError('当前登录用户的原生Skill目录缺少唯一有效预测Skill')

        config, _ = self._get('/workspace/api/v1/workstation/config', cookie)
        model_id = str(version['model'])
        models = config.get('models', []) if isinstance(config, dict) else []
        model = next((m for m in models if isinstance(m, dict) and str(m.get('id')) == model_id
                      and m.get('enabled') is not False), None)
        if not model or not isinstance(model.get('name'), str) or not model['name']:
            raise NativeBridgeError('原生任务模型不在当前授权模型目录中')
        available = list(selected_tools(config.get('tools', [])))
        api_tool = next((t for t in available if t.get('tool_key') == tool_key
                         and t.get('name') == 'forecast_execute' and t.get('enabled') is not False
                         and t.get('id') == selected_id), None)
        if not api_tool:
            # New native tools need not mutate the global workbench defaults.
            # This authenticated endpoint is filtered for the current user's
            # visible resources; runtime use permission remains enforced by
            # the native task executor itself.
            native_tools, _ = self._get('/api/v1/tool?action=visible&is_preset=0', cookie)
            candidates = []
            for group in native_tools if isinstance(native_tools, list) else []:
                if not isinstance(group, dict):
                    continue
                for tool in group.get('children', []):
                    if not isinstance(tool, dict):
                        continue
                    if (tool.get('tool_key') == tool_key and tool.get('name') == 'forecast_execute'
                            and tool.get('id') == selected_id and tool.get('is_delete', 0) == 0
                            and tool.get('enabled') is not False
                            and isinstance(version.get('user_id'), int)
                            and tool.get('user_id') == version['user_id']
                            and group.get('user_id') == version['user_id']):
                        candidates.append(tool)
            if len(candidates) != 1:
                raise NativeBridgeError('当前原生工具目录缺少与任务身份匹配的预测API工具')
            api_tool = candidates[0]

        detail, raw = self._get(prefix + 'execute-task-detail?' + urllib.parse.urlencode({'session_version_id': session_version_id}), cookie)
        if not isinstance(detail, list):
            raise NativeBridgeError('原生任务详情格式无效', 502)
        records = list(_history(detail))
        if not any(_skill_read(record,contract['skill_sha256']) for record in records):
            raise NativeBridgeError('原生执行记录未证明读取预测Skill正文')
        matched = {}
        for record in records:
            if (record.get('name') not in {tool_key, 'forecast_execute'} or record.get('error')
                    or record.get('status') in ('error', 'failed', 'failure')
                    or record.get('is_completed') is False):
                continue
            # Restrict proof to API tool outputs. A CLI/source artifact hash may
            # identify the bundle; it does not claim that the CLI was executed.
            output = record.get('output')
            objects = list(_objects(output))
            if any(o.get('ok') is False or o.get('error')
                   or isinstance(o.get('status_code'), int) and o['status_code'] >= 400
                   for o in objects):
                continue
            prepared = [o for o in objects if o.get('action') == 'prepare']
            if prepared:
                if len(prepared) != 1:
                    continue
                packet = prepared[0]
                subactions = packet.get('subactions')
                if (packet.get('ok') is not True or packet.get('run_id') != contract['run_id']
                        or packet.get('skill_sha256') != contract['skill_sha256']
                        or packet.get('cli_sha256') != contract['cli_sha256']
                        or not isinstance(subactions, list) or len(subactions) != 2
                        or any(not isinstance(r, dict) for r in subactions)
                        or [r.get('action') for r in subactions] != ['forecast', 'history']):
                    continue
                common={k:packet[k] for k in ('run_id','skill_sha256','cli_sha256')}
                if any(set(r)-{'ok','action','action_sha256','state','run_id','skill_sha256','cli_sha256'}
                       or any(k in r and r[k]!=v for k,v in common.items()) for r in subactions):
                    continue
                objects = [{**common,**r} for r in subactions]
            for receipt in objects:
                action = receipt.get('action')
                if (action in ACTIONS and receipt.get('ok') is True
                        and receipt.get('run_id') == contract['run_id']
                        and receipt.get('action_sha256') == contract['actions'][action]
                        and receipt.get('skill_sha256') == contract['skill_sha256']
                        and receipt.get('cli_sha256') == contract['cli_sha256']):
                    matched[action] = receipt['action_sha256']
        if set(matched) != set(ACTIONS):
            raise NativeBridgeError('原生预测API工具未返回本次Skill三个成功动作的匹配回执')
        return {'chat_id': chat_id, 'session_version_id': session_version_id,
                'model': model['name'], 'model_id': model_id, 'status': version['status'],
                'completion_gate': 'all_business_actions_verified' if business_checkpoint else 'native_task_completed',
                'tool_action_sha': matched, 'skill_catalog_hash': entries[0]['content_hash'],
                'execution_tool': 'native_api', 'native_tool_key': tool_key, 'native_tool_id': selected_id,
                'task_detail_sha256': hashlib.sha256(raw).hexdigest(),
                'verified_at': datetime.now(timezone.utc).isoformat()}
