# Design: 网页读取内置工具

> 本文是现状快照 + 关键决策。需求口径见 [spec.md](./spec.md)，执行流水见 [tasks.md](./tasks.md)。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)
**版本**: v3.0.0
**最后更新**: 2026-10-19

---

## 1. 目标与非目标

- **目标**：新增一个独立的预置内置工具「网页读取」（`tool_key = web_fetch`，参数 `url`）。它和「联网搜索」并列：管理员在内置工具设置里单独配置，搭建者在各场景勾选，agent 调用后拿到一个网页的标题和 Markdown 正文。每次成功读取的网页注册为一个网页类引用来源，复用现有网页角标的卡片、跳转和历史回放。
- **非目标**：不改联网搜索的行为和配置；不做 DeepSeek 以外的读取引擎（只预留注册点）；不由平台服务器直接抓网页；不改现有 API 工具（`jina_get_markdown`、Firecrawl）。

---

## 2. 关键约束

- 架构铁律遵循 `docs/constitution.md` C1–C8。本功能涉及的具体点：两张工具表按租户隔离（C3）；工具能否被列出和执行走 F048 权限投影（C4）；秘钥不写进代码（C6）；新增插入只用 ORM，不写方言 SQL（C2）。
- **上游接口**：DeepSeek Fetch `POST https://api.deepseek.com/v1/tools/fetch`，Bearer 鉴权，请求体 `{"url": ...}`，成功返回 `{"title", "content"}`，失败返回 OpenAI 兼容错误体。2026-10-19 实测的接口行为见 §5 第 1～4 条。
- **工具表的组织方式**：一个内置工具 = 一行工具分类（`t_gpts_tools_type`）+ 若干行工具（`t_gpts_tools`）。配置存在分类行的 `extra` 上。执行时 `ToolExecutor` 一行工具只生成一个 `BaseTool`。
- **升级要求**：spec AC-01 要求老环境升级后不需要手工操作。老环境的工具表已有数据，种子 JSON 不会再导入，必须走启动时补数据的路径。补进来的工具还要有权限投影，否则非超级管理员列不出、也执行不了。
- **部署形态**：默认多节点（多个 backend 进程 + Celery worker）。启动补数据只能在拿到 `init_default_data` 的 Redis 锁的那个进程里执行。

---

## 3. 方案对比与选定

### 决策 1：独立内置工具，而不是随联网搜索引擎附带

- **备选**：
  - A. 联网搜索选 DeepSeek 引擎时，`load_tools` 额外返回一个 fetch 工具。
  - B. 新建独立的内置工具分类和工具行。
- **选定**：B
- **原因**：方案 A 下，工具能力随搜索引擎切换出现或消失，管理员看不到也控制不了。而且 `ToolExecutor._init_preset_tool` 只取 `load_tools` 返回的第一个工具，多返回的工具会被静默丢弃，要让它生效就得改所有场景的工具加载链路。方案 B 沿用「一行工具对应一个 BaseTool」的现有约定，权限、勾选、运行日志都能直接复用。用户已在 Spec Discovery 中确认。
- **何时该重新考虑**：如果以后要求「一个配置项产出一组工具」成为普遍需求，再统一改造 `ToolExecutor`，不要为单个工具开特例。

### 决策 2：读取引擎按搜索引擎的同款结构抽象

- **备选**：
  - A. 只写一个 DeepSeek 实现，配置扁平存 `{api_key, base_url}`。
  - B. 照搬 `SearchTool` 的结构：引擎基类 + 按 `type` 注册的实现类；配置存 `{type, config: {<engine>: {...}}, max_chars}`。
- **选定**：B
- **原因**：spec 要求以后能接其他引擎。B 和联网搜索的配置形状一致，前端表单和后端分派都能对照现有代码写；以后加引擎只需新增一个类、一个注册项和一个表单分支，存量配置不用迁移。
- **何时该重新考虑**：某个新引擎的配置无法按「引擎名 → 字段」分组表达时（例如需要按租户动态换取令牌），再调整配置结构，并为存量配置写迁移。

### 决策 3：引用来源用 WEB 类型，不用 ARTICLE

- **备选**：
  - A. `CitationType.WEB`，一个来源只有一个条目：`itemId="page"`（与搜索摘要的 `1`、`2`… 区分，见坑 12），`snippet` 取正文开头，`title` 取网页标题，`source` 取站点名。
  - B. `CitationType.ARTICLE`（频道文章就是「整篇一个来源」）。
