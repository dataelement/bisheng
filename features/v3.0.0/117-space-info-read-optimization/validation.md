# F117 主线验证记录

日期：2026-11-02。来源 `c4fc2316d791736efca6d8b6001814e474938631`；主线起点 `cbd755b3ebab083b366922fb54ed545bc94cfccf`，已包含 F116、检索会话和成员重新激活修复。

## 自动化结果

| 验证 | 结果 |
|---|---|
| 修改前 info/广场/预览/容器访问基线 | 64 passed |
| 修改后同范围及新增真实 service/ASGI 回归 | 105 passed |
| 联合知识/权限/managed/撤权重入/检索/公开访问回归 | 392 passed、16 skipped，无失败 |
| 六个变更 Python 文件 | Ruff format/check/F821、AST 解析、架构守卫通过 |
| 函数与 schema 审计 | 存量生产方法只修改 get_space_info 和有效订阅展示函数；schema 字段名/类型不变 |

16 项跳过均为默认关闭的真实部署 E2E：本功能 13 项，F116 managed 3 项。离线 ASGI 使用真实 router/service，替换登录依赖和 DAO/鉴权 I/O；不代表真实 JWT、OpenFGA 或双数据库联调通过。

使用现有 Python 3.11 虚拟环境和临时内存 SQLite/localhost 不可用 Redis 配置，未复制部署凭据、未连接或修改运行环境。现有依赖警告不影响测试通过。

## 行为与差异覆盖

- AC-01：成员只检查 visible，复用身份，无完整动作展开；无成员记录时保留单次 manage_permission 角色检查。分享页只读 visible；设置页和空间菜单仍读取 my-permissions。
- AC-02：info 与广场对可见的历史 pending/rejected 展示 subscribed，原记录状态不变；不可见 ACTIVE 清除 subscribed 和陈旧角色，可重新申请。
- AC-03：缺失/私有拒绝、鉴权异常不降级；主线未上架公开/审批空间的分享预览保留。
- AC-04：创建者、有效成员、部门/直接授权、超管可进入但未实际加入，以及重建租户保护通过；部门和标签步骤未替换。
- AC-05：九个阶段逐一注入失败，断言失败耗时被记录、异常传播、一次终态指标；正常响应计数不重复查询，阶段计时不重叠。
- AC-06：联合回归包含 F116、统一权限与成员重新激活修复。AST 对比确认 managed、入口鉴权、广场方法、加入/退出和其它 service 方法保持主线原实现；生产变更没有 DAO、SQL、索引、权限模型、前端或配置。

## 复现证据

本会话证据目录 `info-mainline-sync-20261102/` 保存 baseline.json、baseline-regression.txt、focused-regression.txt、regression-paths.json、integrated-regression.txt、static-checks.txt 和 function-scope-audit.json。联合测试路径由上一轮 F116 的已验证集合加本功能两个新测试文件构成。

真实权限、MySQL/DM8、浏览器及接口提速幅度尚未实测；按 [e2e-checklist.md](e2e-checklist.md) 部署后验收。本次不推送、不部署。
