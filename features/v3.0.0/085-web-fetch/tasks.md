# Tasks: 网页读取内置工具

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)
**版本**: v3.0.0
**分支**: `feat/3.0.0/085-web-fetch`

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-10-19 用户确认 |
| design.md | ✅ 已评审 | 2026-10-19 用户确认 |
| tasks.md | ✅ 已拆解 | 2026-10-19 sdd-review tasks 自查通过 |
| 实现 | 🔄 进行中 | 14 / 18 完成 |

---

## 开发模式

- 后端 Test-First：每组先写测试任务，再写实现任务。测试放在 `src/backend/test/tool/` 和 `src/backend/test/citation/`。
- 本地跑测试：在 `src/backend` 下执行 `env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy -u HTTP_PROXY -u http_proxy .venv/bin/python -m pytest -q <路径>`。
- 前端用手动验证 + `pnpm lint` / `pnpm typecheck` / `pnpm check-i18n`（在 `src/frontend/` 下执行）。
- 设计论证见 design.md 对应决策，任务里不重复。

---

## Tasks

### Wave 1 — 基础设施与工具本体

- [x] **T001**: 种子数据新增「网页读取」
  **文件**: `src/backend/bisheng/database/data/t_gpts_tools_type.json`, `src/backend/bisheng/database/data/t_gpts_tools.json`
  **逻辑**: 分类行 id=18，`name="网页读取"`，`is_preset=1`，`user_id=null`，`extra` 为 `{"type":"deepseek","config":{"deepseek":{"api_key":"","base_url":""}},"max_chars":20000}`。工具行 id=40，`tool_key="web_fetch"`，`type=18`，`is_preset=1`，`user_id=null`，`api_params` 为单个必填参数 `url`（`in: query`，`schema.type: string`）。名称和描述与 T014 的补数据函数保持一致（design 坑 9）。
  **依赖**: 无

- [x] **T002**: 网页读取工具本体单元测试
  **文件**: `src/backend/test/tool/test_web_fetch_tool.py`
  **逻辑**: mock `requests.post`，覆盖：请求地址、Bearer 头、请求体 `{"url"}`、超时 (10, 60)；Base URL 覆盖与留空回退默认地址；去转义（普通文本还原、代码块内保持原样）；截断（超过上限截断并带 `truncated`/`total_chars`/提示，等于上限不截断）；网址校验（非 http/https、带用户名密码时不发请求）；引擎错误体（HTTP 404 + `not_found_error`）和超时都返回文字而不抛异常；空正文返回提示；未配置秘钥返回「尚未配置」提示；`load_tools({"web_fetch": extra})` 能构建出 `name == "web_fetch"` 的工具。
  **覆盖 AC**: AC-05, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13
  **依赖**: 无

- [x] **T003**: 网页读取工具本体实现
  **文件**: `src/backend/bisheng_langchain/gpts/tools/web_fetch/tool.py`（新，含 `__init__.py`）, `src/backend/bisheng_langchain/gpts/load_tools.py`
  **逻辑**: `FetchTool` 引擎基类（`request_timeout=(10, 60)`、`init_fetch_tool(type, **cfg)` 注册表）+ `DeepSeekFetch`（默认地址 `https://api.deepseek.com/v1/tools/fetch`）。`WebFetchTool(BaseTool)`：`name="web_fetch"`，参数 `url`，持有 `api_wrapper` 和 `max_chars`（默认 20000，限定 1000～200000）。成功时返回 JSON 对象 `{"title","url","source","content","truncated","total_chars"}`；失败、未配置、网址不合法、空正文返回文字。`load_tools.py` 在 `_EXTRA_PARAM_TOOLS` 注册 `"web_fetch": (_get_web_fetch, [], ["type","config","max_chars"])`，配置缺失也能构建工具（design 决策 7）。
  **测试**: T002 全部通过
  **覆盖 AC**: AC-05, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13
  **依赖**: T002

- [x] **T004**: 网页读取引用标注单元测试
  **文件**: `src/backend/test/citation/test_web_fetch_citation.py`
  **逻辑**: `is_web_citation_tool` 识别 `web_search`、`web_fetch` 及包装后的工具（`tool_name` 属性）；`annotate_fetched_page_with_citation` 生成单条目 WEB 注册项（`itemId="1"`，title/source/snippet 正确，key 前缀 `websearch_`）；同一规范化网址第二次调用复用同一引用 ID 并再次返回注册条目；不同网址得到不同 ID；`rewrite_web_results_with_handles` 和 `drop_web_citation_keys` 接受单个网页对象。
  **覆盖 AC**: AC-19, AC-21
  **依赖**: 无

