# beta1 合并验证（2026-11-18）

目标发布线基线：origin/feat/3.1.0-beta1，611a690182640fb452cc7bca48885a81347dbf0f。
待合入：635eea5407（包含 ed1062e82a）。使用本轮独立工作区的 codex/merge-tenant-ui-beta1-20261118 集成分支；主工作区未切换、未覆盖。

## 冲突及集成处理

- F015 design.md 的追加段落逐段合并：保留发布线分段调整/删除并发设计，以及本轮相似文档 UI 和删除说明。
- effective_roles.py 保留发布线 2e06a84f1b 已确认的 3.0.0 既有个人授权读取行为，未恢复旧范围过滤。只提取原主属/topology 验证供成员展示复用，登录和授权集合保持发布线语义。
- member_role_display 按同一规则展示已有绑定；存储租户、定义类型或定义部门范围不同不再标成未生效。只有缺失定义作为超管诊断，普通管理员仍不返回诊断详情，其他主属的附属成员不披露其私有角色。
- 新增 display/effective_roles 等价回归；调整原诊断和成员接线测试及 F023 文档，明确当前角色策略以目标发布线为准。不迁绑、不补授、不更改实际授权。
- F024 仍为待确认规格/设计，合入文档不代表任务放弃、进度新契约或整体回退已实现。设计注明复用目标分支已具备的删除处理栅栏，避免后续重复实现。

## 验证结果

- 后端定向：96 passed。覆盖 member role display/effective roles、发布线 v3.0.0 角色兼容、管理目录及成员、助手共享候选、模型状态与缓存、工具管理范围、源输入删除保护。
- 前端定向：14 个文件、116 passed。覆盖相似文档、版本及 API 契约、删除提示/流程、文件和空间元数据、文件详情、发布线处理入口、工作流模型、成员角色、模型 query scope 与共享行。
- pnpm lint、pnpm typecheck、pnpm check-i18n、pnpm build:platform 全部通过。保留既有 i18n 信息提示和大 chunk 构建提示。
- 12 个变更 Python 文件通过 Ruff format --check；Ruff 当前与目标基线均为 83 条存量诊断，逐规则/消息比较无新增。角色冲突适配涉及的四个文件单独 Ruff check 全部通过。
- 全部合入文件逐个架构守卫无 VIOLATION；旧 department service 测试的 RULE-7 WARNING 与基线一致，未新增凭据。
- 变更 locale JSON 可解析、QA 八列表格式和 git diff --cached --check 通过，无未解决冲突。

## 七维合并自审

边界、权限、并发、信息披露、代码增量规范、设计同步均 PASS；测试覆盖 PASS_WITH_WARNINGS（本地定向和构建完成，完整环境 E2E/MySQL/DM8/worker 联调未在本轮执行）。不存在新增 HIGH 发现，整体 PASS_WITH_WARNINGS。

本轮只合并/提交/推送代码，不部署 116、不恢复失败任务、不执行现场删除或回退。
