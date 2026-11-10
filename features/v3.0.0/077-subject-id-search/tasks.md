# F077 实现计划

使用 writing-plans、dispatching-parallel-agents 按独立目录分工，当前会话完成。

- [x] T1 主线干净基线、规则和单迁移头。
- [x] T2 后端纯函数、管理查询及模型/显示字段；真实 SQL 回归。
- [x] T3 授权候选按主线范围增加 ID 查询和真实总数，保留目录装配与原授权写入。
- [x] T4 Client API、原平铺用户/部门/组选择、创建授权与三语，不引入中粮用户树。
- [x] T5 Platform 共享选人、授权、列表、审批选人、日志和三语，不改流程写入。
- [x] T6 主线索引迁移、重复执行/回退与单 head 测试。
- [x] T7 统一后端回归、Ruff、arch-guard 和前端源代码审查；前端检查交 CI。
- [x] T8 独立主线纯净审查，记录差异及未执行验收。

测试接口沿用 normalize_keyword/escape_like/numeric_prefix_ranges、subject_match_condition/exact_id_priority。覆盖 Unicode/codepoint、大小写/通配符、跨来源同 ID、空允许范围、分页/计数及旧请求响应。

实现、可运行后端验证和独立审查已完成。T7 的真实 API/页面/双库性能及前端 CI 尚未验收，详见 verification.md；不把这些待验证项记为通过。
