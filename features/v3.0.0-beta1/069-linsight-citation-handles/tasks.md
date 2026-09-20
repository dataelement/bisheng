# Tasks: 灵思任务模式引用溯源可靠性（短句柄 + 审计）

**关联规格**: [spec.md](./spec.md) · 设计: [design.md](./design.md)
**版本**: v3.0.0-beta1（发版线 `feat/3.0.0-beta2`，分支 `feat/3.0.0-beta2-069-linsight-citation-handles`）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-09-20 用户确认（sdd-review 修订后，AC-01 至 AC-27 共 27 条） |
| design.md | ✅ 已评审 | 2026-09-20 用户确认（决策 1～8）；接手时的第一入口 |
| tasks.md | ✅ 已拆解 | 2026-09-20 sdd-review 两轮（41 项）；第二轮 2 项 medium（P2 保留剥未知编号、T031/T033 依赖）已直接修正 |
| 实现 | 🔄 进行中 | 33 / 41 完成（Wave 1、Wave 2 全部完成；A/B uncited 44% → 0%，见 design §7；预览角标已核实）。Wave 3（P2）待产品确认版式。Wave 1（P0）先行；Wave 2（P1）待 P0 基线；Wave 3（P2）待产品确认版式 |

---

## 开发模式

**按 Wave 组织**：Wave 1 = P0（度量、诚实呈现、提示词位置），Wave 2 = P1（短句柄契约），Wave 3 = P2（导出烘焙）。Wave 内按依赖排序，无依赖任务可并行。

**后端 Test-First**：每个实现任务前有配对测试任务（红→绿）。全部单测不依赖中间件：Redis 用 `AsyncMock` 替身，任务执行器用 `test_task_exec_report_citations.py` 的 `completion_task` fixture 形态。

**前端 Client**：i18n 三语同一提交；组件加 jest 测试（样板 `Execution/TaskPanel.test.tsx`）；手动验证在 116 test 环境。

**Worker 与租户**：全部新逻辑运行在灵思 worker 进程内、`_create_agent` 之后，此时 `_restore_tenant_context` 已恢复 `current_tenant_id` ContextVar；新增 Redis 键按 svid / session_id 隔离、不含 tenant，无新表，无 Celery 任务。

**两阶段替换是有意的**：T009 的 P0 提示词措辞在 T022 被 P1 编号措辞替换、T027/T028 的 P1「剥未知编号」在 T038/T040 被 P2 烘焙替换——各阶段分别上线并在 116 取基线（T013 / T034），不是遗漏。**基础设施例外**：Wave 2 的基础设施任务（Redis 命令、配置开关）排在 Wave 1 之后，因 Wave 1 不依赖二者且 Wave 2 待 P0 基线后才启动。

**自包含**：每个任务内联文件、逻辑、AC；设计论证指向 design §X 不复制。行号以 design 记录的 `3b8b83965` 为准，实施时以函数名为锚重新定位。

**验证命令**（worktree 里先软链主检出的 `src/backend/.venv`、`src/backend/bisheng/config.yaml`、`src/frontend/**/node_modules`）：

```bash
cd src/backend && unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
.venv/bin/python -m pytest <测试文件> -q -p no:cacheprovider -W ignore
.venv/bin/ruff check <改动文件>
cd ../frontend && node scripts/check-i18n.mjs
cd client && ../node_modules/.bin/tsc-strict && node_modules/.bin/jest <测试文件>
```

---

## Tasks

### Wave 1 — P0：来源记账、完成时审计、提示词位置、前端提示

#### 来源记账（后端 Domain，Test-First 配对）

- [x] **T001**: `LinsightCitationScope` 单元测试
  **文件**: `src/backend/test/citation/test_linsight_citation_scope.py`
  **逻辑**: 用 `AsyncMock` 替身 Redis（monkeypatch `bisheng.citation.domain.services.linsight_citation_scope.get_redis_client`）。断言：`record_seen(items)` 对键 `linsight:cite_seen:<svid>` 调 `ahset(mapping={item_key: type})` 并 `aexpire_key(..., 30*24*3600)`；`seen_keys` 去重且进程内累积；`load()` 用 `ahgetall` 回填 `seen_keys`；Redis 抛异常时 `record_seen` / `load` 只记 warning、不抛、`seen_keys` 仍按进程内累积；`items` 为空不写 Redis。
  **覆盖 AC**: AC-02, AC-25
  **依赖**: 无

- [x] **T002**: `LinsightCitationScope` 实现
  **文件**: `src/backend/bisheng/citation/domain/services/linsight_citation_scope.py`（新）
  **逻辑**: `class LinsightCitationScope(svid: str, session_id: str, enabled: bool = True)`；属性 `seen_keys: set[str]`；`async record_seen(items: list[CitationRegistryItemSchema])`：取 `build_item_key`（`citation_registry_service.py`）得 key，`ahset(name, mapping=)` + `aexpire_key`（`core/cache/redis_conn.py` `ahset`/`aexpire_key`，样板 `knowledge/domain/services/knowledge_utils.py` L174-207）；`async load()`：`ahgetall` 回填；两者包 try/except 记 warning（design §2「绝不 raise」）。Redis 键 `linsight:cite_seen:<svid>`，无花括号（design §2）。
  **测试**: T001 全绿
  **依赖**: T001

