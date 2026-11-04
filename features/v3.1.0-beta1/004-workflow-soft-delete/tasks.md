# 工作流逻辑删除实施计划

目标：落实 spec 与 design 的单标记方案。执行方式：当前会话逐项实现，测试先行。

## 状态

| 文档 | 状态 |
|---|---|
| spec.md | ✅ 用户确认 |
| design.md / design-summary.html | ✅ 用户确认 |
| tasks.md | ✅ 自查 AC 覆盖与任务依赖 |

## 任务

- [x] T1 模型、迁移、标记删除与正常查询。覆盖 AC-01、AC-02、AC-10、AC-11。修改 flow.py 与 Alembic；真实 SQL 测试验证记录保留、版本标记、同步/异步过滤和联合列表。
- [x] T2 保存与版本事务保护。覆盖 AC-07、AC-09。修改既有更新方法及 flow_version.py；测试旧对象保存不复活、删除后不能创建/修改/切换版本、事务失败回滚。
- [x] T3 引用、新入口与历史。覆盖 AC-03、AC-04、AC-05、AC-06、AC-08。补直接查询、原始 SQL、预览和历史元数据 Repository；测试新操作拒绝、原清理顺序、历史权限与数据可读。
- [ ] T4 验证与评审。运行目标回归、迁移单 head、ruff、架构守卫、API E2E（可用环境）和特性级审查；记录未执行项，不虚报完成。

每个任务：先增加失败测试并确认原因 → 最小实现 → 运行相关测试 → 记录结果。T2 消费 T1 的删除标记；T3 的正常读取依赖 T1、写入保护依赖 T2。所有任务以已确认 spec 为准，不新增删除协调和在途保证。

## 实际偏差与验证记录

- 基线：当前分支 codex/004-workflow-soft-delete，未改动业务代码。uv 默认缓存路径不可写，使用 /private/tmp/bisheng-workflow-uv-cache，不改依赖。
- T3 盘点补充：role/domain/services/quota_service.py 和 tenant_mount_service.py 的 raw SQL 亦需过滤；属于原设计的直接 SQL 覆盖范围。

- T1–T3 审查：主记录单标记、版本同事务、全部正常 Flow SELECT 与 raw SQL 过滤、旧对象保存及父记录锁、元数据历史读取均已实现；不新增权限/运行协调系统。
- 独立全分支审阅发现活动工作流下单版本恢复被阻断；增加同步/异步失败测试后修复，保留父工作流未删除检查。
- 基线对照发现离线输入测试 helper 未模拟既有部门并发租约；仅补测试 helper 的租约 stub，未改部门并发生产逻辑。
- 最终本地结果见 verification-report.md；T4 中真实 MySQL/DM8 与部署 API E2E 尚未验证，故不整体勾选。

- 最终针对性验证 72 passed、1 skipped；T4 本地测试、迁移单 head、静态检查及独立代码审查已完成，真实环境项仍待完成。
