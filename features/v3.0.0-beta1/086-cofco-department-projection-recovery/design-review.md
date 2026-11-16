# F086 Design R1自检

2026-11-16；已确认spec R1，目标cofco-1111 / 00720a9c。按sdd-review design-checklist的24项和constitution C1–C8逐项核对。

结果：LGTM（设计文档自检；用户已确认；不是实现或生产验证）。

## 自检中补齐的关键点

1. 保留自动原意图/人工当前事实边界，明确普通resource恢复资格不扩围；原FAILED恢复仅由Owner可信事实专用入口进入，COMMIT-only/完整目标及原效果边界可测试。
2. 明确普通部门执行和恢复的同session绑定与SQL收口，FGA成功SQL回滚后的独立失败标记CAS；历史CURRENT+COMMITTED不再重复增V，缺AFTER时受保护关门并转人工。
3. 不把Redis租约当服务端fence；有同版部署前提、异步token核验、D/op锁/CAS与写后核验。常驻进程用ContextVar，不能复制临时工具可变self.session。
4. 明确只读初始化路径不能触发Catalog种子、Store/model创建、marker自愈/heartbeat；apply与自动就绪前置分开。
5. 核对SSO外层bypass与strict的优先级，设计显式部门租户过滤上下文和退出还原，不靠手写SELECT条件掩盖问题。
6. 机器可读计划/共享证据/自动和人工重入状态表、legacy维护type拒绝顺序、源不存在/软删/角色引用/部门空间绑定边界及消费者清单已列出。
7. 周期任务有实际注册与配置位置、定点失败派发、扫描公平性/退避/预算；不复活已退役F015 provider-pull。
8. 无新表/列/索引/DDL，无全Store或全人员导出，pyproject不做额外门禁，已有备份只做事实确认；本地53项与未来验收区别明确。

## Constitution Check

- C1/C4：Owner提供业务事实和UOW端口，permission不导入业务模型，FGA编译/读写在权限侧；Role清理由其Owner接收调用方session。
- C2/C3：SQLModel/SQLAlchemy可移植查询，标量PK/索引和既有审计，自动租户过滤与受限跨租户祖先明确；真实MySQL/DM锁/计划必须另测。
- C5/C6/C7/C8：沿用既有外部错误码，不输出凭据，无前端改动；SQL台账/审计为执行真相，文件和Redis游标均不能证明提交。

## 实施后仍需验证

原请求与后台竞争、原型中状态CAS和失租是否正确、真实DM的绑定参数与LOB/锁、FGA未知结果及中断恢复、队列实际调度/多节点配置、开服后普通用户允许/拒绝。设计自检不能代替这些证据。

2026-11-16 R2：已按真实实现回写design，补正常业务投影与失败恢复的区别、已有门禁重入、IAM可选、无tenant列关联约束、请求拒绝告警及实际文件职责。真实双库/多节点仍未验收。