- [x] **T003**: 检索工具与联网包装器记账钩子测试
  **文件**: `src/backend/test/linsight/test_linsight_citation_scope_hooks.py`
  **逻辑**: (a) `SearchKnowledgeBase.base_search`（monkeypatch `cache_citation_registry_items` 与 vector client，样板 `test_linsight_knowledge_citations.py`）：设 `tool.citation_scope = scope` 后调用，`scope.record_seen` 被 await 且收到 annotate 后的 items；`citation_scope=None` 时输出与今天逐字节相同。(b) `_LinsightWebCitationWrapper.wrap(inner, scope=scope)._arun(...)`（样板 `test_linsight_citation_agent.py` 的 `cache_web` fixture）同样记账；`scope=None` 不变。(c) `_subagent_tools(tools)` 返回的工具实例与入参同一对象（`is` 断言），证明子代理共用 scope。(d) `create_linsight_agent(session, tools, citation_scope=scope)`（monkeypatch `create_deep_agent` 捕获 `tools`、`_resolve_model`、`settings`）：KB 工具 `citation_scope is scope`，web 工具为带 scope 的包装器。
  **覆盖 AC**: AC-02, AC-25
  **依赖**: T002

- [x] **T004**: 检索工具与联网包装器接 scope
  **文件**: `src/backend/bisheng/tool/domain/langchain/linsight_knowledge.py`、`src/backend/bisheng/linsight/domain/services/agent_factory.py`
  **逻辑**: `SearchKnowledgeBase` 新增 pydantic 字段 `citation_scope: Any | None = None`（样板同文件 `allowed_knowledge_ids`）；`base_search` 在 `await cache_citation_registry_items(items)` 之后、既有 try 内 `if self.citation_scope: await self.citation_scope.record_seen(items)`。`agent_factory.py`：把 `_annotate_web_search_output(output)` 拆成 `_annotate_web_search_items(output) -> tuple[str, list]`（原函数保留为薄封装，既有测试不改）；`_LinsightWebCitationWrapper` 新增字段 `scope: Any = None`，`wrap(inner, scope=None)`，`_arun` 用新函数并 `record_seen`；`_wrap_linsight_web_citation_tools(tools, scope=None)` 透传。
  **测试**: T003 (a)(b)(c) 全绿；`test_linsight_citation_agent.py`、`test_linsight_knowledge_citations.py` 不破
  **依赖**: T003

- [x] **T005**: 执行器构造 scope 并绑定到工具
  **文件**: `src/backend/bisheng/linsight/domain/services/agent_factory.py`、`src/backend/bisheng/linsight/domain/task_exec.py`
  **逻辑**: `create_linsight_agent(..., citation_scope=None)`：原 `tools = _wrap_linsight_web_citation_tools(list(tools or []))` 处改为 `_bind_linsight_citation_scope(tools, citation_scope)`（KB 工具设 `citation_scope` 字段、web 工具包装带 scope），`_subagent_tools` 取同一批实例。`task_exec._create_agent`：构造 `LinsightCitationScope(svid=session_model.id, session_id=session_model.session_id)`，`await scope.load()`（resume / continue 回读），存 `self._citation_scope`，传 `citation_scope=scope`。
  **测试**: T003 (d) 用例全绿
  **依赖**: T004

#### 完成时审计（后端 Domain，Test-First 配对）

- [x] **T006**: `_audit_report_citations` 与三条完成路径测试
  **文件**: `src/backend/test/linsight/test_citation_audit.py`
  **逻辑**: 克隆 `test_task_exec_report_citations.py` 的 `completion_task` fixture（`LinsightWorkflowTask()` + 各 AsyncMock），补 `task._citation_scope = SimpleNamespace(seen_keys={...})`；`build_fallback_report_file` / `get_final_result_file` 用 monkeypatch 返回临时 md。断言：直答、部分、成功三条路径的 `session_model.output_result["citation_audit"]` 含 `sources_seen, cited, unknown_handles, bracket_numbers, footnotes_without_defs, status, scanned_files, html_only, persisted`；seen>0 且 md 含真实标记 → `cited`；seen>0 且无标记 → `uncited` 且 caplog 有 `WARNING` 行以 `[linsight-citation-audit]` 开头、含 `model=`；seen==0 → `no_sources` 为 INFO；只有 `.html` 交付物且 seen>0 → `uncited` 且 `html_only=True`；正文 `[^1]` 无 `[^1]:` 定义计 `footnotes_without_defs=1`、`[3]` 计 `bracket_numbers=1`；`answer` 前后逐字节相同；`_citation_scope=None` 时 `status="no_sources"`；审计函数抛异常时完成路径照常结束且 `citation_audit` 缺省（不阻断）。
  **覆盖 AC**: AC-01, AC-03, AC-05, AC-26
  **依赖**: T002