- **选定**：A
- **原因**：ARTICLE 是频道专用类型，必填 `articleDocId`。它没有站点名字段，platform 前端没有 article 分支（会落到文档预览），分享页匿名访问时还会被拒。WEB 的卡片、点击跳转原网页、分享页匿名解析、历史回放全部现成，前端不用改。
- **何时该重新考虑**：如果卡片需要展示「整页正文」而不只是开头摘要，再考虑新增引用类型。

### 决策 4：同一网址多次读取共用一个来源，去重表跟随工具实例

- **备选**：
  - A. 每次调用都生成新的引用 ID（与联网搜索现状一致）。
  - B. 在每个场景的「单次回答收集器」上加「网址 → 引用 ID」表。
  - C. 在网页读取工具的引用包装实例上缓存「规范化网址 → 已生成的注册条目」。重复读取时复用同一个 ID，并把同一批注册条目再交给当前的收集器和运行时缓存一次。
- **选定**：C
- **原因**：spec §3 要求同一回答里多次读取同一网址时共用一个来源。B 要改四个场景各自不同的收集器结构（助手、工作流、日常模式、任务模式的 scope 都不一样），改动面大。C 只改网页读取自己的包装层，四个场景共用一份逻辑。包装实例的生命周期已核实：助手的 agent 每个会话建一次（`common/chat/client.py:222`），跨多轮有效；工作流 agent 节点每次运行建一次；日常模式每次请求建一次（`chat_service.py:1239`）；任务模式每个任务建一次。因此去重范围至少覆盖一次回答，最多覆盖一个会话，不会跨用户或跨会话。复用时重新交出注册条目，保证每条消息的持久化里都有这个来源，历史回放按消息加载时不会缺。
- **范围说明**：只对网页读取之间去重。联网搜索结果和网页读取的同一网址仍是两个来源，因为两者的摘要内容不同，合并后卡片会对不上模型实际引用的文字（spec AC-21）。
- **何时该重新考虑**：如果联网搜索也要做跨调用去重，再统一上收到各场景的收集器（方案 B）。

### 决策 5：引用包装层统一按工具名识别，并改为透传参数

- **备选**：
  - A. 为网页读取在每个场景各写一个新的包装类。
  - B. 抽出共享的识别函数 `is_web_citation_tool`（覆盖 `web_search` 和 `web_fetch`），现有包装类的 `_run/_arun` 改为接收 `**kwargs` 并原样转给内层工具，再按工具名选择标注方式：列表结果走联网搜索的标注，单个网页对象走网页读取的标注。
- **选定**：B
- **原因**：助手、工作流 agent、日常模式的包装层现在写死 `invoke({"query": query})`，网页读取的参数是 `url`，不改这一处无论哪个方案都跑不通。任务模式的包装层已经是透传写法，B 让其余三处与它对齐。五处 `_is_web_search_tool` 副本也借机收拢成一个函数，避免下次再漏。
- **何时该重新考虑**：无。

### 决策 6：正文后处理在工具内完成——去转义、截断、空正文

- **备选**：
  - A. 不做后处理，原样交给模型和卡片。
  - B. 在前端卡片渲染时去转义，后端只截断。
  - C. 在工具内、引用标注之前统一做去转义、截断和空正文判断；截断按字符数计。
  - D. 同 C，但截断按 token 数计。
