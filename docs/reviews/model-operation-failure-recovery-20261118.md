# 模型共享修改失败收尾修复

基线：`origin/feat/3.1.0-beta1`，`83da4764460065f78f822e930aadaa1d8edf617b`。
分支：`codex/3.1.0-beta1/model-operation-failure-release-20261118`。

## 问题与结果

PREPARING预留在外部权限读取前已经提交，异常不自动撤销这条记录；后续写入又要求原操作者和相同命令，因而一次失败可能永久阻断所有后续编辑。历史日期精度导致摘要失效时，连详情GET也会被执行校验拦截。

现在未开始权限I/O的失败自动取消；已经开始写入的共享计划先按冻结日志完成恢复，再接受新命令。当前有权限的Root超管可通过下一次正常编辑触发恢复，不需要原操作者、原凭证或手工SQL。正在执行的请求仍互斥。进程被终止的遗留记录，在最后更新时间超过5分钟后允许按日志检查恢复，不能仅凭过期解除未知副作用。

## 实现边界

- 即时清理只持有本次请求在真实原生事务中签发的ModelSharingPreparation，不能用任意ORM快照/计划ID申请机械清理。不合成用户身份。
- 提供商锁、权限日志行锁及PREPARED状态CAS保证取消和权限I/O入口互斥。PREPARED日志与业务预留在同一SQL事务结束；已经开始的日志不按取消路径放行。
- 已开始/未知结果由权限模块按原store/model、checksum、AFTER恢复；FAILED_CLOSED纠正仍验证原业务围栏和确认摘要。原actor、命令、签名载荷不变，恢复者记录在ack.recovered_by。
- 取消记录为ABANDONED，不属于活动操作；新共享命令将旧回执标记SUPERSEDED。挂载失败可重新创建受保护的共享计划，之后不能重复执行已经替代的旧挂载。
- 表单GET只读活动操作的诊断信息，写入仍完整验证。历史DATETIME摘要异常只允许在证实未开始I/O后取消，不重签或伪造原计划成功。
- 普通编辑、共享切换、挂载重试、添加模型及删除准备入口接入恢复。已交接的模型删除/移除业务计划仍使用其原有引用目标与事务恢复路径，共享清理器不直接清除其删除证据。
- 没有新增数据库结构、依赖、后台任务或环境配置；权限SQL仍在权限仓储，业务代码不直接写OpenFGA。

## 验证结果

新增故障恢复用例12项全部通过，覆盖：

1. 读取/权限运行时不可用、请求取消后自动释放。
2. PREPARED插入后及业务绑定后失败；晚到Worker不能执行已取消日志。
3. 历史摘要异常可打开表单，授权写入取消旧记录，签名载荷保留。
4. 新鲜活动请求的并发互斥。
5. 已写权限但接收SQL失败，另一Root管理员提交相反命令。
6. FAILED_CLOSED部分结果纠正及COMMIT_UNKNOWN结果核验。
7. 普通用户精确拒绝19801；任意快照不能调用机械清理。
8. 原始GET /llm/info → PUT /llm → GET链路持久化新配置。

扩展回归25个测试文件：**276通过，1个既有失败**。覆盖模型共享/挂载/删除/计划及权限投影服务、SQL运行时、陈旧投影处理。Ruff、架构守卫及git diff --check通过。

唯一失败：
`test_model_revoked_sharing.py::test_eligibility_restriction_is_only_a_live_model_fact[knowledge_space-valid]`，预期ValueError但未抛出。未修改该用例或对应知识空间目标代码；在独立、未修改的同SHA基线再次运行该文件，结果27通过、同一项失败，确认不是本次引入。

这些测试使用真实原生SQLite事务、业务仓储和投影日志；认证边界及外部权限/Redis传输隔离。HTTP回归为ASGI接口集成测试，不能等同于真实登录、MySQL/DM8、OpenFGA、多进程或116页面E2E验收。

核心用例复跑（src/backend，需本地有效config和已安装依赖）：

```sh
PYTHONPATH=. uv run pytest \
  test/knowledge_unification/test_model_operation_failure_recovery.py \
  test/knowledge_unification/test_model_mount_share_recovery.py \
  test/knowledge_unification/test_model_provider_sharing_writers.py \
  test/knowledge_unification/test_model_sharing_lifecycle.py -q
```

## 七维代码复核

按仓库sdd-code-review检查表自行复核，无另外派发审查Agent。

| 维度 | 结果 | 证据 |
| --- | --- | --- |
| 边界条件 | PASS | 空日志、零增量、异常/取消、过期、历史摘要、未知结果及部分结果用例 |
| 权限与认证 | PASS | 现有model_deletion_request授权；当前Root超管；非管理员拒绝；清理原生凭证 |
| 并发安全 | PASS | 提供商锁、日志行锁/CAS、晚到执行拒绝；原计划恢复后才接纳新命令 |
| 信息泄漏 | PASS | 不存模型密钥、不返回旧actor凭证；日志只记录原操作ID，HTTP验证脱敏 |
| 测试覆盖 | PASS WITH WARNINGS | 新增12项通过；扩展276通过/1项基线失败；真实中间件未验收 |
| 代码风格 | PASS | Ruff、架构守卫、无业务层权限SQL/直接FGA调用 |
| 文档同步 | PASS | AC-12/13、design失败收尾与已知坑、八列QA用例同步 |

本次结论：**PASS_WITH_WARNINGS**，无发现的新增回归。真实中间件和页面验证仍需部署后执行。

## 部署后验收清单

- [ ] 在隔离提供商上令共享权限读取失败，恢复服务后直接改名称/关闭共享，保存并刷新成功。
- [ ] 原操作者退出或停用后，由另一Root超管提交不同修改，能自动恢复；Child管理员仍不能编辑Root模型。
- [ ] 在隔离环境中终止处理进程，超过5分钟后重试普通编辑，不需要后台解锁。
- [ ] 注入已提交但响应丢失及接收SQL异常，恢复后重试；不重复权限增量，不覆盖接收管理员已有的限制。
- [ ] 并发开启/关闭共享，旧请求不能覆盖新操作；MySQL/DM8与多进程复核行锁/CAS。
- [ ] 挂载后共享失败可重试，成功或新命令替代后不能重放旧挂载。

本次未修改116数据、未部署或重启服务；合并推送与部署状态以交付回复为准。