- [x] **T007**: `_audit_report_citations` 实现与三条路径接线
  **文件**: `src/backend/bisheng/linsight/domain/task_exec.py`
  **逻辑**: 新方法 `_audit_report_citations(self, session_model, answer, final_files) -> dict`（放 `_persist_report_citations` 之前）：`sources_seen = len(self._citation_scope.seen_keys)`（无 scope 则 0）；扫描 `final_files` 中本地存在的 `.md`（同 `_persist_report_citations` 的读法）+ `answer`；`cited = len(set(extract_citation_ids_from_text(text)))`（`citation_prompt_helper.py`）；`footnotes_without_defs = max(0, count(r"\[\^\d+\](?!:)") - count(r"^\[\^\d+\]:", M))`；`bracket_numbers = count(r"(?<!\[)\[\d{1,3}\](?!\()")`；`html_only = 无 .md 但有 .html`；`status`：seen==0→`no_sources`，cited>0→`cited`，否则→`uncited`；`scanned_files` ≤20；`unknown_handles=[]`（P1 填）；日志一行 `[linsight-citation-audit] session={svid} model={getattr(session_model,'model',None)} status= sources_seen= cited= unknown_handles= footnotes_without_defs= bracket_numbers= html_only=`，`uncited` 用 `logger.warning` 否则 `logger.info`；整体 try/except 返回 `{}`。三条路径在 `build_fallback_report_file` 之后、`session_model.output_result = {...}` 之前调用，字典加 `"citation_audit": audit`（design 决策 7；`_handle_direct_answer_completion`、`_handle_task_partial`、`_handle_task_success`）。`_persist_report_citations` 末尾把 `len(payloads)` 写进 `output_result["citation_audit"]["persisted"]`（沿用其 copy+reassign）。不改 answer。
  **测试**: T006 全绿；`test_task_exec_report_citations.py` 不破（fixture 需补 `_citation_scope = None`）
  **依赖**: T006

#### 提示词位置（后端 Domain，Test-First 配对）

- [x] **T008**: 引用尾巴中间件与 3a 门控测试
  **文件**: `src/backend/test/linsight/test_citation_tail_middleware.py`
  **逻辑**: 样板 `test_harness_profile_and_time.py` 的 `_FakeReq` + handler 捕获：`_CitationTailMiddleware(_LINSIGHT_CITATION_TAIL_ZH)` 把文本追加到 system 末块、`name == "LinsightCitationTail"`、`tools == []`、文本不含 U+E200 且含「Citation Rules」；`_build_linsight_system_prompt(True)`（位置参数，兼容 `test_skill_prompt_priority.py` 调用形态）含 3a 引用句；`_build_linsight_system_prompt(False, has_web_search=True)` 含；`(False)` 不含且不含 `__CITATION_DELIVERABLE_LINE__`。中间件栈：monkeypatch `create_deep_agent` 捕获 `middleware` 列表，`has_kb=True` 时列表含 `LinsightCitationTail` 且其索引小于 `LinsightLanguageTail`；无 kb/web 时不含；researcher 子代理 spec 的 `middleware` 同样规律。
  **覆盖 AC**: AC-06
  **依赖**: 无

- [x] **T009**: 3a 占位符、`has_web_search` 入参、`_CitationTailMiddleware`
  **文件**: `src/backend/bisheng/linsight/domain/services/agent_factory.py`
  **逻辑**: 3a 行「其它格式由它派生）。」后插 `__CITATION_DELIVERABLE_LINE__`；`_build_linsight_system_prompt(has_knowledge_base, skills_present=False, has_code_interpreter=False, has_web_search=False)`，replace 链解析占位符为「正文中凡依据检索资料写出的事实、数字、引文，在该句或该段末尾按 Citation Rules 逐字复制来源标识并用引用标记包裹。」（仅 `has_knowledge_base or has_web_search`），否则空串；新增常量 `_LINSIGHT_CITATION_TAIL_ZH`，正文：
  「# 来源标注（与上文 Citation Rules 同一要求，不改变其它任何要求）

  写 output/ 下的 markdown 交付物和最终回复时，凡依据检索资料写出的事实、数字、引文，在该句或该段末尾按 Citation Rules 的格式逐字复制检索结果里的来源标识（知识库 `<chunk_id>`、联网 `citation_key`）并用引用标记包裹；一句用了多条资料就把多个标识放在同一组标记里。」
  与 `class _CitationTailMiddleware(_LanguageTailMiddleware)`（只覆盖 `name` 返回 `"LinsightCitationTail"`）；`has_kb/has_web` 的计算上移到中间件列表构造之前；主栈语言尾巴之前 `if has_kb or has_web: middlewares.append(_CitationTailMiddleware(_LINSIGHT_CITATION_TAIL_ZH))`；researcher 栈同样（`_build_researcher_subagent` 已算好 `has_kb/has_web`，把结果经 spec 私有键传入、构造后 pop）；`create_deep_agent` 调用传 `has_web_search=has_web`；语言指令文本一字不动（design §5 #4）。
  **测试**: T008 全绿；`test_skill_prompt_priority.py`、`test_invalid_tool_call_middleware.py`、`test_harness_profile_and_time.py`、`test_linsight_citation_agent.py` 不破
  **依赖**: T008