- [x] **T005**: 网页读取引用标注实现
  **文件**: `src/backend/bisheng/citation/domain/services/citation_prompt_helper.py`, `src/backend/bisheng/citation/domain/services/citation_handle_service.py`
  **逻辑**: 新增 `WEB_CITATION_TOOL_NAMES`、`is_web_citation_tool(tool)`；新增 `FetchedPageCitationRegistry`（以规范化网址为键缓存注册条目）和 `annotate_fetched_page_with_citation(page, registry)`，返回 `(带 citation_key 的网页对象, 注册条目)`，复用 `CitationRegistryService` 的 WEB 构建函数。句柄改写和去 key 函数对 dict 做与列表单项相同的处理（design 决策 3、决策 4）。
  **测试**: T004 全部通过
  **覆盖 AC**: AC-19, AC-21
  **依赖**: T004

### Wave 2 — 各场景接入与升级

- [x] **T006**: 助手和工作流引用包装层测试
  **文件**: `src/backend/test/citation/test_web_fetch_scenarios_agent.py`
  **逻辑**: 用假的 `web_fetch` 工具（返回固定网页对象）分别包进 `AssistantCitationToolWrapper`、`WorkflowCitationToolWrapper`，以 `{"url": ...}` 调用（同步和异步），断言内层工具收到 `url`、结果带 `citation_key`、注册条目进入收集器；同一包装实例重复读取同一网址复用 key；`web_search` 的原有行为（列表标注）不变；工作流工具节点 `ToolNode` 对 `web_fetch` 输出做同样标注。
  **覆盖 AC**: AC-14, AC-15, AC-16, AC-19
  **依赖**: T005

- [x] **T007**: 助手和工作流 agent 节点接入
  **文件**: `src/backend/bisheng/api/services/assistant_agent.py`, `src/backend/bisheng/workflow/nodes/agent/agent.py`
  **逻辑**: 识别改用 `is_web_citation_tool`；`_run/_arun` 改为 `**kwargs` 透传；按工具名分派：`web_search` 走原列表标注，`web_fetch` 走 `annotate_fetched_page_with_citation`，`FetchedPageCitationRegistry` 挂在包装实例上（design 决策 5）。
  **测试**: T006 中助手和工作流 agent 用例通过
  **覆盖 AC**: AC-14, AC-15, AC-19
  **依赖**: T006

- [x] **T008**: 工作流工具节点接入
  **文件**: `src/backend/bisheng/workflow/nodes/tool/tool.py`
  **逻辑**: `_is_web_search_tool` 改用 `is_web_citation_tool`；`web_fetch` 输出为 JSON 对象时做单页标注并写入 `WORKFLOW_CITATION_REGISTRY_ITEMS_KEY`。
  **测试**: T006 中工具节点用例通过
  **覆盖 AC**: AC-16, AC-19
  **依赖**: T006

- [x] **T009**: 日常模式接入测试
  **文件**: `src/backend/test/citation/test_web_fetch_daily_chat.py`
  **逻辑**: `DailyChatCitationToolWrapper` 包装 `web_fetch`，同步和异步调用都透传 `url`；异步短句柄模式下结果里是 `ref`（如 `S1`）而不是原始 key；`_build_tool_meta` 对 `web_fetch` 返回 `tool_type="web"`。
  **覆盖 AC**: AC-18, AC-19, AC-23
  **依赖**: T005

- [x] **T010**: 日常模式接入实现
  **文件**: `src/backend/bisheng/workstation/domain/services/chat_service.py`, `src/backend/bisheng/core/prompts/yaml/citation_handles.yaml`
  **逻辑**: 包装层识别、透传、分派同 T007；`_build_tool_meta` 把 `web_fetch` 归为 `web`；短句柄规则文字补「网页读取结果」（design 决策 9）。
  **测试**: T009 全部通过
  **覆盖 AC**: AC-18, AC-19, AC-23
  **依赖**: T009

- [x] **T011**: 任务模式接入测试
  **文件**: `src/backend/test/citation/test_web_fetch_linsight.py`
  **逻辑**: `_LinsightWebCitationWrapper` 包装 `web_fetch` 后结果带 key 并 `record_seen`；短句柄模式改写为 `ref`；引擎失败时返回文字不抛异常；只有 `web_fetch` 时研究员提示词和主图的 `has_web` 为真（断言研究员提示词包含来源交回要求）。
  **覆盖 AC**: AC-11, AC-17, AC-19
  **依赖**: T005

- [x] **T012**: 任务模式接入实现
  **文件**: `src/backend/bisheng/linsight/domain/services/agent_factory.py`, `src/backend/bisheng/core/prompts/yaml/citation.yaml`
  **逻辑**: `_is_web_search_tool` 改用 `is_web_citation_tool`（影响 `has_web` 三处和包装选择）；包装层对 `web_fetch` 做单页标注；`citation.yaml`「来源 ID」一节补网页读取结果的说明（design 决策 9）。
  **测试**: T011 全部通过
  **覆盖 AC**: AC-17, AC-19
  **依赖**: T011

