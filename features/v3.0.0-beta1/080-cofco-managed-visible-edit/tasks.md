# F080 任务

spec/design 的业务决策与方案已由本会话用户确认；技术细节在已确认范围内。文档按 sdd-review 检查需求追溯、分层、契约和容量边界。

| 文档 | 状态 |
|---|---|
| spec.md | 已确认，用户授权按方案实施 |
| design.md | 已确认，记录当前实现方案 |
| tasks.md | 已拆解并完成本地验证 |

- [x] T001 测试：知识列表、目标构造、权限批量准备与标记回归；覆盖 AC-01, AC-02, AC-03, AC-04, AC-05, AC-06。目标 `test/knowledge/`、`test/permission/`；与 T002/T003 配对。
- [x] T002 实现：有界候选 Repository、业务 adapter 批量目标、统一 verified-action 入口及批量门禁/标记。依赖 T001；目标知识 repository/service 与 permission.application/domain；覆盖 AC-03, AC-04。
- [x] T003 实现：managed visible-first/edit 编排、角色与阶段指标，移除旧全租户扫描路径及对应失效测试。依赖 T002；覆盖 AC-01, AC-02, AC-05, AC-06。
- [x] T004 测试：ASGI 返回契约、调用预算、显式启用的真实 API 只读套件与手动验收清单。依赖 T003；覆盖 AC-01, AC-02, AC-03, AC-04, AC-05, AC-07。
- [x] T005 交付：Ruff、架构检查、共享权限与知识回归、七维代码审查，提交并合入本地 1028；验证既有未提交文件指纹。依赖 T004；覆盖 AC-07。

任务与七维审查见 [review.md](review.md)，自动化及真实环境缺口见 [validation.md](validation.md)。

## 实际偏差

无。真实 OpenFGA/MySQL/DM8 与浏览器验收是否执行，按 validation.md 如实记录，不用离线替身冒充部署验证。
