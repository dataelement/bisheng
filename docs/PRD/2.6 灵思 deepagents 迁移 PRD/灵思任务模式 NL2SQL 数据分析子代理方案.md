# 深度研究（任务模式）NL2SQL 数据分析子代理方案

> **定位**：v3.1 · 深度研究（任务模式，内部代号 Linsight）在"问数/NL2SQL"场景的效果增强，轻量方案
> **归属**：F035-linsight-task-mode 域内增强，不新增领域对象
> **落地入口**：`src/backend/bisheng/linsight/domain/services/agent_factory.py` + 代码执行器工具描述 + 技能编写约定
> **代码基准**：本文所有 `文件:行号` 以 `feat/3.1.0-beta1` HEAD `1b64bb4f52`（2026-11-09）为准；deepagents 版本为 0.6.12
> **关联**：[灵思 Linsight 迁移 deepagents 框架 PRD](./灵思%20Linsight%20迁移%20deepagents%20框架%20PRD.md) · [灵思任务模式 #1 子代理重引入技术方案](./灵思任务模式%20%231%20子代理重引入技术方案.md) · [灵思任务模式 Skill 能力恢复方案](./灵思任务模式%20Skill%20能力恢复方案.md)

---

## 修订记录

| 日期 | 版本 | 说明 |
|---|---|---|
| 2026-09 | v1（v2.6 定位） | 初版，已 approve，未实现 |
| 2026-11-10 | v2（v3.1 定位） | 按 3.1 代码逐条重审，见下文"v1 → v2 变更" |
| 2026-11-11 | v2.1（已实现） | F013 实现、114 E2E 与 code review 后的回写，见文末"附录 B：实现与验证回写" |

**v1 → v2 变更**（只列改变结论的条目，逐条核对依据见附录 A）：

1. **技能接线改为"委派时点名路径"**。v1 要在子代理上手挂 SkillsMiddleware。v2 不挂：10-23 起主图已挂载租户内全部技能，主图负责选出数据库技能，并在委派 description 里写明 `/skills/<name>/SKILL.md`。
2. **子代理描述不会自动进主 prompt**。v1 说 deepagents 会把子代理 description 冒泡进主图 system prompt。0.6.12 只把它写进 `task` 工具描述。主 prompt 必须显式加一行 data-analyst 委派指引。
3. **工具改为 allow-list**。v1 复用 researcher 的 deny-list（`_subagent_tools`）。v2 只给代码执行器和框架文件工具，并且只在绑定了代码执行器时才装配 data-analyst。
4. **新增执行边界例外**。主 prompt 和代码执行器工具描述现在都禁止"连接平台的数据库"。v2 在两处同时加例外：技能提供的外部业务库可以连接。
5. **新增"顶层文件陷阱"**。代码执行器会把写到工作目录顶层的新文件自动移进 `output/`，`output/` 会被收割为交付物。v2 要求子代理代码显式写 `scratch/` 路径。
6. **去掉「整会话最多澄清一轮」上限**。改为由模型判断是否有必要提问：确有必要就问，否则采用假设继续，不打扰用户（2026-11-10 拍板）。
7. **新增无人值守降级**。Open API 无人值守运行没有 ask_user。v2 规定此时主图收到 NEED_CLARIFICATION 必须带显式假设继续。
8. **凭据风险升级并记录**。企业技能现在挂进租户内每个会话，连接串对租户内全员可读。按 2026-11-10 拍板，允许企业技能写凭据，作为已知风险记录。
9. **中间件栈复用 F087 之后的完整栈**，抽公共函数，两个子代理共用。

---

## 一、结论先行

在深度研究上**新增一个只读的 `data-analyst` 子代理**，用于"用自然语言查业务库、产出数据和图表"。

- **数据库访问不建基础设施**。连接信息写在技能（skill）正文里，这是 Tier B 路线。
- **主图选技能，子代理读技能**。主图从已挂载的技能列表里选出数据库技能，把技能路径写进委派 description；子代理用 `read_file` 读 SKILL.md，拿到连接信息和领域知识。
- **子代理在代码执行器里跑 SQL**。子代理产出数据文件、图表和 SQL，主图负责拼装最终交付物。
- **歧义走澄清环**。子代理返回 `NEED_CLARIFICATION:`，主图判断有必要时调 `ask_user`，再重新委派。澄清不设次数上限，由模型判断是否值得打扰用户。这条链路代码已经现成，只改 prompt。

改动面是：`agent_factory.py`（子代理装配、公共中间件函数、主 prompt、子代理 prompt）、代码执行器工具描述里的一句例外、技能编写约定。不加新工具，不改 DB schema，不改前端。

---

## 二、背景与约束

**需求**：用户用自然语言问业务库，深度研究产出带数据与图表的报告。

**已定路线（Tier B）**：短期不建独立数据源模块，连接信息留在技能里。数据源表、Fernet 加密、OpenFGA 权限、CRUD、管理页、工作流节点统一连接，整体推后为债。

**现有能力（均可复用）**：

| 能力 | 位置 |
|---|---|
| deepagents 装配、researcher 子代理 | `agent_factory.py:1163-1200`、`:1607-1680` |
| 子代理中间件栈（压缩、容错、防循环、二进制守卫、结果预算、调用修复） | `agent_factory.py:1610-1637` |
| 子代理上下文溢出兜底（包在 `task` 工具外，对所有子代理生效） | `resilience_middleware.py:898`，挂载于 `agent_factory.py:1503` |
| 代码执行器（local / container / e2b，默认 uid 隔离） | `bisheng_langchain/gpts/tools/code_interpreter/`，任务模式装配在 `workbench_impl.py:2358-2412` |
| ask_user → interrupt → park-and-release → resume | 见 §3.3 |
| 交付物收割（优先 `output/`，`scratch/` 永不收割） | `domain/utils.py:118`、`:436` |

**五条硬约束**：

1. **子代理不能问用户**。子代理没有 ask_user，也没有中断源，只能用 `NEED_CLARIFICATION:` 返回给主图。
2. **委派必须自包含**。deepagents 把子代理的 messages 替换成只有 `[HumanMessage(description)]`（`deepagents/middleware/subagents.py:663-665`）。子代理需要的问题、技能路径、口径都必须写进 description（`linsight/AGENTS.md:28`）。
3. **prompt 与工具同步**。prompt 提到某个工具或子代理，当且仅当它真的被装配（`linsight/AGENTS.md:26`）。
4. **无人值守模式没有 ask_user**（`agent_factory.py:1444`）。澄清环在该模式下必须降级。
5. **代码执行器自动收割顶层文件**。执行器把运行中新建在工作目录顶层的文件移进 `output/`（`base_executor.py:292`），`output/` 里的新文件会成为交付物。

---

## 三、方案设计

### 3.1 容器：`data-analyst` 子代理

**装配条件**：只在 `has_code_interpreter` 为真时装配（`agent_factory.py:1480` 已计算）。没有代码执行器，子代理就连不了库，装配它只会误导主图。

**定义**：新增 `_build_data_analyst_subagent(...)`，与 `_build_researcher_subagent` 并列，返回：

- `name = "data-analyst"`。
- `description`：用于连接业务数据库查询数据、做统计分析和出图；需要调用方在描述里给出技能路径；不能向用户提问，不负责最终交付物。
- `system_prompt`：见 §3.6 的 prompt 要点。
- `tools`：**allow-list**，只保留 `bisheng_code_interpreter`。框架文件工具（`read_file`、`write_file`、`ls`、`glob`、`grep`）由 deepagents 的 FilesystemMiddleware 自带。researcher 的 deny-list 会把知识库检索、联网等工具也交给子代理，这会分散数据任务的注意力。

**中间件栈**：把 `agent_factory.py:1610-1637` 抽成公共函数 `_subagent_middleware(...)`，两个子代理共用。顺序保持不变：summarization → resilience（`is_subagent=True`，每个子代理一个实例）→ tool-loop breaker → binary guards → result budget → LanguageTail → invalid-call repair（必须在最后，`linsight/AGENTS.md:32`）。data-analyst 不挂 F069 引用相关的两层，因为数据查询结果没有引用句柄。

**主 prompt**：在第 2 步执行段（`agent_factory.py:136` 附近）和工具清单段（`:181` 附近）各加一行 data-analyst 的委派指引。这两行用占位符生成，只在装配了 data-analyst 时出现。

### 3.2 内容：主图点名技能路径，子代理按路径读取

**做法**：

1. 主图的技能列表已经包含租户内全部启用的技能，并标注用户选中了哪些（`SkillSelectionMiddleware`，`agent_factory.py:1259`、`:1547-1553`）。
2. 主图判断问题需要查库时，从列表里选出数据库技能。
3. 主图在委派 description 里写明 `/skills/<name>/SKILL.md`。
4. 子代理用 `read_file` 读取该文件。读取走 WorkspaceBackend（本地缓存，MinIO 兜底），路径与主图一致。

**为什么不在子代理上挂技能中间件**：

- deepagents 原生 `skills=` 键仍然不可用。它使用共享的 WorkspaceBackend 枚举技能（`deepagents/graph.py:653-655`），而 `WorkspaceBackend.ls` 只返回对象、`is_dir` 恒为 False（`workspace_backend.py:927-958`），SkillsMiddleware 只认目录（`deepagents/middleware/skills.py:597-610`），结果是发现 0 个技能。
- 手挂 `LinsightSkillsMiddleware` 技术上可行，但会把全部技能的列表再塞进子代理上下文。子代理只需要一个技能，选择权在主图，主图点名即可。
- 点名做法符合约束 2：子代理需要的选项写进 description。

**技能里放什么**：连接信息（只读账号）、库表说明、业务口径、常用 SQL 示例。通用的 NL2SQL 方法（先探 schema、再写 SELECT、检查、执行、按报错修正）写进子代理 prompt，不做成技能。

### 3.3 澄清环：NEED_CLARIFICATION

**链路现成，不改业务代码**。各环节当前位置：

| 环节 | 位置 |
|---|---|
| 子代理最后一条消息冒泡为主图的 ToolMessage | `deepagents/middleware/subagents.py:600-637` |
| 主图调 `ask_user`，内部 `interrupt(...)` | `agent_factory.py:910-956` |
| 检测 `__interrupt__`，产出 NeedUserInput | `stream_event_mapper.py:287-313` |
| park：任务置 `WAITING_FOR_USER_INPUT`，释放 worker 槽位 | `task_exec.py:1873-1910`、`worker.py:151-157` |
| 用户提交答案 `POST /workbench/user-input` | `api/endpoints/linsight.py:420` |
| resume：`Command(resume=...)`，同 thread_id | `task_exec.py:442`、`:593` |

代码里没有限制 ask_user 次数。"整会话一次"只是 prompt 约束。

**返回契约**：子代理遇到靠查库和技能都无法消除的歧义（例如时间口径、多个同名指标、多表都能回答）时，最后一条消息只写 `NEED_CLARIFICATION:` 加问题列表，每个问题带 2-4 个候选项。能用合理默认值补齐的，子代理写明假设后继续，不返回 NEED_CLARIFICATION。

**主 prompt 要改的四处**：

| 位置 | 现文 | 改为 |
|---|---|---|
| `agent_factory.py:129` | 整个会话最多澄清一轮；用户回答后仍不明确也绝不第二次调用 ask_user | 删除轮数上限，改为判断原则（见下方"何时提问"） |
| `:130` | 所有澄清必须在创建任何 task 之前一次性问完 | 能在开工前确定的缺口，开工前一次问完；执行中才暴露的缺口（含子代理返回的 NEED_CLARIFICATION）可以在执行中问 |
| `:175` | ask_user：第 0 步澄清；整个会话最多调用一次 | ask_user：只在确有必要时调用，不限次数 |
| 新增 | — | 收到 NEED_CLARIFICATION 时，先按"何时提问"判断；需要问就转成 ask_user 的 questions，拿到答案后写进新的 description 重新委派；不需要问就选定假设重新委派。不得把 NEED_CLARIFICATION 当作最终答案 |

**何时提问（取代原"整会话一轮"上限，2026-11-10 拍板）**：不设澄清次数上限，由主图判断是否有必要打扰用户。判断原则写进主 prompt：

- **要问**：缺的信息只有用户知道，而且按默认假设做大概率做错，或者做错后返工代价大（例如口径不同会得出相反结论）。
- **不问**：能用合理默认值补齐、能从上下文或数据本身推断、或者做错代价小的，直接采用假设继续，在交付物里写明假设。
- **合并提问**：同一时刻有多个缺口，放进同一次 ask_user，不分多次问。
- **不重复问**：用户已经回答过的问题不再问；用户回答后仍有个别细节不明确，按默认假设推进。

这一条改的是主 prompt 的通用澄清规则，影响所有任务，不只数据任务。代码里本来就没有 ask_user 次数限制（见上表链路），所以只改 prompt。

**无人值守**：`_to_unattended_prompt`（`agent_factory.py:325`）删除澄清段落时，同时删除上述新增段落，替换为一句：收到 NEED_CLARIFICATION 时选择最合理的候选项作为假设，重新委派，并在交付物里写明假设。

### 3.4 委派契约与职责边界

**description 必须包含**：

1. 精确的问题。
2. 技能路径 `/skills/<name>/SKILL.md`。
3. 已知口径（时间范围、指标定义、用户在澄清中给出的答案）。
4. 允许的范围（哪些库表、是否需要出图）。
5. 中间产物目录 `scratch/<子任务短名>/`。

**职责边界不变**：主 prompt `agent_factory.py:148` 规定"最终交付物的撰写与拼装必须由主智能体亲自完成"。data-analyst 只返回数据、图表路径、关键发现和执行过的 SQL。主图按用户选择的格式拼装交付物：markdown 插入图表；HTML 由主图用数据渲染，`check_html` 只在主图上。

### 3.5 产物治理

- **中间产物写 `scratch/<子任务短名>/`**。代码里必须写这个显式路径。写到工作目录顶层的新文件会被执行器移进 `output/` 并收割为交付物（约束 5）。
- **结果集写成 CSV**，放在 scratch 目录下。代码只打印行数、列名和前若干行。单条工具结果超过可用输入的 10% 会被卸载到 `/large_tool_results/`（`context_budget.py:376`），需要时用 `read_file` 分页读，不重新执行同一查询。
- **进入交付物的最终图表写 `output/`**，数量节制。
- **返回里写明全部文件路径**。执行器同步到 MinIO 是 best-effort（`base_executor.py:462-500`），主图 `ls` 不一定能列出，按路径 `read_file` 更可靠。

### 3.6 执行边界与安全

**执行边界例外**：主 prompt（`agent_factory.py:494-501`）和执行器工具描述（`base_executor.py:104` 的 `EXECUTION_BOUNDARY_RULES`）现在都写着"不要连接平台的数据库、缓存、对象存储等内部服务"。模型可能因此拒绝连接业务库。两处必须同时加一句：技能中明确提供的外部业务数据库可以按技能说明连接；平台自身的数据库、缓存、对象存储仍不得连接。两处是同步孪生文本（`agent_factory.py:493` 注释），必须一起改。

**凭据放进技能的 `secrets/` 目录（v2.1 新增，见附录 B）**。口令等凭据不写在 SKILL.md 正文，单独放在 `skills/<技能名>/secrets/` 下；文件工具读不到这个目录，只有代码执行器里的代码能读。

**只读账号仍是数据库侧的唯一护栏**。技能里的连接必须用只读账号。模型生成 DML 或凭据外泄时，影响范围限于只读。

**企业技能凭据全员可读（已知风险，2026-11-10 拍板接受）**：

- 企业技能（`owner_user_id=0`）对租户内全员可见（`linsight_skill.py:337-347`）。
- 10-23 起任务模式把全部候选技能挂进每个会话（`skill_provisioning.py:151-191`）。
- 所以租户内任何用户都能 `read_file` 读到企业技能里的连接串，不需要选中该技能。
- 缓解建议：业务库给该只读账号加 IP 白名单，只放行 worker / 沙箱出口；需要按人隔离的库，用个人技能（只挂给上传者本人）。

**data-analyst prompt 要点**：

1. 先 `read_file` 读 description 指定的 SKILL.md，按其中的连接方式和口径工作。
2. 只执行 SELECT；禁止 INSERT / UPDATE / DELETE / DDL。
3. 先探 schema（表、列、样例行），再写查询；写完先检查再执行；按报错修正，同一失败不超过 3 次。
4. §3.5 的产物治理规则。
5. 主 prompt 里的代码执行器使用规则（`agent_factory.py:480-501`）。这段要抽成常量，主 prompt 和子代理 prompt 共用，避免漂移。
6. NEED_CLARIFICATION 返回契约（§3.3）。
7. 最后一条消息包含：结论、关键数字、执行过的 SQL、所有文件路径、所做的假设。

---

## 四、改动清单

| 文件 | 位置 | 改动 |
|---|---|---|
| `linsight/domain/services/agent_factory.py` | 常量区 | 新增 `_DATA_ANALYST_PROMPT_TEMPLATE_ZH`；把代码执行器使用规则抽成共用常量 |
| 同上 | `:1163` 旁 | 新增 `_build_data_analyst_subagent(tools)`，tools 用 allow-list |
| 同上 | `:1607-1637` | 抽 `_subagent_middleware(...)`；researcher 与 data-analyst 共用；data-analyst 不挂引用两层 |
| 同上 | `:1668` | `subagents=[researcher, *([data_analyst] if has_code_interpreter else [])]` |
| 同上 | `:129/:130/:136/:175/:181` | §3.1 委派指引（用占位符按装配情况生成）；§3.3 去掉澄清轮数上限，改为判断原则 |
| 同上 | `:325` `_to_unattended_prompt` | 无人值守降级文本 |
| 同上 | `:494-501` | 执行边界例外 |
| `bisheng_langchain/gpts/tools/code_interpreter/base_executor.py` | `:104` `EXECUTION_BOUNDARY_RULES` | 执行边界例外，与上一行同步 |
| 技能编写约定（文档） | — | 数据库技能写只读账号、库表说明、口径、示例 SQL |

**明确不动**：新工具、DB schema / 迁移、前端、数据源模块、researcher 的行为、工作流节点。前端子代理步骤按 `subagent_type` 原样显示名称（`client/src/components/Linsight/Execution/execTypes.ts:15`），"data-analyst" 会原样显示，与现在的 "general-purpose" 一致；按类型显示中文名记为可选优化。

**依赖**：

- 用户在配置里启用 `bisheng_code_interpreter`。
- 驱动已就绪：local 模式用后端 venv（`pyproject.toml` 含 pymysql>=1.1.2、pandas、sqlalchemy），沙箱镜像用同一份 `uv.lock`。
- 网络：代码里没有出网限制（local 模式无网络隔离；容器 Helm `denyEgress: false`）。能否连到业务库只取决于部署网络。

---

## 五、验收标准

| ID | 场景 | 预期 |
|---|---|---|
| AC-01 | 会话里有一个含只读 MySQL 连接的数据库技能，用户提数据问题 | 主图委派 data-analyst；子代理读 SKILL.md、在执行器里跑 SELECT；返回结论、SQL、文件路径；主图拼装交付物 |
| AC-02 | 子代理遇到无法自解的歧义 | 子代理返回 `NEED_CLARIFICATION:`；主图弹澄清卡；用户答复后主图把答案写进新 description 重新委派并跑通 |
| AC-03 | 提问克制 | 能用默认值补齐的缺口不弹澄清卡，交付物写明假设；用户已回答的问题不再问；同一时刻的多个缺口合并为一次提问 |
| AC-04 | 子代理产出 | 中间产物在 `scratch/`，不进结果面板；只有最终图表在 `output/`；返回里列出路径 |
| AC-05 | 技能接线 | 委派 description 含 `/skills/<name>/SKILL.md`；子代理 `read_file` 成功 |
| AC-06 | 只读 | 模型即使生成 DML，数据库拒绝写入 |
| AC-07 | 职责边界 | 最终交付物由主图拼装 |
| AC-08 | 无人值守（Open API） | 收到 NEED_CLARIFICATION 时不停下，带显式假设完成，交付物写明假设 |
| AC-09 | 顶层文件陷阱 | 子代理的中间文件不出现在交付物列表里 |
| AC-10 | 执行边界 | 技能提供的业务库能连接；要求连接平台自身数据库时仍被拒绝 |
| AC-11 | 装配门控 | 未启用代码执行器时不装配 data-analyst，主 prompt 不出现其委派指引 |

---

## 六、验证方案

1. **单测**（`test/linsight/`）：
   - 有代码执行器时 subagents 含 data-analyst，没有时不含，主 prompt 同步（AC-11）。
   - data-analyst 的 tools 只含代码执行器。
   - 两个子代理的中间件栈顺序一致，invalid-call repair 在最后。
   - 主 prompt 含 NEED_CLARIFICATION 契约；`_to_unattended_prompt` 输出不含 ask_user 相关文本、含降级文本。
   - `agent_factory.py` 与 `EXECUTION_BOUNDARY_RULES` 的例外措辞一致。
2. **端到端**（114 或本地连 test 中间件）：准备一个只读账号可达的测试 MySQL，建一个企业数据库技能。
   - **前置**：在默认 uid 隔离模式下，先确认执行器能连到该库。v1 的连通性验证早于 uid 隔离成为默认。
   - 跑 AC-01 / 04 / 05 / 07 / 09 主链路。
   - 用歧义问题跑 AC-02 / 03。
   - 用 Open API 跑 AC-08。
   - 让用户要求"连平台数据库"跑 AC-10。
3. 走 `/e2e-test`。

---

## 七、不做 / 推后

- 独立数据源模块（表、Fernet 加密、连接工厂、OpenFGA 权限、CRUD、管理页）
- 凭据按用户隔离、中央凭据管理与轮转
- 工作流节点统一连接、数据源级权限
- schema 语义层 / 数据字典、DM8 等多方言、结构化结果协议、结果脱敏
- 复用工作流的 `sql_agent` 工具：它只在工作流 Agent 节点里装配（`workflow/nodes/agent/agent.py:312-319`），`t_gpts_tools.json` 里没有它，任务模式拿不到；连接也是内联在节点配置里
- 前端按子代理类型显示中文名

---

## 八、开放问题与风险

| # | 风险 | 缓解 |
|---|---|---|
| 1 | 模型遵循度：主图是否选对技能、子代理是否遵守 NEED_CLARIFICATION 契约和 scratch 路径 | prompt 用强结构和示例；AC-02 / 05 / 09 实测校准 |
| 2 | 企业技能凭据对租户内全员可读 | 已拍板接受；只读账号 + IP 白名单；敏感库用个人技能 |
| 3 | uid 隔离下的连通性未复验 | 列为端到端前置检查 |
| 4 | 去掉轮数上限后，模型可能问得过多打扰用户，或反复澄清 | prompt 写明「何时提问」原则和「不重复问」；用 AC-03 实测校准；若实测过度提问，再考虑加软上限 |
| 5 | 大结果集撑爆上下文 | 结果写 CSV 只打印摘要；结果预算中间件兜底卸载 |
| 6 | `SubagentContextOverflowMiddleware` 构造时传入的是 researcher 的 resilience 实例（`agent_factory.py:1503`） | **已关闭**：两个子代理共用同一个 resilience 实例（`subagent_resilience`），降级额度共享，与溢出兜底的计数一致 |

---

## 附录 A：v1 论断逐条核对（2026-11-10）

| v1 论断 | 当前事实 | 结论 |
|---|---|---|
| 子代理 description 自动进主 prompt | 只进 `task` 工具描述（`deepagents/middleware/subagents.py:590-594`，`graph.py:787-797` 不传 system_prompt） | 不成立，主 prompt 显式加 |
| 原生 `skills=` 不可用 | 仍不可用（`graph.py:653-655` + `workspace_backend.py:927-958` + `skills.py:597-610`） | 成立 |
| 子代理挂同构 SkillsMiddleware | 主图现在挂 `LinsightSkillsMiddleware` + `SkillSelectionMiddleware`，全部技能挂载 | 改为委派时点名路径 |
| `bisheng_code_interpreter` 可用于子代理 | 仍不在 deny-list（`agent_factory.py:69-78`） | 成立，改为 allow-list |
| 澄清链全程现成 | 成立，新增 park-and-release | 成立，行号更新 |
| 主 prompt 硬约束在 :104/110/111/153 | 现在在 :129/:130/:175 | 行号更新；v2 去掉轮数上限 |
| 主图 `ls` 可能列不出沙箱文件 | 执行器 best-effort 同步 MinIO | 变轻，保留返回路径约定 |
| 中间产物写 scratch/ 即可 | 执行器把顶层新文件移进 output/ | 补显式路径要求 |
| 沙箱已验证可直连业务库 | 验证早于 uid 隔离默认化；代码无出网限制 | 需复验 |
| 凭据明文是短期债 | 全挂载后企业技能凭据全员可读 | 风险升级，已拍板接受 |
| 零前端改动 | 子代理名称原样显示 | 成立 |
| 未覆盖 | 执行边界规则禁止连平台数据库 | 新增例外 |
| 未覆盖 | 无人值守没有 ask_user | 新增降级 |
| 未覆盖 | 大结果卸载到 `/large_tool_results/` | 写入 prompt |

---

## 附录 B：实现与验证回写（2026-11-11）

**实现**：分支 `feat/3.1.0-beta1-013-taskmode-data-analyst`，spec 见 `features/v3.1.0-beta1/013-taskmode-data-analyst/spec.md`，E2E 记录见同目录 `e2e-report.md`。

**与本方案正文不同的实现决定**：

| 正文写法 | 实际实现 | 原因 |
|---|---|---|
| §3.1 中间件栈抽公共函数 | `_subagent_middleware(...)`，researcher 与 data-analyst 共用；两者共用同一个 resilience 实例 | 降级额度与主图的子代理溢出兜底共用一个计数 |
| §3.3 第 0 步写"执行中暴露的缺口（含 NEED_CLARIFICATION）可以提问" | 第 0 步只写"执行中才暴露的缺口"，NEED_CLARIFICATION 只出现在 data-analyst 的委派行里 | prompt 与工具同步：没装配 data-analyst 时不应提到它 |
| §3.6 代码执行器规则"抽成常量" | `_CODE_INTERPRETER_RULES_ZH`，主图与子代理共用；执行边界例外写在其中，并与 `EXECUTION_BOUNDARY_RULES` 同步 | 避免两处漂移 |
| §3.6 凭据写在 SKILL.md | 凭据放 `skills/<名>/secrets/`；`WorkspaceBackend.read/aread/grep` 拒绝该目录；两个提示词都禁止把凭据写进可见文字 | 见下方已知坑 1 |

**已知坑**：

1. **文件工具返回的内容会成为可见的步骤输出**。`read_file` / `grep` 的结果存进步骤历史，`execute-task-detail` 对分享链接跳过租户过滤。114 上 11 个会话凡读过 SKILL.md 的，口令都出现在步骤历史里。如果不知道这一点，把凭据写进 SKILL.md 就等于发给所有能看到分享链接的人。处理：`secrets/` 目录 + 后端拒读（`workspace_backend.py` 的 `_is_skill_secret_path`），契约记在 `linsight/AGENTS.md`。
2. **主图倾向于在委派前自己定口径**。3 次刻意构造的歧义问题里，主图要么在第 0 步先问用户，要么在委派说明里指定主口径并让子代理并列计算，子代理从未返回 NEED_CLARIFICATION。AC-06 因此记为"未触发、不阻断"（用户 2026-11-11 决定）。
3. **E2B 模式读不到 `skills/`**。E2B 沙箱在技能复制进工作区之前就快照了工作目录，所以 `secrets/` 在 E2B 下不可用；local（默认）模式已验证可用，container 模式未验证。
4. **114 上 Open API 选不到代码执行器**。v2 按日常模式配置校验工具，114 的日常配置没有工具，所以 E2E 用"v1 提交 + 改该会话 `api_meta.channel`"模拟无人值守。这是环境配置问题，不是代码问题。

**技能编写约定（数据库技能）**：

- `SKILL.md`：写库表说明、指标口径、常用 SQL，以及"连接信息在 `secrets/<文件名>`，在代码里用 `open("skills/<技能名>/secrets/<文件名>")` 读取"。不写口令。
- `secrets/<文件名>`（如 `conn.json`）：写主机、端口、库名、只读账号和口令。
