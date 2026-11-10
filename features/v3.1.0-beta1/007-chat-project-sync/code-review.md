# Code Review Report

Feature：F007-chat-project-sync。审查范围：当前两个工作目录内本特性改动与未跟踪新增源码，对照 spec/design/tasks；不以空的 HEAD...HEAD diff 代替工作树审查。未创建分支或 PR。

| Dimension | High | Medium | Status |
| --- | --- | --- | --- |
| Boundary Conditions | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | PASS |
| Concurrency Safety | 0 | 1 | PASS_WITH_WARNINGS |
| Information Leakage | 0 | 0 | PASS |
| Test Coverage | 0 | 1 | PASS_WITH_WARNINGS |
| Code Style | 0 | 1 | PASS_WITH_WARNINGS |
| Docs Sync | 0 | 0 | PASS |

边界：严格 action union、unknown 校验、名称/ID/批次/响应/帧限额；仅完整且不低于高水位的快照发布。首次消息配对意图在正式创建点进入 Owner，重放以 13018 终止生成；task 意图在消耗邀请次数前验证。

认证：主体从当前认证注入；actor scope 覆盖管理员，项目是自然人的私有会话组织数据，未添加共享资源/FGA 旁路。main 信任窗口与主 frame、epoch 及固定动作；远端 presentation 只获得无数据失效提示。账号切换取消读写和 timer，旧响应不应用。自动迁移来源首次绑定当前账号，后续账号不接管。

并发：版本行锁先于项目/会话、四表同事务、数据库唯一约束、有限冲突重试。提交后才发布；订阅 ACK 后读 SQL，15 秒心跳弥补通知失败。MEDIUM：SQL 行锁在 MySQL/DM8 与多节点条件下仍需环境验收，SQLite 的顺序操作不是压力测试证明。

信息：日志不输出凭据/正文/导入 payload；响应身份只含当前用户/租户以校验路由，不暴露其他租户。保留原旧键，导入不覆写云端项目或已改变归属；不读取用户文件。

测试：真实 SQL/ASGI、Web、native Electron 行为覆盖见 e2e-coverage.md。MEDIUM：真实 OS 休眠、普通账号全流程、Windows 与正式包尚未完成。后端扩展 16 项失败在 HEAD 快照同样复现；Desktop 全回归 PPT 超时独立重测通过，未隐藏失败。

风格：使用现有模块、React Query v4、locale、Dialog/primitives；无新依赖。MEDIUM：四表按用户已确认设计采用项目 created_at/updated_at 和版本/回执提交序号，未为所有元数据表增加通用 wall-clock 字段；Repository 命名按 constitution C1，不退回旧 DAO。既有跨 API import 的 arch-guard 提醒与 HEAD 相同。

文档：按用户最新自动迁移指示更新 AC-11/12、设计决策、数据流、UI/来源绑定/重试、任务、限制与验证边界。未提交或上传非必要文档。

Overall：PASS_WITH_WARNINGS（源码审查结果；不等于全部目标部署条件已通过）。