#### 前端 Client（i18n + 组件 + 测试）

- [x] **T010**: 零引用提示三语文案
  **文件**: `src/frontend/client/src/locales/zh-Hans/translation.json`、`src/frontend/client/src/locales/en/translation.json`、`src/frontend/client/src/locales/ja/translation.json`
  **逻辑**: 各加 `com_linsight_citation_uncited`（`{{0}}` 位置占位，与 `com_linsight_files_ready_suffix` 同格式，放其附近）：zh-Hans「本次检索到 {{0}} 条资料，但报告正文未标注来源，暂无法提供溯源角标。」/ en「{{0}} sources were retrieved, but the report does not cite any of them, so no citation markers can be shown.」/ ja「{{0}} 件の資料を検索しましたが、レポート本文に出典が記されていないため、引用マーカーを表示できません。」
  **覆盖 AC**: AC-04
  **手动验证**: `cd src/frontend && node scripts/check-i18n.mjs` 三语 parity 通过
  **依赖**: 无

- [x] **T011**: `ResultSection` 渲染提示行并从三处调用点透传
  **文件**: `src/frontend/client/src/components/Linsight/Artifacts/ResultSection.tsx`、`src/frontend/client/src/components/Linsight/Execution/TaskTurnPanel.tsx`、`src/frontend/client/src/components/Linsight/Execution/ConversationRound.tsx`、`src/frontend/client/src/components/Linsight/Execution/ExecutionFlow.tsx`
  **逻辑**: `ResultSectionProps` 新增 `citationAudit?: { status?: string; sources_seen?: number } | null`；`status === 'uncited'` 时在 answer 块之后渲染一行 `<p className="text-sm text-text-3">{localize('com_linsight_citation_uncited', { 0: sources_seen ?? 0 })}</p>`（沿用文件内既有灰字样式；不加 Badge，design 决策 7）；三处调用点传 `citationAudit={...output_result?.citation_audit}`（`output_result` 在 `store/linsight.ts` 为 `any`，不改类型）。文件数超 3 的例外理由：三处调用点各只加一行 prop 透传，拆开会让新 prop 在中间态无人消费。历史回看与分享页走同一 `output_result` 通道，天然一致。
  **覆盖 AC**: AC-04
  **手动验证**: 116 test 环境（`http://192.168.106.120:3002/workspace`）跑一个知识库任务用 deepseek-v4-pro：完成后摘要下方出现提示行；刷新后仍在；分享页仍在；`no_sources` 任务无此行
  **依赖**: T010

- [x] **T012**: `ResultSection` jest 测试
  **文件**: `src/frontend/client/src/components/Linsight/Artifacts/ResultSection.test.tsx`
  **逻辑**: 样板 `Execution/TaskPanel.test.tsx`；三种 `citationAudit.status`（`uncited` 出现提示并含 `sources_seen` 数字；`cited`、`no_sources`、`undefined` 不出现）。
  **覆盖 AC**: AC-04
  **依赖**: T011

#### 真机基线

- [x] **T013**: 116 P0 基线取数
  **文件**: 无（结果记入 design §7）
  **逻辑**: 按 PRD §7：两题 × deepseek-v4-flash / -pro / qwen3.5 × 3 次；每次记 `docker logs bisheng-test-backend-worker | grep '\[linsight-citation-audit\]'` 一行与 MySQL `linsight_session_version.output_result.citation_audit`；统计 uncited 率作为 P1 对照基线；确认历史回看与分享页提示一致。
  **覆盖 AC**: AC-03, AC-04
  **依赖**: T007, T011（分支部署到 116 test，部署方式与用户确认）

### Wave 2 — P1：短句柄契约（待 P0 基线后启动）

#### 基础设施（无测试配对）

- [x] **T014**: Redis 客户端补 `ahincrby` / `ahsetnx`
  **文件**: `src/backend/bisheng/core/cache/redis_conn.py`
  **逻辑**: 仿 `ahset` / `ahget`：`async ahincrby(name, key, amount=1) -> int`、`async ahsetnx(name, key, value) -> bool`（先 `await self.acluster_nodes(name)`）；design 决策 4 的原子分配依赖。
  **依赖**: 无

- [x] **T015**: `LinsightConf.citation_handles_enabled` 开关
  **文件**: `src/backend/bisheng/core/config/settings.py`、`docker/bisheng/config/config.yaml`
  **逻辑**: `LinsightConf` 新增 `citation_handles_enabled: bool = Field(default=True, description=...)`；shipped `config.yaml` 没有 `linsight:` 段，只加连父键的注释示例（`# linsight:` / `#   citation_handles_enabled: true`）。运行期读法：`await settings.aget_linsight_conf()`（`bisheng.common.services.config_service.settings`，同步版 `settings.get_linsight_conf()` 在 agent_factory 已用）。
  **依赖**: 无

#### 句柄表服务（Test-First 配对）

