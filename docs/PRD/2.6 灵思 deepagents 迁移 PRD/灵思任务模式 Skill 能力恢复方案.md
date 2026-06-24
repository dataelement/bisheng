# 灵思任务模式 Skill 能力恢复方案

- **关联 Feature**：F035 `035-linsight-task-mode`（本方案是其 Skill 运行时能力的收尾）
- **关联契约**：[release-contract](../../../features/v2.6.0/release-contract.md)（F035：`LinsightSkill` / 110 段 11050–11069 / `linsight_skill` 表）
- **关联设计**：F035 `design.md §7`（Skill 存储与中间件，原始设计——部分已演进/过时，详见 §1）、`spec.md AC-2/AC-3`
- **文档性质**：历史背景沉淀 + 需求 + 方案思路。**先文档对齐，暂不开发。**
- **一句话**：F035 迁移时把流程知识从动态 SOP 改为可热插拔的静态 Skill，但 **Skill 的运行时注入入口在 2026-06-16 被临时关闭**；本方案厘清「原设计 → 实现演进 → 禁用 → 现状再核查」全脉络，论证恢复无架构级阻塞，并给出落地路径与工作量。

> ✅ **实现状态（2026-06-24，代码已落地 + 单测绿，端到端实测待跑）**：按 **Option 1 / Fork X（复制时过滤，最简）** 实现。
> - 落点：`skill_provisioning.materialize_session_skills`（复制闸门）+ `SkillStore.read_bytes` + schema/`linsight_session_version.skills` 列 + migration `f035_linsight_skills` + `task_exec._create_agent` 触发复制 + `agent_factory.create_linsight_agent(skills_present=...)` 装配 `SkillsMiddleware`（枚举 backend=指向工作区缓存的 `FilesystemBackend`）。
> - **未采用** `active_skills` run-config 穿透与 `TenantSkillsMiddleware` 运行时白名单（语义迁至复制闸门；该子类保留为休眠 fallback）。
> - **§1.5 两条静态推断已校正并单测确认**：① `SkillsMiddleware` 不注册文件工具 → 双 backend 不 shadow（deepagents 0.6.8 源码 + 装配共存确认）；② 原生 `skills=` 无法用——`SkillsMiddleware` 靠 `ls` 的 `is_dir` 目录项枚举（`skills.py:674`），而 MinIO 版 `WorkspaceBackend.ls` 只返回文件项 → 改用「复制进工作区 + `FilesystemBackend` 枚举缓存」；`test_skill_provisioning.py::TestEnumerationLoop` 实跑确认复制后被真实 `SkillsMiddleware` 枚举到、且注入路径经 `normalize_workspace_path` 解析回工作区同一物理文件（AC-R2 路径闭环）。
> - **待办**：D1 端到端实测（真实 MinIO + 模型 + 交付物落 `output/` 验 shadow 不复现）、D3 DM8/MySQL `alembic upgrade head` 实库回归。

---

## 一、历史背景与演进脉络

### 1.1 Skill 在 F035 中的定位
F035 把灵思自研 ReAct 内核替换为 deepagents，流程知识从**运行时动态生成的 SOP** 迁移为**可热插拔的静态 Skill**（progressive disclosure：先看 name/description，命中再 `read_file` 读正文）。Skill 分两类：
- **built-in**（`SKILLS_ROOT/built-in/`）：内核能力，始终生效、前端不暴露、不经 API。
- **租户自定义**（`SKILLS_ROOT/data/skills/{tenant_id}/`）：前端唯一可见可管理的一类，可 CRUD + 启停，按租户隔离。

### 1.2 原始设计（design §7.2）——双中间件 + 顺序硬约束
原设计用**两个**中间件：

| 中间件 | 职责 |
|---|---|
| `SkillsMiddleware` | progressive disclosure，加载两类 skill 的 frontmatter 注入 prompt |
| `SkillWhitelistMiddleware` | 按本轮 `active_skills` 过滤**租户自定义** skill；built-in 始终放行 |

