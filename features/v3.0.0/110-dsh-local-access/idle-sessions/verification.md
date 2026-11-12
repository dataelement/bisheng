# DSH 认证后统一活动入口 — 验证与发布边界

2026-11-11。分支 `feat/bisheng-work-130`，基线 `4eb73410648b9a9637beeb293b6604ffa3d465d4`。用户明确确认：身份认证成功且进入服务端声明的业务入口即续期，不依赖业务权限、配额或最终结果。客户端不修改。

## 已验证行为

| 范围 | 证据 |
| --- | --- |
| 普通 Chat / Linsight | 真实 account_async → start → get_model_runtime → 记账 → 模拟供应商 → 结算；共享运行时不需要 sessions |
| 根因回归 | 同样两个真实工厂测试放到未修改基线，均复现 SimpleNamespace 缺 sessions；当前两个用例通过 |
| 原生 DSH | 真实 PKCE、ticket、token、HTTP 鉴权和 SQL 会话；额外保留真实模型工厂/模型服务，模拟外部存储 IO、供应商 |
| 内嵌工作区 | 实际 AuthJwt / LoginUser 依赖、Cookie 设备绑定、工作台 chat/completions 路由；200/403/429/500 均在业务处理前更新绑定设备 |
| WebSocket | 实际 ChatManager 消息分发，input/init_data 在资源权限检查前记录；check_status、stop、握手不记录 |
| MCP | 真实 SDK Streamable HTTP：initialize/list 不记录，tools/call 在 SDK 工具 schema 校验前记录；参数失败和工具 403 都记录；Host 421 不记录 |
| 失败和流式 | 续期存储错误返回服务不可用，模型工厂/供应商不执行，会话不撤销；SSE 仅在入口记录一次，不随分片刷新 |
| 多设备 | Cookie 只更新认证绑定的第二台设备，第一台设备不变；生命周期与跨租户回归继续保留 |
| 旧协议 | 已发布 1.2.0 的原版 parseToken 接受原生响应与延长后的到期时间，登录字段和别名保持 |

1.2.0 客户端源码仅只读导出到临时目录：发布标签解引用为 `8c33cac5dfb7baac18c135d5acd180716ebeec07`，contract.js 与标签内容逐字节相同，SHA256 为 `7b99d8de4cc09bbf8fb8a55c3f9dda69818d270f3a531f0d5750fedd009b09ac`。未修改客户端仓库。

## 测试结果与基线

- 专项组合：119 passed，1 deselected。排除的是已有 `test_models_api::test_usage_selected_model_cannot_borrow_another_allowance`，测试的简化 policy 缺 monthly_token_limit；该用例仍在扩展回归中执行并与基线对比，不作为新增失败忽略。
- 扩展组合：当前 544 passed / 17 failed / 4 skipped；相同未修改基线为 520 passed / 17 failed / 4 skipped。17 个失败用例 ID 完全一致，新增失败 0。
- 认证/任务/线程池补充组合：37 passed / 1 failed；未修改基线同为 37 passed / 1 failed，失败为 `test_workbench_content_safety_task::test_task_mode_miss_still_submits`。
- 扩展组合中跳过的两个客户端解析器用例在提供原版 1.2.0 导出目录后单独补跑，2 passed。

扩展失败分布：既有模型用量测试 1 项；工作台导出旧接口/夹具 5 项、游标/数据库配置 1 项、应用固定列表夹具缺 app 表 8 项、内容安全输入夹具 2 项。不修改无关业务或测试来凑全绿。SQLite 和模拟存储不代表真实数据库锁或生产供应商验证。

## 静态与架构检查

所有受影响 Python 文件执行 Ruff import 检查和格式化。新增核心模块、适配器和新增/重写测试完整 Ruff 检查通过；受影响旧文件剩余告警逐 code/message 与基线对比，不引入新告警。common/core 的历史跨层引用及部分 endpoint 的历史 DAO 导入由 arch-guard 基线保留，新增架构输出 0。diff --check 通过。

## 七维度审查

| 维度 | 结论 |
| --- | --- |
| 边界 | HTTP 请求内去重，WS 按 action，MCP 按 RPC 分发；非法消息不作为活动；未标记入口不记录 |
| 身份权限 | 设备绑定仅来自认证结果；权限/配额仍由原业务执行且无法被续期绕过；失效会话不复活 |
| 并发 | 复用原设备行锁与锁后时钟；设备能力不放入共享模型缓存，MCP 作用域 finally reset |
| 信息泄漏 | 设备能力不进入 LoginUser 序列化、队列任务或模型参数；不记录凭据；MCP 活动失败只返回安全错误 |
| 覆盖 | 普通聊天和原生 HTTP 保留真实工厂，真实路由与 SDK 验证入口，避免再次 mock 掉根因 |
| 风格架构 | 公共核心不导入领域；业务模块续期调用及可选 activity_recorder 参数已删除，模型工厂仅组装模型/记账/审计 |
| 文档 | 用户确认的 AC-IDLE-03、增量设计、父级设计、方案和实施清单同步 |

本地代码审查 PASS。API 链路验收通过；完整发布验收 PARTIAL。

## 发布前真实环境清单

- [ ] 原版 1.2.0 安装包：真实登录、普通聊天回复、DSH 原生调用、内嵌工作区、14 天跨期及缓存截止后重启。
- [ ] MySQL/DM8 实际并发刷新/活动/撤销；本轮没有新增 SQL 或 DDL，不能以此报告真实双数据库验证完成。
- [ ] 问题 Mac 的代理、断网、休眠和唤醒；客户端 1.3.0 优化仍未实施。
- [ ] 推送后的 CI、目标镜像摘要、环境配置核对及实际供应商聊天验收。
- [ ] 独立记录是否启用 session_idle_migrate_existing。109 最近只读核对值为 false，本轮不修改配置，不以镜像更新视作已开启存量转换。

提交和推送以 Git 记录为准；本轮不部署或修改线上数据。默认 14 天、刷新恢复窗口、设备独立及行锁事务沿用现有实现。既有迟到祖先 token 触发重放撤销的边界仍存在。

## 合并至 3.1.0-beta1 的验证

合并基线为远端 `5aa1de64f92fcbc514f3316cadacccdfa349d359`，源分支为 `8efc7e6e7dd86fd39b7a2a710bc85eb99941f6cc`。保留发布分支的工作流执行端口、并发租约、消息准入和角色策略；续期仍发生在这些业务判断之前。发布分支工作流测试同步移除旧的业务层续期钩子，新增消息准入拒绝时的入口续期回归。

- 认证、续期入口、租户策略专项：53 passed。
- 扩展组合：合并后 539 passed / 18 failed / 4 skipped；未合并发布基线 532 passed / 18 failed / 4 skipped。失败用例 ID 完全一致，无新增失败。
- 工作流/消息准入等补充组合：113 passed / 5 failed；其中失败文件在未合并发布基线重跑为 23 passed / 5 failed，5 个失败 ID 一致，均依赖未配置数据库。
- 原版 1.2.0 协议解析器：2 passed；前端配置测试：37 passed。
- 35 个受影响 Python 文件 Ruff 告警与发布基线均为 72，无新增告警；合并冲突逐处处理，diff --check 通过。

以上为本地合并验证；CI、部署和真实客户端验收仍按发布前清单独立记录。