- [x] **T016**: `citation_handle_service` 与 scope 扩展单元测试
  **文件**: `src/backend/test/citation/test_citation_handle_service.py`、`src/backend/test/citation/test_linsight_citation_scope.py`（追加）
  **逻辑**: Redis 用 `AsyncMock`：`assign(scope, items)`：同 identity（rag=`document_id+itemId`、web=`normalize_url`）二次分配返回同编号、`ahincrby(next)` + `ahsetnx(id:<identity>)` 抢占失败时读回已有编号、`h:<n>` 写 JSON `{key,type,title,loc}`、`meta:enabled` 首次写入、TTL 30d；Redis 异常返回空映射并 warning。`convert_handles_to_markers(text, handles)` 文法表：`[S3]`→单 key 标记；`[S3][S7]`、`[S3, S7]`、`[S3、S7]`→一组两 key；`[3]`、`[^3]`、`[S3](url)`、``` 代码块内 ```、行内 code、`[S3]: x` 定义行不动；`[S99]` 未知字面保留并进 `unknown`；已转换文本二次调用不变；返回 `converted` 计数。`strip_citation_handles` 删三种形态。scope 扩展：`LinsightCitationScope.load()` 同时水化 `handles` / `entries` / `enabled`（`meta:enabled`）。离线回放：把 116 两次 run 的 write_file 正文（取样保存为测试 fixture 文本）跑 `convert_handles_to_markers`，应 0 转换、`[^n]` 只计数。
  **覆盖 AC**: AC-07, AC-10, AC-11, AC-13, AC-16, AC-17, AC-27
  **依赖**: T002, T014

- [x] **T017**: `citation_handle_service` 实现与 scope 扩展
  **文件**: `src/backend/bisheng/citation/domain/services/citation_handle_service.py`（新）、`src/backend/bisheng/citation/domain/services/linsight_citation_scope.py`
  **逻辑**: 键 `linsight:cite_handles:<session_id>`；`_HANDLE = r"S\d{1,4}"`、`_GROUP`、`_RUN_RE`（design §4.2）；`async assign(scope, items) -> dict[key, handle]` 用 T014 的原子命令，表首次创建（`next` 不存在）时同时 `HSETNX meta:enabled <scope.enabled>`；`convert_handles_to_markers(text, handles) -> ConvertResult(text, converted, unknown, skipped_definitions)`；`strip_citation_handles(text)`。scope 新增属性 `handles: dict[str, str]`（handle→key）、`entries: list[dict]`、`unknown_handles: dict[str, int]`、`converted_count: int`；`load()` 从 `linsight:cite_handles:<session_id>` 水化并读 `meta:enabled`。
  **测试**: T016 全绿
  **依赖**: T016

#### 工具输出改写（Test-First 配对）

- [x] **T018**: 工具输出句柄化测试
  **文件**: `src/backend/test/linsight/test_linsight_knowledge_handles.py`
  **逻辑**: scope.enabled 时 KB 结果 `<chunk_id>key</chunk_id>` 变为 `<ref>S3</ref>`，`format_retrieved_chunk` 其余不变；web 结果多 `"ref": "S7"` 且无 `citation_key` / `itemId`；分配失败或 scope 关闭时保留旧形态。
  **覆盖 AC**: AC-07, AC-17, AC-18
  **依赖**: T017

- [x] **T019**: 工具输出句柄化实现
  **文件**: `src/backend/bisheng/tool/domain/langchain/linsight_knowledge.py`、`src/backend/bisheng/linsight/domain/services/agent_factory.py`
  **逻辑**: `base_search` 在 `record_seen` 之后调 `handles = await citation_handle_service.assign(scope, items)`（刷新 `scope.handles` / `scope.entries` 镜像），再在 `format_retrieved_chunk` 之后按 `handles` 做 `<chunk_id>` → `<ref>` 替换（不改 `format_retrieved_chunk`）；web wrapper `_arun` 同样先 `assign` 再按 `handles` 加 `ref`、删 `citation_key` / `itemId`；`assign` 返回空映射（Redis 故障或 scope 关闭）时保留旧形态。
  **测试**: T018 全绿
  **依赖**: T018

#### 提示词换编号（Test-First 配对）

- [x] **T020**: 短规则与编号措辞测试
  **文件**: `src/backend/test/linsight/test_linsight_citation_agent.py`（改 5 个既有用例：`test_citation_rules_only_when_kb_or_web`、`test_citation_rules_require_real_pua_and_cover_written_files`、`test_with_citation_rules_delegates_to_the_shared_backstop`、`test_researcher_prompt_requires_last_message_handoff_when_citable`、`test_researcher_subagent_injects_rules_for_web_search` 改按 `handles` 分支断言）、`src/backend/test/linsight/test_citation_tail_middleware.py`（追加 P1 文本断言）
  **逻辑**: `_with_citation_rules(prompt, enabled, handles=True)` 追加 `citation_handles.yaml` 的「# 来源编号」段且幂等；`handles=False` 走 `ensure_citation_rules` 且 3a 句 / 尾巴 / researcher 交接行保持 T009 的 P0（逐字复制）措辞；`handles=True` 时三处为编号措辞（PRD 附录 C）。
  **覆盖 AC**: AC-06, AC-09, AC-18
  **依赖**: T009

