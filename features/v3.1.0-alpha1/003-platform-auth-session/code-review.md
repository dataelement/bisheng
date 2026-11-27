# Code Review Report：F003平台统一认证与会话

审查基线：bisheng `572d5ecf77`（feat/3.1.0-alpha1）、mobile `6990f73`（main）。范围：两个实施工作树的未提交差异及新增文件；不以HEAD...HEAD空diff替代未提交文件检查。网关与桌面只读核对，无源码修改。

## 七维度

| 维度 | High | Medium | 状态／证据 |
| --- | --- | --- | --- |
| 边界条件 | 0 | 0 | 30/90天、精确失效、策略快照、丢响应/重放、Cookie物理过期、无效body/版本 |
| 权限与认证 | 0 | 0 | 真实密码身份提取，Session/Home/用户版本检查；用途分离、CSRF、凭据冲突；业务权限不改 |
| 并发安全 | 0 | 0 | 用户→Session→Refresh锁序及当前读、唯一代次；Web Locks/IDB/epoch/fence；真实DB锁待用户验收 |
| 信息泄漏 | 0 | 0 | RT/票据只存摘要；网页不返回RT；auth日志不记录query凭据，native Token不注入WebView |
| 测试覆盖 | 0 | 1 | 新平台套件、221前端、209手机及旧组差异对照；本机Jest需可选canvas适配，真实集成用户接手 |
| 代码风格 | 0 | 1 | 架构守卫0发现、Ruff新增0；原有Ruff/ESLint账本问题保持；无全仓格式修改 |
| 设计同步 | 0 | 0 | 实际模块/模型、origin、根auth Cookie路径、父子sid、关闭新签发的回滚地板已同步 |

## 已闭环的问题

- MySQL RR锁后旧快照及identity map：锁定当前读、populate_existing及统一锁序；Tenant使用共享当前读。
- Session策略与单点配置：会话期限快照、登录时读取当前策略；同秒真实JWT使用随机sid/jti；网关选择以私有DB发行序防时间精度与实例时钟差。
- 冻结后的网关绑定恢复补充：事务成功但Cookie/hint响应全丢，仍在首代未消费与300秒窗口内恢复；不得重置已消费链、覆盖更晚选择。
- Access Cookie自然删除仍能凭Refresh恢复；固定入口不遮蔽已选完整Access，迟到绑定不删除另一新入口Cookie。
- 退出先清选择，限定selector恢复CSRF与撤销；重复三次幂等、混传明确拒绝。
- 写事务不使用仅取消等待的to_thread两秒超时；只读准入保持预算，已有流和每条新WS消息都重验。
- 手机RPC真实写方法保活，list/status不保活；真实mobile SSE接入统一守卫，不只测试helper。
- host WebView冷启动Cookie消失后请求原生续期，不清有效parent或发空Refresh；两个SPA初始化和切号查询均门控。
- 两SPA认证固定根/api/v1/auth，避免workspace/custom base使Refresh Cookie不发送；RT/hint按服务器冻结cookie_retention_seconds保留，支持自定义TTL。
- 公开/自证入口忽略无关平台坏凭据，分享缺证明仍403、受保护请求仍401；refresh自行检查混传，不依赖中间件偶然拦截。
- 已提取不签发的PasswordLoginIdentity认证方法；DSH经公开纯状态协议共享轮换，旧表、codec与活动口径不改。

## Overall：PASS_WITH_WARNINGS（本轮开发范围）

没有剩余已知HIGH代码缺陷。警告是已有工具环境/静态基线，不是批准真实环境上线；按用户最新授权，发布前集成由用户自行执行。SQLite串行夹具不能替代MySQL/DM8并发实测；原生DSH安装包和手机真机仍按handoff验收。未合并、未部署。

说明：本报告由主执行者按sdd-code-review清单审查，并结合手机Owner对后端/网页的只读交叉评审；不是外部审计或CI全绿证明。微任务未逐个留存独立红态日志，未伪造TDD历史。
