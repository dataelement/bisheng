# beta2 文件/文件夹 edit 遗漏修复审查

范围：AC-45；基线 `5e57d80ab2`，合入 `feat/3.1.0-beta2`。
按照 sdd-code-review 七维自审；本轮为已确认权限遗漏的 hotfix。

## 结果

| 维度 | High | Medium | Low | 结论 |
| --- | --- | --- | --- | --- |
| 边界条件 | 0 | 0 | 0 | PASS：无变更、停用动作、自定义选择、过期与错误 key/operator |
| 权限与认证 | 0 | 0 | 0 | PASS：普通用户，真实 Catalog/fence 与模型语义；文件 CUSTOM 和跨租户拒绝 |
| 并发安全 | 0 | 0 | 0 | PASS：复用发布 fence、两次提交前影响检查及原子指针；部分暂存必须重建 |
| 信息泄漏 | 0 | 0 | 0 | PASS：无现场密码；只记录维护 draft ID 与结构化摘要 |
| 测试覆盖 | 0 | 0 | 0 | PASS：存量发布、HTTP 版本修改、恢复、原生 CLI 生命周期、规模对比 |
| 代码风格 | 0 | 0 | 0 | PASS：ruff、架构守卫与 diff whitespace 检查 |
| 文档同步 | 0 | 0 | 0 | PASS：spec/design/tasks、八列表格、脚本索引与升级恢复指南 |

Overall: **PASS**（现场升级与页面验收待部署后执行）。

审查时纠正：禁用动作不出现在运行时有效动作映射中，verify 应检查完整持久化 Catalog
而非误报升级未完成；取消后 PROJECTING 不代表暂存完成，恢复必须重新执行原 publisher
的暂存和模型测试；历史 checksum 用例必须冻结历史 action scope，不能随首次安装默认值漂移。
保留旧 checksum 断言，不将新默认值冒充历史兼容结果。

## 本地验证

- 定向：125 项通过，新增升级/CLI/HTTP 测试及原 Catalog policy/bootstrap/runtime/service、授权模型和
  可见性来源 floor 回归；使用真实 SQLite 表、原 Catalog 发布器、真实权限服务。
- 版本：205 项通过（版本 service/endpoint 与 mutation 授权/wiring），权限拒绝无版本写入。
- 权限全目录：修复树 1257 passed、51 failed、5 errors、10 skipped；未修改基线
  1207 passed、51 failed、5 errors、10 skipped。56 项失败/错误名称集合完全相同，
  没有新增失败。该次对照之后增加一项 floor 来源保留回归，由定向门禁单独覆盖。
- CLI：20 条原生数据库池用例，覆盖 plan/apply/verify/resume 的正常/noop、业务拒绝、异常、
  部分初始化失败、取消；在实际 asyncio.run 结束前观察真实 engine_disposed。
- 从 `/private/tmp` 直接调用脚本 `--help`，无需工作目录或配置即可查看参数。
- OpenFGA transport 使用基于生产 schema 的内存语义执行器，不等于真实服务验收；
  MySQL/DM8 和 116 页面验收未在本次本地测试中执行。无前端代码改动。

## N/2N 完整维护流程成本

两组数据独立创建旧 Catalog，每个 Grant 三个 ACTIVE assignee，跨两个租户。
测试统计完整 plan → apply → verify → repeat，包含所有实际 Catalog SQL 和 FGA 写调用。

| Grant 数 | assignee 数 | SQL 次数 | FGA 写批数 | 累计 Grant 扫描行数 | 峰值内存 | 本机耗时 |
| --- | --- | --- | --- | --- | --- | --- |
| 240 | 720 | 371 | 4 | 1200 | 约 4.0 MB | 约 0.52 秒 |
| 480 | 1440 | 401 | 4 | 2400 | 约 4.0 MB | 约 0.74 秒 |

固定五次关系扫描的必要性见升级指南；批次上限 200，摘要不累积关系列表。
repeat 不增加资源扫描或 FGA 写。模型 tuple 写入数由 Catalog 定义规模决定，
不随资源/成员增长；此结果仅证实本地有界与线性趋势，不能当作生产维护窗口承诺。