顺序硬约束：`SkillWhitelistMiddleware → SkillsMiddleware → GenerativeUIMiddleware`。
`active_skills` 契约（C3）：`["a","b"]`=勾选白名单 / `[]`=全禁租户技能 / `None`=全放行（仅留给非 UI 调用方，产品前端始终下发显式列表）。

### 1.3 实现期演进（deviation D8）——合并为单 subclass
实际实现没有按双中间件落地，而是合并成**一个 subclass** `TenantSkillsMiddleware(SkillsMiddleware)`（`skill_middleware.py:54-109`），在 `before_agent`/`abefore_agent` 里直接过滤 `skills_metadata`。代码注释明示这是 **deviation D8**：单 subclass 取代 §7.2 的双中间件拆分，消除了对其它中间件的顺序依赖。白名单逻辑（built-in 始终放行、租户技能需 `enabled` + 命中 `active_skills`）写在 `_skill_allowed()` 中，已完整实现。

### 1.4 临时禁用（2026-06-16，commit `4ce0c496f`；注释 `285d6c20e`）
`agent_factory.create_linsight_agent()` 的 `middleware=` 列表**不再注入** `TenantSkillsMiddleware`，`make_skills_middleware()` 无生产调用方。代码注释（`agent_factory.py:385-392` / `skill_middleware.py:1-32`）记录**两条独立原因**：

1. **Workspace filesystem shadow bug**：`TenantSkillsMiddleware` 带了**自己独立的** `FilesystemBackend(SKILLS_ROOT, virtual_mode)`。装在工作区 `FilesystemMiddleware` 之后，被认为会**遮蔽** agent 的 `write_file/read_file`，导致交付物落进技能库而非工作区 `output/`，最终工作区空、产不出结果文档。
2. **`active_skills` 白名单从未生效**：per-run 白名单键从未写进 run config（`task_exec.py` 三处 config 只设 `thread_id`），第二道门即使开了也是 no-op。

当时取舍：**技能可选、交付物核心，先保交付物**，Skill 留作 forward-compatible WIP。

### 1.5 现状再核查（基于当前 deepagents 0.6.8，静态代码分析）
对当前安装版本（`deepagents==0.6.8`，pin `>=0.6.3`）逐行核查后，**原「shadow 阻塞」的前提已不成立**：

- 0.6.8 的 `SkillsMiddleware` **不注册任何文件工具**——它只在 `before_agent` 用自带 backend 读 SKILL.md 元数据、在 `wrap_model_call` 把技能清单注入 system prompt。文件工具的**唯一来源**是 scaffolding 级的 `FilesystemMiddleware`（`graph.py:206/213`，不可剔除）。
- deepagents 原生 `skills=` 参数收的是**同一个 backend 下的路径前缀**（如 `/skills/user/`）——官方设计本就让 Skill 与工作区**共用一个 backend**，根本不产生 shadow。

→ **结论**：当年那条注释的心智模型对应的是更早的版本/自建独立 backend 的组合。在 0.6.8 下，把 `TenantSkillsMiddleware` 加回 `middleware=` 列表**不会**再注册第二套文件工具、**不会** shadow 工作区。原「阻塞性架构问题」需要的是一次廉价的端到端实测复核，而非大改。

**但暴露出一个真实、有界的遗留缺口**（不是 shadow，而是原设计 §7.1 的隐含隐患）：技能 bundle 存在独立的 `SKILLS_ROOT`，而模型读正文/附属文件用的是**工作区** backend 的 `read_file`。design §7.1 写「模型按 SKILL.md 中的相对路径 `read_file` 附属文件」、§5 写「Skill 独立走磁盘、两套后端互不混用」——但 progressive disclosure 注入 prompt 的技能路径是 `SKILLS_ROOT` 内的路径，工作区 `read_file` 解析不到。**模型能看到技能 name/description，却读不到技能正文**。这才是恢复真正要解决的「命名空间」问题，且有成熟解法（§3.2）。

> ⚠️ 该断裂为**静态分析结论**，尚未端到端实跑验证；恢复方案 D 块（§3.3）需先实测复核再据此定方案。

