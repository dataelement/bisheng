# Vibe 开发整合与合入审查（2026-10-23）

## 结论与范围

**开发合入：PASS_WITH_WARNINGS；完整 Feature 交付验收仍未完成。** 用户明确要求先收尾开发、合并到 `feat/3.0.0-vibe` 并推送远端，只做必要定向验证。本次不改变已确认规格、进程边界或授权/存储合同；无新增 Tag、公开镜像发行或远端环境变更。

- 目标起点：`feat/3.0.0-vibe@4aa9ce69b2830b81162fe631b9c801057c40ee8b`（已 fetch 核对远端）。
- F059 实现与最新实证：`cda8dccf26298af91a1df277dcd1a49787b6b444`；其中运行修复源为 `0f2db1f9a29213ca94d4596e64b00ad8fcbac528`。
- F086 源分支：`667546bb77eeb366e66a13d544d122ef24811e35`，本地历史合并提交 `575984069`；BIGINT/迁移在 F059 已经由 `ea3b1f6afb68da2b52ba4fd1fcf0bb5e060510ba` 继承。
- F059 已继承的发布线历史随分支合入；不是把目标以来全部 1640 个文件差异都称为本轮新增 Vibe 代码。未合并另一个任务正在修改的发布线最新工作区。
- 收回 F086 尚未提交的限定 Feature 文档/证据共 78 个文件、579065 字节；源工作树保留。五个公共后端草稿及一个 tenant 测试与 F059 完全相同，不复制覆盖；原主工作区其他任务不动。

## 已完成开发范围

| 模块 | 本次整合内容 |
| --- | --- |
| Docker / 应用交付 | 预制 runtime/preparer、版本化应用包、依赖材料缓存、离线补包、完整镜像与兼容 source-image |
| K8s 执行 | 受限 API 客户端、固定生产 Pod、PVC、材料授权/初始化、控制器租约、资源 UID/停止事实、生命周期/对账 |
| 数据与代理 | backend 源码/附件/快照存储，manager SQLite 维护；独立 app-proxy/egress-proxy 读取平台投影，manager 不直接访问 MinIO |
| 安装与发行实现 | Chart、准入服务、真实能力探测/报告失效、helper/assembler Dockerfile 与构建脚本、CI/目录/离线物料工具 |
| CLI / SDK | 现有业务接口接线、离线材料工具、容量码映射、提交的 wheel/manifest 与源码匹配 |
| 最终开发收尾 | 保留 K8s 后续模型/租户约束；刷新设计当前快照与已知坑；同版本镜像 CI 入口使用同一并发组 T274 |

F059 当前 **268/272**；F086 **92/94**。剩余勾选项是分项回归、完整验收、发行或交付汇总门。开发合入审查完成不把这些合并任务自动改为通过。

## 七维代码审查

三条只读分工审查 runtime、backend 和安装/发行/CLI/SDK；root 集成结论如下。完整报告保存于 F059 `integration-review/`。

| 维度 | 未关闭 HIGH | 结论 |
| --- | --- | --- |
| 边界条件 | 0 | 操作期限、准备/数据/材料边界及未知结果保护未放宽 |
| 权限与认证 | 0 | Owner/tenant/permission、HMAC/材料身份及 K8s 准入范围保持 |
| 并发安全 | 0 | 租约/UID/单写与持久事实核对；CI 同 release 跨入口竞争已修复 |
| 信息泄漏 | 0 | 未复制平台凭据到 manager；限定新增证据完成敏感值检查 |
| 测试覆盖 | 0（开发代码范围） | 复用既有 L1/真实证据；本次只做下列定向验证，完整验收缺口另列 |
| 风格与分层 | 0 | Ruff/架构门、进程和平台存储边界保持 |
| 文档同步 | 0 | D1 旧当前快照已修，runtime/backend 两线仅定向复审关闭 |