- [x] **T021**: 短规则与编号措辞实现
  **文件**: `src/backend/bisheng/core/prompts/yaml/citation_handles.yaml`（新）、`src/backend/bisheng/linsight/domain/services/agent_factory.py`
  **逻辑**: yaml key `linsight_handle_rules`，正文：
  「# 来源编号

  检索结果里每条资料都带一个编号（知识库 `<ref>S3</ref>`，联网 `"ref": "S7"`）。写 output/ 下的 markdown 交付物和最终回复时，凡依据检索资料写出的事实、数字、引文，在该句或该段末尾写编号：`……市占率为 31%。[S3]`；一句用了多条资料写 `[S3][S7]`。编号必须是检索结果或本轮来源表里出现过的；没有对应资料的句子不标。编号就是全部标注，不需要再列参考文献或来源名称。」
  `_with_citation_rules` 增 `handles` 分支（判据 `"# 来源编号" in prompt`）。三处文本**各保留两套**（P0 逐字复制 / P1 编号），由 `handles`（= `scope.enabled`）选择，供 T032 的开关回退：
  - 3a 句（P1）：「正文中凡依据检索资料写出的事实、数字、引文，在该句或该段末尾写来源编号，如 [S3] 或 [S3][S7]。」
  - 尾巴（P1）：「# 来源编号（与上文「来源编号」同一要求，不改变其它任何要求）\n\n写交付物正文和最终回复时，每条依据检索资料的句子末尾写编号 [Sn]，多条写 [S3][S7]；编号取自检索结果或本轮来源表。」
  - researcher 交接行（P1）：「- 检索结果中的来源编号（如 S3）必须原样出现在你的最后一条消息里的对应句末，写作 [S3]，供主智能体写入报告正文；不要改写成参考文献列表或来源名称。」
  `citation.yaml` 不动。
  **测试**: T020 全绿
  **依赖**: T020

#### 每轮来源表与一次提醒（Test-First 配对）

- [x] **T022**: `LinsightCitationSourceMiddleware` 测试
  **文件**: `src/backend/test/linsight/test_citation_source_middleware.py`
  **逻辑**: `_FakeReq` 样板：`scope.entries` 非空时 `awrap_model_call` 追加临时 HumanMessage（`request.state["messages"]` 不变）；超过 150 条时按编号倒序取最近 150 条并加「其余见检索结果」；state 末批 ToolMessage 有 `write_file` 成功且 `file_path` 匹配 `output/*.md`、内容零句柄、表非空 → 追加提醒、写 Redis `nudged:<svid>:<path>` 并打 `[linsight-citation-nudge] session= file=` 日志；已有该字段不再提醒；`budget_sink["soft_landing"]` 为真跳过；`is_subagent=True` 只给表不提醒；无 write_file 不提醒。
  **覆盖 AC**: AC-08, AC-15
  **依赖**: T017

- [x] **T023**: `LinsightCitationSourceMiddleware` 实现与挂载
  **文件**: `src/backend/bisheng/linsight/domain/services/citation_source_middleware.py`（新）、`src/backend/bisheng/linsight/domain/services/agent_factory.py`
  **逻辑**: 样板 `resilience_middleware.py` `_with_wrap_up_nudge`、`tool_loop_middleware.py` `_repeat_nudge`；只实现 `awrap_model_call`，绝不实现 `wrap_tool_call`（design 决策 5）；提醒去重与 `[linsight-citation-nudge]` 日志在本文件；主栈在 tool-loop breaker 之后挂载（`has_kb or has_web` 且 `scope.enabled`），researcher 栈 `is_subagent=True`。
  **测试**: T022 全绿
  **依赖**: T022

#### 写边界与 answer 转换（Test-First 配对）

- [x] **T024**: 写边界转换测试
  **文件**: `src/backend/test/linsight/test_workspace_backend_citation_handles.py`、`src/backend/test/linsight/test_citation_audit.py`（追加 answer 转换用例）
  **逻辑**: `WorkspaceBackend(..., citation_scope=scope)`：`write` / `awrite` / `edit` 写 `.md` 时 `[S3]` → 私有区标记；`edit` 的 `old_string` 含 `[S3]` 时先转换再匹配磁盘；`.txt` / `.html` 不转换；scope 关闭只做 unescape；未知句柄计入 `scope.unknown_handles`；已转换文本二次写入不变。三条完成路径 answer 在软着陆注记之后、兜底报告之前转换，兜底 `报告.md` 含标记。
  **覆盖 AC**: AC-10, AC-12, AC-14, AC-25, AC-27
  **依赖**: T005, T017

- [x] **T025**: 写边界转换实现
  **文件**: `src/backend/bisheng/linsight/domain/services/workspace_backend.py`、`src/backend/bisheng/linsight/domain/task_exec.py`
  **逻辑**: `WorkspaceBackend.__init__(..., citation_scope=None)`；`_normalize_markdown_citation_bytes` 改为实例方法 `_canonicalize_citation_bytes(rel, data)`：unescape → `convert_handles_to_markers`；`write` / `edit`（含 `old_string`）/ `awrite` 调用，每次把 `ConvertResult.converted` 累加到 `scope.converted_count`、`unknown` 累加到 `scope.unknown_handles`；`_create_agent` 传 scope；新方法 `_canonicalize_answer_citations(answer)` 在三条路径接线（同样累加）。
  **测试**: T024 全绿；`test_workspace_backend.py` 不破
  **依赖**: T024

