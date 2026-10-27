# 灵思任务模式 NL2SQL 数据分析子代理方案

> **定位**：v2.6.0 · 灵思任务模式在"问数/NL2SQL"场景的效果增强（轻量方案）
> **归属**：F035-linsight-task-mode 域内增强，不新增领域对象（复用 `LinsightSkill` 等既有对象）
> **落地入口**：`src/backend/bisheng/linsight/domain/services/agent_factory.py` + skill 正文约定
> **关联**：[灵思 Linsight 迁移 deepagents 框架 PRD](./灵思%20Linsight%20迁移%20deepagents%20框架%20PRD.md) · [灵思任务模式 #1 子代理重引入技术方案](./灵思任务模式%20%231%20子代理重引入技术方案.md) · [灵思任务模式 Skill 能力恢复方案](./灵思任务模式%20Skill%20能力恢复方案.md)

---

## 一、结论先行（核心主张）

在现有灵思任务模式上**新增一个只读的 `data-analyst` 子代理**：

- **DB 访问不建基建**，连接信息留在 **skill 正文**里（Tier B，如"早报生成"skill 直写 MySQL 地址/账号/密码）；
- 通过**把会话 skill 接线进子代理**，让子代理读到连接信息与领域知识；
- 子代理在**沙箱（code interpreter）**里跑 SQL、产出数据与图表，**主图负责组装最终交付物**；
- 歧义走 `NEED_CLARIFICATION → 主图 ask_user → 重新委派`（**纯 prompt，零业务代码**）。

**为什么轻**：零新基建、零 DB schema、零前端、零新工具。改动集中在**一个文件** `agent_factory.py`（子代理 + skill 接线 + 两处 prompt）+ skill 正文约定。三处关键机制已核实到可执行级。

---

## 二、背景与动机（Why）

- **需求**：把任务模式在"问数/NL2SQL"场景做强——用户用自然语言问业务库，产出带数据与图表的报告。
- **已定路线（Tier B）**：短期**不建独立数据源模块**；连接信息留在 skill 里（**已验证沙箱可直连业务库**）。重基建（数据源表 / Fernet 加密 / OpenFGA 权限 / CRUD / 管理页、统一 workflow 节点内联连接）**整体推后为债**。
- **现有 harness 家底（均现成可复用）**：deepagents 装配（`agent_factory.py:758`）、researcher 子代理构造式防御、resilience + tool-loop 中间件、沙箱 code interpreter、WorkspaceBackend、`ask_user`→interrupt→park→resume 全链、StreamEventMapper。
- **三条硬约束**（贯穿全案，逐条落地）：
  1. 子代理进不了 `ask_user` → 用 `NEED_CLARIFICATION:` 返回形态回主图触发澄清。
  2. 子代理是"容器"、skill 是"内容" → **父 agent 的会话 skill 必须接线进子代理**（连接信息就在 skill 里，不接线子代理无从连库）。
  3. 委派 prompt 必须**自包含**（子代理 messages 被 deepagents 替换成只剩 task description）。

---

## 三、方案设计（MECE 六块）

### 3.1 容器 · `data-analyst` 子代理

- 新增第二个子代理（`name="data-analyst"`，区别于 researcher 的 `general-purpose`）。其 `description` 会被 deepagents 的 `SubAgentMiddleware` **自动冒泡进主图 system prompt**（`subagents.py:683-685`），模型据此决定派活，**无需手写进主模板**。
- 工具 = `_subagent_tools(tools)`（已核实：含 `bisheng_code_interpreter` 沙箱、且不在 `_SUBAGENT_TOOL_DENY` 黑名单）。**只读纪律**靠 prompt + skill 里的只读账号。
- 中间件栈 = resilience + tool-loop-breaker + **SkillsMiddleware（新接线，见 3.2）** + LanguageTail（永远置尾）。

### 3.2 内容 · skill 接线进子代理（约束 2 · 命门）

- ❌ **不能**用 deepagents 原生子代理 `skills=` 键：它硬绑传给 `create_deep_agent` 的共享 `WorkspaceBackend`（`graph.py:630`），而 `WorkspaceBackend.ls` 返回 `is_dir=False`（`workspace_backend.py:311-337`）→ SkillsMiddleware 目录枚举（`skills.py:597-610`）**发现 0 个 skill**。这与主图当初绕开原生 `skills=` 是同一根因。
- ✅ **正确做法**：往子代理 middleware **append 一个与主图同构的 `SkillsMiddleware`**：
  - `backend = FilesystemBackend(root_dir=file_dir, virtual_mode=True)`（dir-aware，能 `ls /skills/`）
  - `sources = [("/skills/", "Skills")]`
  - 位置：**LanguageTail 之前**（保证语言指令仍在最尾）
  - `file_dir` / `skills_present` 在子代理装配作用域（`agent_factory.py:742-751`）内已可见，**无需改函数签名**。
- **披露方式**（progressive disclosure）：模型 system prompt 里只看到 skill 的 `name + description + 路径`；连接串写在 SKILL.md **正文**，子代理**按需 `read_file /skills/<name>/SKILL.md`** 才拉进上下文（枚举靠 FilesystemBackend、读正文靠子代理自身 FilesystemMiddleware 的共享 WorkspaceBackend 按路径读，各司其职）。
- **通用工作流**（schema-exploration / query-writing 那套 know-how）→ **写进子代理 prompt**（不新建 skill——BiSheng 无"常驻 skill"机制，做成 skill 反而更重）；**场景 skill**（早报，含连接 + 领域知识）仍走会话选中 + 本接线。

### 3.3 澄清环 · NEED_CLARIFICATION（约束 1 · 纯 prompt 零代码）

- 子代理返回文本 → 冒泡成 ToolMessage 进主图上下文（`subagents.py:519-531`）→ 主图模型可见 → 识别 `NEED_CLARIFICATION:` 前缀是**模型语义任务**，无需改引擎（stream_event_mapper / `_handle_event` 均不需动）。
- **必须动 prompt**：改写主模板里"整会话最多澄清一轮 / 澄清必须在 task 之前 / 绝不第二次 ask_user"这几条硬约束（`agent_factory.py:104 / 110 / 111 / 153`），否则模型拒绝二次澄清。
- **约定返回契约**：子代理无法自解的歧义 → 返回**仅** `NEED_CLARIFICATION: [问题列表]`；主图识别后调 `ask_user`，拿到答案**折进新的自包含 description 重新委派**，不得把 NEED_CLARIFICATION 当最终答案。
- **防无限环**（对齐历史红线）：设**有界澄清预算**（每次数据委派最多触发 ≤2 轮澄清，超出则带显式假设继续），澄清由用户驱动、非机器自环。
- **全链现成无缺口**：`ask_user`→`interrupt`（`agent_factory.py:567`）→`__interrupt__` 探测（`stream_event_mapper.py:248`）→`NeedUserInput`→ park（`WAITING_FOR_USER_INPUT` + `USER_INPUT` push）→ `POST /workbench/user-input`（`linsight.py:405` put_head resume）→ `async_resume` 喂 `Command(resume=...)`（`task_exec.py:328`），同 thread_id + Redis checkpointer。

### 3.4 委派契约 + 职责边界（约束 3 + 交付物不变量）

- **自包含委派**：主图派数据任务时，description 必须自带 `精确问题 + 用哪个 skill/库 + 口径 + 允许范围`（子代理只看得到这一条 `HumanMessage`，`subagents.py:539`）。落在委派段 `agent_factory.py:117` / `__KB_DELEGATE_LINE__` 附近，比照现有 KB 委派的 `knowledge_id` 自包含约束。
- **职责边界**（保持 `:125` 不变量"最终交付物必须主智能体亲自完成，不得委派"）：**data-analyst 只出"结构化数据 + 图表路径 + 关键发现 + 执行的 SQL"，主智能体亲自拼装最终交付物**。既保隔离收益，又不违反"交付物不委派"。

### 3.5 产物治理（别堆一堆中间产物）

- **中间产物**（原始 dump、探索性查询、草图）一律写 **`scratch/`**（不被 `get_final_result_file` 收割）。
- **只有要进交付物的最终图表**写 **`output/`**（收割区），且约定**节制**——不把每张中间图丢进 output/。
- 子代理返回里**显式给出 output/ 产物路径**——规避已知瑕疵：主图 `ls` 只读 MinIO（`workspace_backend.py:311`）、可能列不出沙箱新写文件；但 `read_file`（缓存）与最终结果面板（扫 `file_dir`）均可见。

### 3.6 安全底线（唯一不可省）

- **skill 里的连接必须用只读账号**——哪怕模型生成 DML 或凭据泄漏，爆炸半径锁死在只读。这是短期唯一安全护栏，写进 skill 编写规范。
- 凭据明文在 SKILL.md（可被 `read_file`）= 已知短期取舍，记为债，随数据源模块 productize 时收口。

---

## 四、改动清单（What to change）

**唯一核心文件**：`src/backend/bisheng/linsight/domain/services/agent_factory.py`

| 改动 | 位置 | 说明 |
|---|---|---|
| 新增 `_DATA_ANALYST_PROMPT_TEMPLATE_ZH` | 常量区 | 子代理系统 prompt：数据分析工作流（探 schema→写 SELECT→双检→执行→报错自纠）+ 只读纪律 + "读所选 skill 的 SKILL.md 拿连接/领域知识" + 沙箱跑 SQL + 产物治理(scratch/output) + 自包含 + NEED_CLARIFICATION 返回契约 + 返回蒸馏结论/SQL/产物路径 |
| 新增 `_build_data_analyst_subagent(tools)` | 仿 `:589-619` | `name="data-analyst"` + description + prompt + `tools=_subagent_tools(tools)` |
| `subagents=[researcher, data_analyst]` | `:763` | 加入子代理列表 |
| 子代理 middleware 接 SkillsMiddleware | `:742-751` 同款 | §3.2 的正确写法，guard=`skills_present and file_dir`，置于 LanguageTail 前 |
| 主模板放宽澄清约束 + 加委派/识别指令 | `:104/110/111/117/153` + `__KB_DELEGATE_LINE__` | §3.3/§3.4：允许 NEED_CLARIFICATION 二次澄清（有界）、数据任务委派 data-analyst、自包含约束、职责边界 |

**skill 内容（约定，非代码改动）**：场景 skill（早报式）SKILL.md 正文写**只读账号**连接 + 领域知识。

**明确不动**：无新工具、无 DB schema/迁移、无前端、无数据源模块、researcher 子代理不变、workflow 节点不动。

**依赖**：data-analyst 走沙箱查库，需用户在配置里**启用 `bisheng_code_interpreter`**。

---

## 五、验收标准（AC 口径）

| ID | 场景 | 预期 |
|---|---|---|
| AC-01 | 会话选中一个含只读 MySQL 连接的场景 skill 并提数据问题 | 主图委派 `data-analyst`，子代理 `read_file` 该 SKILL.md 拿到连接，沙箱跑 SELECT，返回"结论 + SQL + output/ 图表路径"，主图亲自拼装交付物 |
| AC-02 | 子代理遇到无法自解的歧义（时间口径 / 多表歧义） | 子代理返回 `NEED_CLARIFICATION: […]`；主图调 `ask_user` 弹澄清卡，用户答复后主图折进新 description 重新委派并跑通 |
| AC-03 | 连续歧义 | 澄清轮数受有界预算约束（≤2/委派），不进入无限澄清环 |
| AC-04 | 子代理产出 | 中间产物落 `scratch/`（不进交付物），仅最终图表落 `output/`；子代理返回显式给出 output/ 路径 |
| AC-05 | skills_present 为真 | data-analyst 子代理装配含 SkillsMiddleware，可枚举并按需读 `/skills/<name>/SKILL.md` |
| AC-06 | 只读约束 | skill 连接使用只读账号；即便模型生成 DML 亦无法写库（DB 侧拒绝） |
| AC-07 | 职责边界 | 最终交付物由主智能体亲自拼装（不违反 F035 "交付物不委派"不变量） |

---

## 六、验证方案（端到端）

1. **环境**：本地起前后端 + 连 test 环境中间件（不改 test 部署）；备一个**只读账号**可达的测试 MySQL + 一个早报式 skill（连接写进 SKILL.md）。
2. **主链路**（AC-01/04/07）：任务模式提数据问题 → 观察委派 / `read_file` SKILL.md / 沙箱 SQL / 中间产物落 `scratch/`、最终图落 `output/` / 返回"结论+SQL+路径" / 主图拼装交付物。
3. **澄清环**（AC-02/03）：给歧义问题 → 子代理 `NEED_CLARIFICATION` → 主图 `ask_user` → 用户答 → 重新委派跑通；验证有界预算。
4. **单测**（`test/linsight/`）：① 子代理构造含 SkillsMiddleware（skills_present 为真时）；② 主 prompt 含 NEED_CLARIFICATION 契约且已放宽"最多一轮"约束；③ 委派 description 自包含约束存在。
5. 可选 `/e2e-test`。

---

## 七、不做 / 推后债

- 独立数据源模块（表 + Fernet 加密 + 连接工厂 + OpenFGA 权限 + CRUD + 管理页）
- 统一 workflow 节点的内联连接、数据源级权限、中央凭据管理 / 轮转
- schema 语义层 / 数据字典、多方言（DM8 等）扩展、结构化结果协议标准化、结果脱敏

---

## 八、开放问题 / 风险

| # | 风险 | 缓解 |
|---|---|---|
| 1 | 模型遵循度：NEED_CLARIFICATION 契约 + "放宽但不无限环" 属 prompt 遵循，随模型波动 | prompt 用强结构 + few-shot，有界预算兜底；实测校准 |
| 2 | 凭据明文在 SKILL.md（可 `read_file`） | 只读账号是唯一护栏，接受为短期债，随数据源模块收口 |
| 3 | 沙箱连通性：新业务库需确认沙箱网络 / 驱动可达 | 当前库已验证；每接新库前置确认 |
| 4 | 澄清预算上界具体值 | 建议每次数据委派 ≤2 轮，落 prompt 时定稿 |
