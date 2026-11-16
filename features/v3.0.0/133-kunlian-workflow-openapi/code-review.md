# F133 本地特性审查

- Date：2026-11-16
- Scope：当前工作树F133修改与新增文件（包含未跟踪文件），基线4e37058daf；不将分支所有历史差异算作本特性。
- Overall：EVIDENCE_GAP / NOT_READY_FOR_RELEASE
- 不是部署批准或真实环境通过声明。

## 已发现并修复

1. 控制面信缓存超管：改User Owner当前事实，避免撤权缓存窗口。
2. 继承管理/bypass上下文：可信tenant_execution_scope隔离并finally复原。
3. 版本接口仅visible就回编辑图：列表裁剪、图读取edit gate、真实SQL凭据路径脱敏。
4. 脱敏图GET→PUT丢密码：按唯一稳定节点及参数匹配保留缺省secret，明确新值仍可更新；不跨节点搬运。
5. 正式非Mock详情缺draft_revision：用原未脱敏版本计算同一CAS摘要；保存严格If-Match。
6. 旧版本下线新版本、ONLINE元数据绕过：锁内当前版校验与在线保护。
7. 旧Owner错误HTTP200/400降级、PENDING200、非法assignee500：标准envelope、真实Owner状态、PENDING202与路径严格校验。
8. Key轮换fake resolver假阳性：真实CredentialService.rotate测试；新Key可查询/取消，旧Key撤销后答案入口拒绝恢复。
9. 无效Key先装配身份依赖：改先认证后lazy身份解析。
10. 授权内存回执与审计丢主体：SQL持久摘要回执、业务及控制面审计意图，持久前置失败拒绝。

## 七维度状态

| 维度 | 本地判断 | 发布缺口 |
|---|---|---|
| 边界 | 身份参数、路径、严格DTO、时限与输入协议有拒绝测试 | 附件/多输入输出/平台节点明确未支持 |
| 认证权限 | Key租户/能力与实际用户交集、禁止super、普通Key隔离 | 真实昆联与权限Catalog/OpenFGA未验 |
| 并发事务 | CAS、User→Flow锁、配额当前读、幂等回执、Beat补偿 | MySQL/DM8真实锁及独立Broker进程未验 |
| 信息泄露 | 响应白名单、SQL secret脱敏/回写、审计allowlist | 真实图节点秘密路径需环境确认 |
| 测试证据 | 最新424 passed、2 skipped；多项先RED后GREEN，包含仅user_account准入、旧Query拒绝、账号/成员唯一与Key范围复核；历史幂等请求头合同已按用户要求取消 | Python3.11与真实环境E2E NOT_RUN |
| 风格架构 | 全changed/new Python Ruff与arch-guard无VIOLATION，i18n通过 | RULE7对旧默认项/合成secret测试WARNING已披露 |
| 文档 | spec/design/tasks/api-guide/operations/verification已更新 | 未将本地证据包装成发布完成 |

## 残余风险

- 授权receipt已claim而原F048 ledger尚未创建时崩溃可保持PENDING；不能自动冒险重复执行，需按operations受控核对。
- 审计finish失败保留INTENT并告警，不等于业务回滚；当前无通用自动结果重建器。
- 永久墓碑保留后每轮清理仍需keyset遍历历史记录，单任务有界但总扫描成本随历史增长。
- 当前一个配置连接，integration与连接组合由平台维护；未来多连接必须固定持久绑定或扩大运行归属校验，不能仅同名字认定同接入方。
- 测试为Python3.14且依赖有兼容告警；不能替代3.11。

## 交付判断

核心SG式接线及本地回归成立。尚不具备完整真实环境发布证据，不标全部任务完成，不提交/部署/迁移真实数据。真实验收按e2e-checklist执行，凭据/权限等环境写入需要另行授权。