#### 导出剥未知编号（后端 / 前端分开，Test-First 配对）

- [x] **T026**: 后端导出剥未知编号测试
  **文件**: `src/backend/test/linsight/test_linsight_export.py`（追加）、`src/backend/test/linsight/test_download_md_export_strips_citations.py`（追加）
  **逻辑**: docx / pdf 导出工具、单文件转换端点、zip 内 md：输入含 `[S99]`（未登记）与私有区标记的 md，输出既无标记也无 `[S99]`；已识别标记按既有 `strip_citation_markers` 剥离。
  **覆盖 AC**: AC-19, AC-24
  **依赖**: T017

- [x] **T027**: 后端导出剥未知编号实现
  **文件**: `src/backend/bisheng/tool/domain/langchain/linsight_export.py`、`src/backend/bisheng/linsight/api/endpoints/linsight.py`
  **逻辑**: 各调用点在 `strip_citation_markers` 之后调 `strip_citation_handles`。
  **测试**: T026 全绿
  **依赖**: T026

- [x] **T028**: 前端 Client 另存 md 剥未知编号
  **文件**: `src/frontend/client/src/components/Linsight/Artifacts/artifactUtils.ts`、`src/frontend/client/src/components/Linsight/Artifacts/artifactUtils.test.ts`
  **逻辑**: 另存 md 路径在 `stripCitationMarkers` 后剥 `[S\d{1,4}]` 三种形态（jest 先写红测再实现）；复制路径不动（design §8）。
  **覆盖 AC**: AC-19, AC-24
  **手动验证**: 116 另存含 `[S99]` 的报告，文件内无编号
  **依赖**: T017

#### 审计扩展与契约钉住（Test-First 配对）

- [x] **T029**: 审计扩展测试
  **文件**: `src/backend/test/linsight/test_citation_audit.py`（追加）
  **逻辑**: `citation_audit` 含 `unknown_handles`（来自 `scope.unknown_handles`，≤50）与 `converted`；日志行含 `converted=`。
  **覆盖 AC**: AC-01, AC-13
  **依赖**: T025

- [x] **T030**: 审计扩展实现
  **文件**: `src/backend/bisheng/linsight/domain/task_exec.py`
  **逻辑**: `_audit_report_citations` 读 `scope.unknown_handles` / `scope.converted_count`；日志行加 `converted=`。
  **测试**: T029 全绿
  **依赖**: T029

- [x] **T031**: 开关与在途会话契约测试
  **文件**: `src/backend/test/linsight/test_citation_handles_switch.py`
  **逻辑**: `_create_agent`（monkeypatch `create_linsight_agent`、`WorkspaceBackend`、`materialize_session_skills`、`settings.aget_linsight_conf`）：会话已有 `meta:enabled=0` 时 scope.enabled 为 False 即使配置为 True（在途会话不换契约）；无 `meta:enabled` 时取配置值并在首次分配时写入；开关关闭时 `create_linsight_agent` 收到 `scope.enabled=False` → 工具输出旧形态、`_with_citation_rules(handles=False)`、不挂 source middleware、写盘只 unescape；审计照常写。
  **覆盖 AC**: AC-16, AC-18
  **依赖**: T015, T017, T019, T021, T023, T025

- [x] **T032**: 开关与在途会话契约实现
  **文件**: `src/backend/bisheng/linsight/domain/task_exec.py`、`src/backend/bisheng/linsight/domain/services/agent_factory.py`
  **逻辑**: `_create_agent` 先 `await scope.load()` 读 `meta:enabled`，无则 `(await settings.aget_linsight_conf()).citation_handles_enabled`，写 `scope.enabled`（首次落 `meta:enabled` 由 T017 的 `assign` 在建表时完成，design 决策 6）；`create_linsight_agent` 按 `scope.enabled` 选择工具输出 / 规则文本（T021 两套）/ 是否挂 source middleware；写盘边界看 `scope.enabled`。
  **测试**: T031 全绿
  **依赖**: T031

- [x] **T033**: 116 P1 A/B 与判定
  **文件**: 无（结果记入 design §7）
  **逻辑**: PRD §7 同题同模型各 3 次；指标 uncited 率、cited 中位数、unknown_handles 率（<5%）、footnotes_without_defs、每轮 token 增量、nudge 触发数；判定保留默认开或关开关。
  **覆盖 AC**: AC-07, AC-15, AC-18
  **依赖**: T030, T032

### Wave 3 — P2：导出烘焙（待产品确认版式）

- [ ] **T034**: `render_citations_for_export` 测试
  **文件**: `src/backend/test/citation/test_citation_handle_service.py`（追加）
  **逻辑**: 输入 md（含私有区标记）与已按导出者 resolve 的来源列表：按首现顺序编号 `[n]`、文末「参考资料」（知识库：文档名+定位；网页：标题+URL）；未解析的 key 剥离不编号；无来源时等价 `strip_citation_markers`。
  **覆盖 AC**: AC-20, AC-21, AC-22, AC-24
  **依赖**: T017