- **选定**：C，具体规则：
  - **去转义**：把「反斜杠 + 非字母数字字符」以及 `\_` 还原为该字符（DeepSeek 也转义下划线）；以 ``` 包围的代码块内保持原样。
  - **截断**：按字符数截断，上限取管理员配置值，默认 20000，允许范围 1000～200000。截断后在结果里给出 `truncated=true` 和原文总长度，并附一句提示让模型知道内容不完整。
  - **空正文**：返回「该网页没有可读正文」的提示，不生成引用标识。
- **原因**：实测 DeepSeek 几乎给每个标点加反斜杠（GitHub 页 429 处，Python 文档页 6574 处），白白占用 token，还会原样出现在角标卡片里。正文长度没有上限（实测 13 万字），不截断会撑满上下文。这些都是引擎特性，放在引擎实现之后、引用标注之前统一处理，所有场景和以后的引擎都受益。
- **为什么不选 B 和 D**：B 只修了卡片，模型仍然读到带反斜杠的正文，token 照样浪费。D 要知道调用方模型的分词器，工具层拿不到，而且管理员配置「字数」比配置「token 数」直观。
- **何时该重新考虑**：如果 DeepSeek 修正了转义行为，去转义步骤可以保留（对未转义文本无副作用）。如果出现大量「截断后信息不够」的反馈，再考虑分段读取（带 offset 参数）。

### 决策 7：未配置和调用失败不抛异常，返回文字给模型

- **备选**：
  - A. 必填配置缺失时让 `load_tools` 抛 `ValueError`（联网搜索现状）。
  - B. 工具总能被构建；调用时再检查配置，未配置、网址不合法、引擎报错都以文字结果返回给模型。
- **选定**：B
- **原因**：spec AC-11、AC-13 要求对话或任务继续执行。方案 A 在日常模式会变成一条失败记录、工具消失；在任务模式里异常会中断运行（`agent_factory.py` 包装层注释说明了这一点）。B 让模型自己决定换一个网址、改用搜索或者如实告诉用户。
- **何时该重新考虑**：无。

### 决策 8：老环境升级在启动时补行、投影权限、复制到已有子租户

- **备选**：
  - A. 只改种子 JSON。
  - B. 照 `_ensure_image_view_tool` 在启动时补根租户的分类行和工具行，只做这一步。
  - C. 在 B 的基础上，仅当本次新插入了行时：（1）为根租户的新分类做 F048 系统资源权限投影；（2）多租户开启时，对每个已有子租户调用 `acopy_root_builtin_tools_to_tenant`。
  - D. 在 B 的基础上，每次启动都执行一次「补缺口」：OpenFGA 开启时为根租户分类补投影（只写缺失的投影）；多租户开启时只对还没有 `web_fetch` 行的活跃子租户执行复制。每一步失败只记日志。
- **选定**：D（种子 JSON 也同步加上，供全新安装使用；补数据函数从种子 JSON 读取字段）
- **原因**：A 对老环境无效。B 的做法对 Image View 够用，是因为 Image View 按 tool_key 直接读取、不经过权限检查；网页读取走 `ToolExecutor`，执行前要检查使用权限，缺投影时非超级管理员用不了（spec AC-26）。已有子租户只在缺少默认工具时才会懒复制，网页读取不在默认工具里，不主动复制就永远不会出现在子租户中。复制函数本身幂等，并会为子租户的分类做投影。不选 C 是因为它只在插入的那一次启动尝试投影和复制，如果那次 OpenFGA 未就绪或某个租户复制失败，以后再也不会重试；而 `init_default_data` 里任何未捕获的异常都会让后端启动失败，所以这些步骤必须吞掉异常、下次启动再补。根租户投影复用全新安装用的系统资源清单（`load_system_owned_resource_inventory`）生成的规格，保证与全新安装的投影一致。
- **何时该重新考虑**：如果平台以后提供「预置工具版本化同步」的统一机制，把本步骤迁过去。

### 决策 9：任务模式和提示词把网页读取当作网页来源

- **备选**：
  - A. 不改任务模式的 `has_web` 判断，只勾网页读取时不开启引用规则。
  - B. 为网页读取单独写一套引用提示词。
  - C. `has_web` 改用共享识别函数，并在现有引用提示词里补一句网页读取结果。
- **选定**：C。具体做法：任务模式中判断「是否有网页来源」的三处 `has_web`（研究员提示、主图引用中间件、研究员可引用标记）改用共享识别函数。`citation.yaml` 和 `citation_handles.yaml` 的说明补上「网页读取结果」。
- **原因**：任务模式目前只在有联网搜索时才开启引用规则，只勾网页读取时模型拿不到规则，spec AC-19 不成立，所以 A 不行。网页读取的引用标识格式和联网搜索完全相同（都是 WEB 类型的 key 或短句柄），单独写一套提示词（B）只会增加两套文字不一致的风险。助手和工作流 agent 现状不注入引用规则（依赖搭建者自己的提示词），本 feature 保持一致，不新增注入。
- **何时该重新考虑**：助手和工作流将来统一注入引用规则时，一并覆盖网页读取。

---

## 4. 系统现状（接手必读）

### 4.1 数据流

**配置**：管理员打开内置工具「网页读取」的设置 → `ToolSet.tsx` 按子工具 `tool_key` 分派到 `WebFetchForm` → `POST /api/v1/tool/config` → `ToolServices.update_tool_config` 合并掩码后写分类行 `extra`。

**执行**（以助手为例，其他场景相同，只是包装类不同）：
1. `ToolExecutor` 读分类 `extra` → `load_tools({"web_fetch": extra})` → `_get_web_fetch` → `FetchTool.init_fetch_tool(type, **engine_config)` → `WebFetchTool(api_wrapper=..., max_chars=...)`，工具名 `web_fetch`。
2. 场景的引用包装层用 `is_web_citation_tool` 识别出它，包上引用逻辑。
3. agent 调用 → 包装层把 `{"url": ...}` 透传给 `WebFetchTool` → 校验网址 → 引擎请求 → 去转义 → 截断 → 返回网页对象。
4. 包装层调用 `annotate_fetched_page_with_citation`：命中去重表就复用，否则生成一个 WEB 注册条目 → 把 `citation_key` 写进结果 → 注册条目交给收集器和运行时缓存。日常模式和任务模式的短句柄模式再把 key 改写为 `[Sn]` 形式的 `ref`。
5. 回答结束时各场景按原路径持久化引用；前端按 WEB 类型渲染卡片。
6. 调用展示：助手运行日志标题按 `tool_key` 在助手配置的工具列表里查到「网页读取」，展开后显示调用输入（含网址）和输出原文，所以运行日志不用改。日常模式由 `_build_tool_meta` 把 `web_fetch` 标为 `web` 类型，前端用网页条目展示网页标题和站点图标，名称走 `BUILTIN_TOOL_I18N`。任务模式在 `ToolRowLite` 的动作文案和 `activity.ts` 的统计分类里新增网页读取。

**升级**：`init_default_data`（持有 Redis 锁）→ `_ensure_web_fetch_tool` 按种子 JSON 插入根租户行（已存在则跳过）→ OpenFGA 收尾步骤之后执行 `_sync_web_fetch_tool`：OpenFGA 开启时 `_project_root_web_fetch_tool` 补根分类投影；多租户开启时 `_tenants_missing_web_fetch_tool` 找出缺少该工具的活跃子租户，逐个执行 `acopy_root_builtin_tools_to_tenant`。每一步失败只记日志，下次启动再补。

### 4.2 关键数据结构 / 字段约定

| 字段 / 结构 | 类型 / 格式 | 说明 | 谁会消费 |
|---|---|---|---|
| 分类名 | `网页读取` | 与 `联网搜索` 一样用中文存库，前端按名字分派设置表单 | `ToolSet.tsx`、`tools/index.tsx` 的 `MANAGED_TOOLS`、子租户复制（按名字匹配） |
| 工具 `tool_key` | `web_fetch` | 也是运行时 `BaseTool.name` | `load_tools` 注册表、引用识别、助手运行日志、前端工具卡片 |
| 工具 `api_params` | `[{"name":"url","in":"query","required":true,"schema":{"type":"string"}}]` | 工作流工具节点据此渲染输入框 | `flowUtils.ts` |
| 分类 `extra` | `{"type":"deepseek","config":{"deepseek":{"api_key":"","base_url":""}},"max_chars":20000}` | 秘钥字段名必须叫 `api_key`，才能被现有掩码逻辑覆盖 | `ToolExecutor`、设置表单 |
| 工具结果（给模型） | JSON 对象 `{"title","url","source","content","truncated","total_chars","citation_key"}` | 失败或未配置时是一段文字而不是 JSON | 模型、日常模式工具卡片（按 `url`/`title` 显示网页条目） |
| 引用条目 | WEB 类型，单条目 `itemId="page"`，key 形如 `websearch_xxxxxxxx:page`；卡片摘要是去掉 Markdown 标记和标题行后的正文开头，最多 300 字 | 沿用 `websearch_` 前缀，前端、解析服务、持久化都按 WEB 处理 | 引用解析、卡片、历史回放 |

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `bisheng_langchain/gpts/tools/web_fetch/tool.py`（新） | `FetchTool` 引擎基类与注册表、`DeepSeekFetch`、`WebFetchTool`；网址校验、去转义、截断 | 不做引用标注 |
| `bisheng_langchain/gpts/load_tools.py` | 注册 `web_fetch` → `_get_web_fetch` | — |
| `bisheng/citation/domain/services/citation_prompt_helper.py` | 新增 `is_web_citation_tool`、`annotate_fetched_page_with_citation` | 不关心是哪个场景 |
| 各场景包装层：`assistant_agent.py`、`workflow/nodes/agent/agent.py`、`workflow/nodes/tool/tool.py`、`workstation/.../chat_service.py`、`linsight/.../agent_factory.py` | 识别网页读取、透传参数、调用标注、交出注册条目 | 不各自实现标注逻辑 |
| `bisheng/citation/domain/services/citation_handle_service.py` | `rewrite_web_results_with_handles`、`drop_web_citation_keys` 除列表外也接受单个网页对象（日常模式和任务模式的短句柄） | 不分配句柄以外的事 |
| `bisheng/common/init_data.py` | `_ensure_web_fetch_tool` 及升级后的投影和子租户复制 | — |
| platform `tools/builtInTool/WebFetchForm.tsx`（新） | 引擎选择、秘钥、Base URL、长度上限的表单与校验 | — |
| client `ToolCallDisplay.tsx`、`Linsight/Execution/*` | 网页读取的本地化名称、网页条目展示、任务模式动作文案与统计分类 | — |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | DeepSeek Fetch 返回的 Markdown 给几乎每个标点加反斜杠（`\#`、`\-`、`\,`） | token 浪费，卡片显示一堆反斜杠 | 决策 6，去转义 |
| 2 | 正文没有长度上限，一页可达 13 万字 | 一次调用撑满上下文 | 决策 6，截断 |
| 3 | 部分站点整体拒绝抓取（实测维基百科中英文都返回 `not_found_error: failed to fetch URL`），需要执行 JS 的页面只返回一段占位提示 | 误以为是我们的 bug | 失败如实返回模型；占位提示按正文原样返回，不伪造内容 |
| 4 | 单次请求耗时 5～12 秒 | 超时设太短会大量失败 | 超时取 (10, 60) 秒，与联网搜索一致 |
| 5 | `ToolExecutor._init_preset_tool` 只取 `load_tools` 返回的第一个工具 | 想「一个配置出两个工具」会被静默丢弃 | 决策 1 |
| 6 | 助手、工作流 agent、日常模式的引用包装层写死 `invoke({"query": query})` | 网页读取收到错误参数，调用失败 | 决策 5，透传参数 |
| 7 | `_ensure_image_view_tool` 不做权限投影，Image View 不受影响只是因为它不经过权限检查 | 照抄后，非超级管理员在老环境里列不出、用不了网页读取 | 决策 8 |
| 8 | 子租户只在缺少默认工具时懒复制根租户的预置工具 | 老环境的已有子租户永远看不到网页读取 | 决策 8，升级时主动复制 |
| 13 | `init_default_data` 里任何未捕获的异常都会让后端启动失败（外层 `raise RuntimeError`） | 补投影或复制子租户时 OpenFGA 未就绪，整个后端起不来 | `_sync_web_fetch_tool` 逐步 `try/except` 只记日志 |
| 14 | `test/sandbox/test_code_interpreter_seed_default.py` 用 AST 禁止 `init_data.py` 出现任何 `extra=` 关键字参数，但它的本意是「升级时不改已有行的 extra」；主线上该测试已因 `_ensure_image_view_tool` 失败 | 误以为是本 feature 引入的回归 | 本 feature 的插入只写新行；该测试的误报留给其维护方处理 |
| 9 | 旧工具的设置弹窗和 `MANAGED_TOOLS` 按分类的中文名匹配，子租户复制也按名字匹配；在 platform 源码里新增中文字面量会让文件超出 lint 冻结配额 | 设置按钮不出现；lint 失败；子租户复制出重复分类 | 前端改按子工具 `tool_key = web_fetch` 识别（`tools/index.tsx` 的 `hasManagedToolKey`、`ToolSet.tsx`）；分类名只在种子 JSON 里定义一次，补数据函数从种子读取 |
| 10 | 只有 `api_key` 等固定字段名会被掩码 | 换个字段名，秘钥会明文返回给前端 | 配置字段名固定为 `api_key` |
| 12 | 短句柄（日常模式、任务模式）按「来源身份」分配，网页类来源的身份原本只看网址 | 同一网址的搜索结果和网页读取拿到同一个句柄，模型引用全文内容时卡片显示的是搜索摘要 | `citation_handle_service.item_identity`：`itemId == "page"` 时身份为 `webpage:<网址>` |
| 11 | 任务模式的引用规则只在 `has_web` 为真时开启，原判断只认 `web_search` | 只勾网页读取时模型不会打角标 | 决策 9 |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| 内置工具 `web_fetch`（参数 `url`） | 工具表数据 + `load_tools` 注册项 | 助手、工作流、日常模式、任务模式 |
| 分类 `extra` 配置形状 | JSON | platform 设置表单、子租户复制 |
| `is_web_citation_tool(tool)` | 内部 Python API | 五个场景的引用包装层 |
| `annotate_fetched_page_with_citation(...)` | 内部 Python API | 五个场景的引用包装层 |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| DeepSeek Fetch 接口 | 外部 HTTP API | 转义、长度、站点封禁等行为可能变化；错误体格式变化会影响失败原因的文字 |
| WEB 引用类型的解析、卡片和持久化（F069、F072） | 内部数据契约 | 若 WEB 负载字段改名，网页读取的卡片会缺字段 |
| `ToolServices.update_tool_config` 的掩码合并 | 内部行为 | 改动掩码规则会影响秘钥保存 |
| `acopy_root_builtin_tools_to_tenant` 按名字匹配分类 | 内部行为 | 匹配规则改变会导致子租户重复或缺失 |
| F048 系统资源投影（`reconcile_system_owned_resources`） | 内部 API | OpenFGA 未就绪时升级投影失败，需重启或跑对账脚本 |

---

## 7. 测试与可观测

- **单元测试**：引擎实现（请求参数、错误体解析、超时）、去转义（含代码块）、截断边界（等于上限不截断）、网址校验、未配置；引用标注（单条目、去重复用、空正文不注册）；五个包装层的识别和参数透传；`_ensure_web_fetch_tool` 的幂等。放在 `test/tool/` 和 `test/citation/`。
- **真实接口自测**：用本地环境变量 `DEEPSEEK_API_KEY` 走 `load_tools` → 调用 → 标注全链路，覆盖成功、站点拒绝、超长截断三种网页。三个参考网址：`https://github.com/dataelement/bisheng`（成功，含大量转义）、`https://en.wikipedia.org/wiki/Taiwan`（站点拒绝）、`https://docs.python.org/3/whatsnew/3.14.html`（约 13 万字，触发截断）。
- **手动验证一遍**：
  1. 在 `src/backend` 下执行 `env -u ALL_PROXY -u all_proxy .venv/bin/python -m pytest -q test/tool test/citation`（本地需清掉 SOCKS 代理变量，否则整批误报）。
  2. 以超级管理员登录 platform → 构建 → 工具 → 内置工具 →「网页读取」→ 设置，选 DeepSeek 并填秘钥。
  3. 新建助手，勾选「网页读取」，提问「读一下 https://github.com/dataelement/bisheng 并总结」，确认运行日志标题、回答角标、角标卡片和点击跳转。
  4. 刷新页面重新打开该会话，确认角标卡片仍可显示。
  5. 在工作台配置里把「网页读取」加入日常模式和任务模式的可用工具，在 client 各发一次同样的问题，确认工具卡片和任务步骤的名称是「网页读取」。
- **端到端**：`/e2e-test` 按 AC 生成 API 测试和页面验证清单。页面重点看设置弹窗、日常模式工具卡片、任务模式步骤、角标卡片和历史回放。
- **可观测**：引擎失败用 `logger.warning` 记录网址和 DeepSeek 返回的 `request_id`，便于向 DeepSeek 反馈。

---

## 8. 后续改进 / 不打算做的事

- 接入 Jina Reader 等其他读取引擎：新增引擎类、注册项和表单分支即可。
- 自建抓取引擎时必须加内网地址拦截（防 SSRF）。第一期由 DeepSeek 服务端抓取，平台不访问目标网址，所以暂不需要。
- 联网搜索的跨调用去重：见决策 4 的「何时该重新考虑」。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-10-19 | 初版 | spec 确认后进入设计 |