---

## 二、需求

### 2.1 恢复目标
让 **租户自定义 Skill 端到端可用**：终端用户在任务模式勾选已启用技能 → 后端把勾选项作为 `active_skills` 下发 → 中间件按治理 `enabled` + 本轮白名单过滤加载 → 模型能读到技能正文并据其执行 → 交付物仍正确落工作区 `output/`。

### 2.2 验收标准（对齐 F035）
| # | 验收点 | 来源 |
|---|---|---|
| AC-R1 | 勾选的租户技能在运行时被加载，未勾选/停用的不加载（白名单二元：`[names]` / `[]`） | design §7.2 |
| AC-R2 | 模型能 `read_file` 到技能正文与 bundle 附属文件（progressive disclosure 闭环） | 本方案 §1.5 缺口 |
| AC-R3 | 启用技能后，任务交付物仍正确落工作区 `output/`（shadow 不复现） | 本方案 §1.4 原因1 |
| AC-R4 | 跨租户隔离：A 租户技能不被 B 租户加载 | design §6 / §7.6 |
| AC-R5 | 关联 F035 AC-2「Skill 稳定触发、命中率」可在恢复后重新评测 | spec AC-2 |

### 2.3 范围红线（非目标）
- ❌ **built-in 内置技能的设计与编写**：中间件对「无技能」优雅处理，built-in 缺省不影响租户技能恢复；属独立增量。
- ❌ 技能热更新策略、管理页↔选择器实时同步（WebSocket）、file-memory 超期兜底等产品增强。
- ❌ 不碰 F035 N1–N7 既有红线（自动挂载 / learning loop / marketplace / Interpreter Skill / 双引擎共存）。

---

## 三、方案思路

### 3.1 现状盘点（哪些已就绪、哪些缺）
| 组件 | 状态 | 锚点 |
|---|---|---|
| 平台端技能管理 UI（列表/新建/上传/启停/详情） | ✅ live | `platform/.../components/LinSight/skill/` |
| 客户端技能选择器 + 提交 payload 带 `skills:[name]` | ✅ live | `client/.../Linsight/Input/SkillSelector.tsx`、`TaskModeInput.tsx` |
| 后端 CRUD/上传/启停 API（10 端点） | ✅ live | `linsight/api/endpoints/skill.py` |
| `linsight_skill` 表 + `SkillStore` 磁盘层 | ✅ live | migration 2026-06-11、`skill_store.py` |
| `TenantSkillsMiddleware`（含白名单过滤） | ⚠️ 已实现未装配 | `skill_middleware.py`（DISABLED 注释） |
| 后端接收 `skills` 字段 | ❌ 缺 | 提交端点 schema / `session_version` 模型均无此字段，前端发了被丢 |
| `active_skills` 写入 run config | ❌ 缺 | `task_exec.py` 三处 config 只设 `thread_id`（约 L301/L389/L780） |
| 技能正文对模型可读（跨 backend） | ❌ 缺 | §1.5 缺口 |
| built-in 内置技能文件 | ❌ 仓库无（非恢复必需） | `SKILLS_ROOT/built-in/` 为空 |

要点：**前端 + 管理/存储后端已 100% 就绪**，缺的全在「把已上传的租户技能在运行时喂进 agent」这一段。

### 3.2 关键技术判断：命名空间缺口的本质与三种解法
原设计 §7.1/§5 坚持「Skill 与工作区两套后端互不混用、Skill 独立走磁盘」。在 0.6.8 下这反而让模型读不到技能正文（§1.5）。解法（恢复时三选一）：