- [ ] **T035**: `render_citations_for_export` 实现
  **文件**: `src/backend/bisheng/citation/domain/services/citation_handle_service.py`
  **逻辑**: 纯函数，不查权限（design 决策 8）。
  **测试**: T034 全绿
  **依赖**: T034

- [ ] **T036**: 后端导出烘焙测试
  **文件**: `src/backend/test/linsight/test_linsight_export.py`（追加）
  **逻辑**: 导出工具与转换端点以导出者身份 `resolve_citations_with_reasons` 后烘焙；无权限来源不编号、不进参考资料；解析为空时退回剥标并有 `citations_baked=false` 日志；导出不失败；输出仍不含未识别编号 `[S99]`（AC-19 在 P2 继续成立）。
  **覆盖 AC**: AC-20, AC-21, AC-22, AC-24
  **依赖**: T035

- [ ] **T037**: 后端导出调用点改烘焙
  **文件**: `src/backend/bisheng/tool/domain/langchain/linsight_export.py`、`src/backend/bisheng/linsight/api/endpoints/linsight.py`
  **逻辑**: 导出前以导出者身份 `resolve_citations_with_reasons`（既有 `citation_resolve_service`，INV-7 执行点）取来源，调 `render_citations_for_export`；未解析退回剥离并记日志 `citations_baked=false`。替换 T027 引入位置上的 `strip_citation_markers` 调用；`strip_citation_handles`（剥未识别编号）保留（AC-19）。
  **测试**: T036 全绿
  **依赖**: T036

- [ ] **T038**: html 交付物上标与附录测试
  **文件**: `src/backend/test/linsight/test_workspace_backend_citation_handles.py`（追加）
  **逻辑**: 写 `.html` 时 `[S3]` → `<sup>[1]</sup>`，页尾追加附录（编号表标题）；无句柄时文件不变。
  **覆盖 AC**: AC-23
  **依赖**: T025

- [ ] **T039**: html 交付物上标与附录实现
  **文件**: `src/backend/bisheng/linsight/domain/services/workspace_backend.py`
  **逻辑**: 写 `.html` 分支（design 决策 8）。
  **测试**: T038 全绿
  **依赖**: T038

- [ ] **T040**: 前端 Client 另存 md 客户端烘焙
  **文件**: `src/frontend/client/src/components/Linsight/Artifacts/artifactUtils.ts`、`src/frontend/client/src/components/Linsight/Artifacts/artifactUtils.test.ts`
  **逻辑**: 用预览时已取回的解析结果（`output_result.citations` 种子 + 解析缓存）按与后端同一规则烘焙；未解析 key 剥离；不新增端点（design 决策 8）；替换 T028 中对已识别标记的剥离，未识别编号 `[S99]` 仍剥（AC-19）。jest 先写红测。
  **覆盖 AC**: AC-20, AC-24
  **手动验证**: 116 另存 md，文件含 `[n]` 与参考资料
  **依赖**: T035

- [ ] **T041**: F054 契约措辞修订、文档回写与 116 导出对照
  **文件**: `features/v3.0.0-beta1/054-unified-citation-entries/spec.md`、`features/v3.0.0-beta1/release-contract.md`、本目录 design.md
  **逻辑**: F054 AC-07 / AC-12 补「任务模式报告导出按 F069 AC-24 烘焙」的例外措辞；release-contract 变更历史加一行「F069 P2 交付、F054 AC-07/AC-12 措辞已修订」；design §7 记 A/B 结果；116 以有权限 / 无权限 / 分享页三种身份各导出 docx、pdf、md，核对编号与参考资料、无内部键、无权限来源不出现。
  **覆盖 AC**: AC-21, AC-22, AC-24
  **依赖**: T037, T040

---

## 实际偏差记录

> 只留一行指针，论证在 design.md。推翻已 ★ 确认的决策时先停下与用户重新确认。

- T003 (d) 用例需 stub `agent_factory.settings`（pydantic 实例不可 monkeypatch 属性，改为替换模块级 `settings` 对象）——实现细节，design 不变
- T006 审计日志断言改用 loguru sink（caplog 看不到 loguru）——实现细节，design 不变
- T017 偏离 → 句柄前瞻改为 ASCII 字母数字（Python `\w` 含 CJK，`结论[S3]` 不会转换）；前端 `stripCitationHandles` 同步（实现细节，design §4.2 文法表补一行）
- T032 偏离 → 契约钉 `meta:enabled` 改在 `_create_agent` 的 `scope.pin_contract()` 写入（不只靠首次分配）：逐字契约的会话永不分配句柄，否则开关翻开后追问轮会换契约 → 更新 design 决策 6
- T013 基线暴露：零引用时 `persisted` 未写回 DB 行（提前 return 跳过保存）→ 已修，design §7 记录
- T011 `ExecutionFlow.tsx` 第二个 `citations=` 属于 `FilePreviewPanel`，不透传 `citationAudit`（预览面板不显示提示）——与 spec AC-04「结果区摘要下方」一致
