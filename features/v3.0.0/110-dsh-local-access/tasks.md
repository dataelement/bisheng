# DSH 本地认证任务

spec 与 design 依据用户已确认技术方案及本轮实施指令整理。客户端基线 origin/V1.1.0，分支 codex/dsh-without-gateway。

- [x] T001 本地会话模型、Repository、Token、PKCE 与身份服务；覆盖 AC-01、AC-02、AC-03、AC-11。
- [x] T002 路由、runtime、middleware、配置及历史事件 DDL；覆盖 AC-01、AC-03、AC-09。
- [x] T003 授权保存、个人优先和部门继承，退出远程任务；覆盖 AC-04、AC-05、AC-06、AC-07、AC-10。
- [x] T004 管理界面和客户端兼容，保留审计；覆盖 AC-08、AC-10、AC-11。
- [ ] T005 行为测试、审计回归、迁移图、lint/typecheck、端到端验证和代码审查；覆盖 AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09、AC-10、AC-11。

## 评审

需求和设计未偏离已确认方案；个人显式零额度和多部门规则见技术评估。任务按认证、接线、授权、界面和验证分波。执行中记录实际结果，未执行的真实环境检查不得标记通过。

## 完成证据与目标范围

| 任务 | 目标文件组 | 证据 |
| --- | --- | --- |
| T001 | local_session 模型/Repository/Service、authorization Repository/Service、token_keys、access | native_access、shared_trust、identity 和 access 测试；真实过滤事件和 Desktop 解析器校验 |
| T002 | local_auth / identity endpoint、router/main、http_middleware、DshSettings、tenant_filter、Alembic | 标准及旧路由行为、middleware 回归、Celery 无 Gateway 配置导入、唯一迁移 head |
| T003 | admin_policy、subject_policy / subject_grant、role_migration、user profile、worker | 个人低额度/零额度、继承、部门重试、退休任务与后台关闭测试 |
| T004 | DshPage、SystemPage/dsh、DepartmentAccessTree、API/dsh；Desktop contract/client/error-copy | 管理端 300 项；Desktop 1931 项；两端构建与平台/客户端类型检查 |
| T005 | test/dsh、相关前端测试、deployment / validation / review | 本地验证完成；全仓原有门禁及真实环境检查未完成，故本任务保持未勾选 |

109:13001 已完成本次指定链路的真实联调，见 [环境报告](./e2e-109-20261020.md)；T005 的其他发布检查保持未完成。

详细结果见 [validation.md](./validation.md)，任务和特性自审见 [review.md](./review.md)。本次未进行生产操作。