- **Option 1（推荐，最简、零 deepagents 内核改动）**：任务启动时把「本租户 `enabled` 且本轮 `active_skills` 命中」的技能 bundle 复制进**当前会话工作区**的 `/skills/` 子树，中间件 sources 指向工作区内该子树（或直接用原生 `skills=`）。技能体积小（≤10MB/个），复制开销可忽略；治理过滤仍由 `TenantSkillsMiddleware` 子类完成。← 修正原设计「两套 backend 互不混用」的取向。
- **Option 2**：实现 overlay backend，`/skills/**` 路由到 `SKILLS_ROOT`、其余到工作区。更优雅、免复制，但要实现 `BackendProtocol` 包装，多 1–2 天。
- **Option 3**：让 `SkillsMiddleware` 非渐进地把技能正文直接注入 prompt（放弃 progressive disclosure）。仅适合技能少且小，不推荐。

### 3.3 改动块（全在后端 `linsight`，按依赖排序）
- **A. 技能正文对模型可读**：落 §3.2 的 Option 1（或 2）。关键文件 `agent_factory.py`（backend/sources 组装）、`skill_store.py`（复制源路径，`builtin_dir/tenant_dir/skill_dir` 已现成）。
- **B. `skills` 字段穿透到 run config**：① 提交/启动端点 request schema 增加 `skills: list[str]`（接住前端已发字段）；② 随会话带到 worker（持久 `session_version` 或随 Redis 队列 payload）；③ `task_exec.py` 三处（含 resume 路径）`config.configurable` 注入 `active_skills`（契约同 design §7.2：`[]`=禁用全部自定义技能，缺键=不约束仅兜底）。关键文件：`linsight/api/` 提交端点 + `domain/schemas/` + `task_exec.py`。
- **C. 装配中间件**：`create_linsight_agent()` 调 `make_skills_middleware(tenant_id)`（`session_model` 自带 tenant_id）加进 `middlewares`，恢复 system prompt 对技能的条件化介绍。`make_skills_middleware` 已实现，基本是「解开禁用 + 接好 backend/sources」。
- **D. 实测复核 + 测试**：先实测复核 §1.5 的两个论断（shadow 不复现 / 正文可读断裂是否真实），再据此定 A 块方案；复用 `test/linsight/test_skill_middleware.py`（白名单已覆盖），补 agent 装配级集成测试 + 跨租户隔离用例。

### 3.4 与原设计 §7 的差异修正（须在落地时回链标注）
1. **§7.2 双中间件 → 单 subclass**：已发生（deviation D8），design §7.2 的「两个中间件 + `SkillWhitelistMiddleware → SkillsMiddleware → GenerativeUIMiddleware` 顺序」描述为历史，实际以 `TenantSkillsMiddleware` 单类为准。
2. **§7.1/§5「两套 backend 互不混用」修正**：为闭合 progressive disclosure，恢复时技能需对工作区 `read_file` 可达（Option 1 复制进工作区，或 Option 2 overlay）。

---

## 四、工作量与风险
- **难度**：中等，**无架构级阻塞**。当年的「shadow 阻塞」在 0.6.8 下已消解；真正要做的命名空间缺口有 1 天级成熟解法。
- **核心恢复工作量（A+B+C+D，仅租户自定义技能）**：约 **5–9 人天**，单人 **1–2 周** wall-clock。
- **不在范围（勿混入估算）**：built-in 编写、热更新、实时同步——产品增强，非「恢复入口」必需。
- **风险**：① A 块若选 Option 2 overlay 略增成本；② 多节点部署须满足 design §7.1 的 `SKILLS_ROOT` 共享卷约束；③ 多租户隔离 + DM8 双库回归须在 D 块补测；④ §1.5 缺口为静态结论，须先实测复核。

## 五、验证方式（恢复实施后）
1. 本地起前后端 + 连 test 中间件；平台端建/传一个技能并启用。
2. 客户端任务模式勾选该技能发起任务 → 后端日志确认 `active_skills` 进 config、中间件加载到该技能。
3. 让任务产出交付物 → 确认文件落会话工作区 `output/`（不在技能库），即 shadow 不复现（AC-R3）。
4. 让 prompt 命中技能 → 确认模型成功 `read_file` 技能正文并按其指引执行（AC-R2）。
5. 三态白名单 + 跨租户隔离用 `test/linsight/` 集成测试守护（AC-R1/AC-R4）。
