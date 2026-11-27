# Token Exchange 设计评审记录

对象：design.md，对照已接受spec、design-checklist的24项、constitution与发布契约。状态：主代理静态清单自查完成，等待用户技术设计确认；没有实现或测试通过声明。

## 核查及修订

- C1/C4：SQL落Repository，身份复用既有identity_lookup；策略准入仅认已解析global-super/permission.application，不新增跨域ORM、DAO或OpenFGA直读。业务资源与ApiCredential权限没有被替代。
- C2/C3/C8：仅两张新整表，使用共享JsonType、时间默认及可移植索引；身份/租户由已验签凭证与父会话核对，关联查询显式约束；DB/配置是多节点真相。尚未执行MySQL/DM8实库测试。
- 协议：明确单一audience、严格issuer/aud及输入类型、重复字段/JSON键与未支持actor/resource拒绝；新增grant默认不启用；错误映射和三语文案纳入实现。
- 会话：B独立session与link同事务，父会话/客户端状态在线复核；B撤销不影响A，链接缺失不得降级。临时禁用再启用可恢复未到期且未撤销的会话，永久撤销不得复活，已写入设计。
- 寿命：固定开始校验t0，原exp、父session、B配置与300秒共同限期，排队/签名不延长。在途禁用不会把截止推迟至变更后300秒以外。
- 兼容性：已核对ClientFormDialog编辑不提交grant_types，不会覆盖API新增grant；全局管理异常是HTTP200 envelope，设计已更正“409冲突”的假设，区分public OAuth真实HTTP状态与管理业务码。
- 观测和测试：明确定义无敏感值的结果事件与无locals堆栈；计划普通用户、tenant admin、源/目标撤销、故障与旧43项回归。B自己的登录会话寿命与单点登出不被误报为本轮保证。

## 证据与局限

现状边界独立核查已完成并返回5条代码事实（全局管理员入口、独立session与两新表可行性、现有decoder宽校验、父链及删除语义、C1/C4边界），已纳入design。后续三次独立设计终审执行异常退出，没有结论；没有把这些失败标记为独立评审通过。本记录的设计终审结论是主代理按完整清单的静态自查：未发现遗留的明确high/medium问题，须实现和测试进一步验证。

用户业务规格已接受，不再重复请求；当前只需确认三个实现决策：复用/token与ES256、新增policy/link并复用独立B会话、父链在线检查与本地有界到期。