发现并处理：D1 设计仍写 R29/265-of-269 和 owner 数据未验，现更新为 R32/R11/M2 与明确未验范围；CI 并发按 ref 分组导致同版本跨入口可竞争，现与实际 release 表达式同源。后者只约束该仓库此工作流；仓库外 CLI/其他工作流仍需发布权限或仓库不可变策略。

## 必要定向验证

| 检查 | 结果与边界 |
| --- | --- |
| 两个 Git 冲突 | 按 hunk 保留 F059 `String`、17 表/tenant=None 与 UID 约束测试；历史合并后的产品/测试内容与 F059 源一致 |
| CI 同版本发布锁 | 现有单条契约先失败，修复后 **1 passed**；没有触发镜像构建/推送 |
| 冲突涉及的模型合同 | **17 passed**，真实 SQLite + 静态 MySQL/DM 方言；未连接 DM8。新工作树缺私有配置的初次收集失败，改用现有本地测试配置后成功 |
| 代码静态 | 修改测试 Ruff format/check、arch-guard 与 git diff --check 通过 |
| 静态整合完整性 | 任务正文/索引、限定 JSON、冲突标记、迁移唯一 head、变更 Markdown 本地链接及恢复文件来源核对；不代替部署 |

未运行全量 runtime/backend/frontend 回归；未重新部署 109/189。旧测试记录保留其原 source/date，不能转标为当前提交的实测。

## 子分支与恢复记录

- `codex/f059-installation@992905292`、`codex/f059-e2e@21250d329`、`codex/f059-image-release@f84415f25`、installer DNAT 分支已被 F059 继承。
- CLI capacity 独占旧 hash 虽非祖先，当前五个相关文件逐字节相同，源有 `0ff595428` 接线与测试/已重建 wheel。
- protection-runtime `0338d2f65` 对应源 `2992a28a8`，六个文件相同；destroy-maintenance `dd549c009` 对应 `1532e115e`，operations 文件相同。后续 purge 等待和 controller 准入继续保留。
- destroy-fact、prepare-cancel、protection-backend、restore-resume 四个测试分支的独占文件与 F059 逐字节相同，源历史有对应测试/修订。未仅凭 ancestry 或 git cherry 判定缺失，也未重复覆盖旧实现。
- 公共租户修复先在发布线 `9d156f261c` 落地，F059 正常继承；BIGINT 两原迁移父链保留，经显式 merge revision 汇合。

## 保留的验收与发行边界

1. F086 T055/T056：完整离线平台新装、目录导入及剩余故障组合与全交付汇总未结束。
2. F059 T067/T070/T071/T072：后续 Docker/平台范围、剩余故障和独立域卸载保留数据、当前版本双架构正式发行及最终逐 AC 交付汇总仍 pending；L2 开发审查子项完成。
3. ARM 按用户要求暂缓；DM8 仅静态；189 单节点 amd64 不能证明跨节点、NodeLost 或所有存储类型。
4. 189 R32 在途 prepare 的原操作/deadline/install UID/CID 续办实证保持；不把后续 probe 的 SQL 结果扩大成物理清理或批准上线。旧失败/unknown writer 及容量围栏不清除。
5. `v3.0.0-test-vibe@755d4456e5` 的历史双原生七镜像 CI 与 109 启动证据保留；不代表包含后续 F059 修复的九镜像版本已正式发行。R32 私有 manager-only 镜像也不是最终整合提交全组件发行。
6. 历史 frontend/backend 既有基线失败不因本次合并自动消除；未将相关其他业务工作区混入。

## 关联资料

- [F059 当前设计](../../features/v3.0.0/059-k8s-runtime-backend/design.md)、[任务](../../features/v3.0.0/059-k8s-runtime-backend/tasks.md)、[审查](../../features/v3.0.0/059-k8s-runtime-backend/code-review.md)
- [F086 设计](../../features/v3.0.0/086-vibe-runtime-delivery/design.md)、[审查](../../features/v3.0.0/086-vibe-runtime-delivery/code-review.md)、[历史完整交付审查](../../features/v3.0.0/086-vibe-runtime-delivery/code-review-2026-10-21.md)