- [x] **T013**: 升级补数据测试
  **文件**: `src/backend/test/tool/test_ensure_web_fetch_tool.py`
  **逻辑**: 用 SQLite 内存库：空库执行 `_ensure_web_fetch_tool` 后出现一个分类行和一个工具行，字段与种子一致，返回「本次新插入」；再执行一次不重复插入、返回「已存在」；分类 `extra` 与联网搜索分类互相独立。mock 投影和子租户复制函数，断言仅在新插入且 OpenFGA 开启时调用，多租户关闭时不复制。
  **覆盖 AC**: AC-01, AC-04, AC-26
  **依赖**: T001

- [x] **T014**: 升级补数据实现
  **文件**: `src/backend/bisheng/common/init_data.py`
  **逻辑**: 新增 `_ensure_web_fetch_tool(session) -> bool`（照 `_ensure_image_view_tool`），在其后调用；释放租户过滤绕过后，若新插入且 `settings.openfga.enabled`：为根租户新分类调用 `reconcile_system_owned_resources`（规格同 `acopy_root_builtin_tools_to_tenant` 末尾）；多租户开启时对每个已有子租户调用 `acopy_root_builtin_tools_to_tenant`，单个租户失败只记日志（design 决策 8）。
  **测试**: T013 全部通过
  **覆盖 AC**: AC-01, AC-26
  **依赖**: T013

### Wave 3 — 前端

- [ ] **T015**: Platform 设置表单
  **文件**: `src/frontend/platform/src/pages/BuildPage/tools/builtInTool/WebFetchForm.tsx`（新）, `src/frontend/platform/src/pages/BuildPage/tools/ToolSet.tsx`, `src/frontend/platform/src/pages/BuildPage/tools/index.tsx`, `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json`
  **逻辑**: 表单含引擎选择（DeepSeek）、API Key（必填、password）、Base URL（选填，占位提示默认地址）、正文长度上限（默认 20000，1000～200000 校验）；提交 `{type, config, max_chars}`。`ToolSet` 按分类名「网页读取」分派，`MANAGED_TOOLS` 加入该名。新文案三语齐全，不新增 `any`。
  **覆盖 AC**: AC-02, AC-03, AC-06, AC-25
  **手动验证**: 超级管理员打开 构建 → 工具 → 内置工具 →「网页读取」→ 设置；不填 API Key 提交出现必填提示；长度上限填 500 出现范围提示；保存后重新打开，秘钥显示为掩码，其他字段回显；联网搜索设置不受影响。
  **依赖**: T001

- [ ] **T016**: Client 调用展示
  **文件**: `src/frontend/client/src/components/Chat/Messages/ToolCallDisplay.tsx`, `src/frontend/client/src/components/Linsight/Execution/ToolRowLite.tsx`, `src/frontend/client/src/components/Linsight/Execution/activity.ts`, `src/frontend/client/src/components/Linsight/Execution/execTokens.ts`, `src/frontend/client/src/locales/{zh-Hans,en,ja}/translation.json`
  **逻辑**: `BUILTIN_TOOL_I18N` 加 `web_fetch`，网页条目显示网页标题和站点图标；任务模式动作文案「已读取网页」、统计分类「读取 N 个网页」。`ToolRowLite` 的动作文案表含遗留中文，按仓库规则一并抽到 i18n。
  **覆盖 AC**: AC-23, AC-24, AC-25
  **手动验证**: 日常模式勾选网页读取并提问，工具卡片名称为「网页读取」并显示网页标题；任务模式步骤显示「已读取网页」，头部统计含「读取 1 个网页」；切换英文和日文界面文案正确。
  **依赖**: T010, T012

### Wave 4 — 联调与验收

- [ ] **T017**: 真实接口自测
  **文件**: 无（临时脚本放 scratchpad）
  **逻辑**: 用环境变量 `DEEPSEEK_API_KEY`，经 `load_tools` → 包装层 → 标注全链路，跑 design §7 的三个参考网址，记录成功、站点拒绝、截断三种结果。
  **覆盖 AC**: AC-07, AC-08, AC-09, AC-11, AC-19
  **依赖**: T003, T005

- [ ] **T018**: 端到端验收
  **文件**: `/e2e-test features/v3.0.0/085-web-fetch` 生成的测试与验证清单
  **逻辑**: 按 AC 生成 API 测试和页面清单，重点覆盖角标卡片、点击跳转、联网搜索与网页读取混合引用、历史回放。部署到共享环境前先征得用户同意。
  **覆盖 AC**: AC-14, AC-15, AC-17, AC-18, AC-20, AC-21, AC-22, AC-24
  **依赖**: T007, T008, T010, T012, T014, T015, T016

---

## 实际偏差记录

- T005 偏离 → 网页读取条目的 itemId 用 `page` 而不是 `1`，句柄身份区分 `web:` / `webpage:`，更新 design 决策 3、新增坑 12（同网址的搜索结果和网页读取在短句柄模式下会被合并）
- T014 偏离 → 投影和子租户复制改为每次启动补缺口、失败只记日志，更新 design 决策 8、新增坑 13
