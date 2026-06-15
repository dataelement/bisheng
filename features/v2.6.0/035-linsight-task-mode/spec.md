# Feature Spec: 灵思任务模式（deepagents 适配层，F035）

- 版本：v2.6.0 · 状态：✅ 已评审（薄 spec：需求真相在 PRD，本文件只做 AC 收口与追溯锚点）
- 关联 PRD：[2.6 灵思 Linsight 迁移 deepagents 框架 PRD](../../../docs/PRD/2.6%20灵思%20deepagents%20迁移%20PRD/灵思%20Linsight%20迁移%20deepagents%20框架%20PRD.md)（需求唯一真相，FR/边界/优先级）
- 关联设计：[design.md](./design.md)（设计真相，原《技术方案》）
- 关联契约：[release-contract](../release-contract.md)（F035 已登记：`LinsightSkill` / 110 段 11050–11069 / `linsight_skill` 表）

> **本文件刻意薄**：PRD 第 4 章的 FR-1.x~7.x 与边界表是需求明细的唯一来源，此处不复制（避免三处漂移）。本文件仅承载：AC 总表（验收门禁 + `/e2e-test` 锚点）、范围红线、指针。

## 1. 用户故事

详见 PRD §2（US-1/US-2 终端用户：勾选 Skill → 流式执行 → 拿到产物；US-3/4/5 管理员：Skill 管理与存量迁移）。一句话：把灵思的自研 ReAct 内核替换为 deepagents，流程知识从动态 SOP 迁移为可热插拔的静态 Skill，全程保留 BiSheng 企业级横切能力。

## 2. 验收标准（AC，与 PRD §2 一字对齐）

| AC | 验收标准 | 需求明细 | 设计落点 |
|----|---------|---------|---------|
| AC-1 | 端到端「提交→规划→工具调用→产物→完成」全流程走 deepagents 内核，全程流式可见 | PRD §4.1/§4.3（FR-1.x/3.x） | design §2/§3 |
| AC-2 | 基线模型评测集上 Skill 稳定触发执行，命中率 ≥95%（基线由 POC 选定） | PRD §2.1 | design §7 + POC P4 |
| AC-3 | Skill 管理（列表/新建/导入/编辑/删除/启停）端到端可用，按租户隔离；built-in 不暴露 | PRD §4.5（FR-5.x） | design §7 |
| AC-4 | 存量 SOP 全量转换为 Skill；脚本输出迁移摘要（stdout + JSON，运维产物，无管理页报告界面），异常记录可人工处理 | PRD §4.6（FR-6.x） | design §8 |
| AC-5 | HITL 中断/恢复正常；现场经持久化 checkpointer 落盘，隔任意时长可续跑，Worker 重启不丢 | PRD §4.4（FR-4.4.x） | design §4（park-and-release） |
| AC-6 | 知识库/文件/E2B 沙箱在新内核下功能正常 | PRD §4.1.5/§4.2（FR-2.x） | design §5/§9（WorkspaceBackend） |
| AC-7 | 多租户隔离、权限、DM8 双库回归全部通过 | PRD §4.7（FR-7.x，含 §4.7.7 任务模式菜单权限） | design §6 |
| AC-8 | 自研 `bisheng_langchain/linsight` ReAct 内核及 SOP 动态生成链路代码下线 | PRD §3.4 | design §1/§8.6 |

## 3. 边界情况

全部边界与异常表在 PRD 各节（§4.1.9 / §4.2.5 / §4.3.6 / §4.4.5 / §4.5.10 / §4.6.5 / §4.7.6）与 design 各 §x.x 边界异常表，此处不复制。**范围红线（非目标）**：不做 Skill 自动挂载/learning loop/marketplace/Interpreter Skill/双引擎共存/邀请码（PRD §1.3 N1–N7）；不做旧灵思模式兼容（一次性切换）。

## 4. 设计与实现（指针，不复制）

- **设计真相**：[design.md](./design.md)（§1 总体策略 / §2 内核替换+模型选择 / §3 事件流映射+task_id 约定 / §4 HITL park-and-release / §5 工具·知识库·沙箱 / §6 多租户权限+菜单 / §7 Skill / §8 迁移 / §9 工作区 WorkspaceBackend）。
- **并行开发拆分**：[tasks.md](./tasks.md)（9 Track / Wave 编排）；**接口冻结**：[依赖与契约约定](./依赖与契约约定.md)（C1–C7）。

## 相关文档

| 文档 | 位置 | 角色 |
|------|------|------|
| PRD | `docs/PRD/2.6 灵思 deepagents 迁移 PRD/`（含流程图-drawio） | 需求唯一真相（FR/边界/优先级） |
| design.md | 本目录 | 设计唯一真相（含全部终稿修订） |
| tasks.md / 依赖与契约约定.md | 本目录 | 多人并行拆分与契约冻结 |
