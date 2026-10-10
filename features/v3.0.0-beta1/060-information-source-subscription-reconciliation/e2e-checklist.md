# F060 E2E 验证清单

## 自动化分类结论

F060 不新增或修改对外 HTTP API、前端页面和业务错误码。按仓库 `e2e-test`
规范，AC-01～AC-37 均属于内部调度、跨服务或持久化行为，不生成伪装成 API E2E
的 mock 用例；自动覆盖由 `test/channel/test_information_*.py` 的 Service、Worker、
Repository 和跨 Service 集成测试承担。

真实 E2E 必须连接可控的 Information、Redis、MySQL/DM8、ES、MinIO 和默认
Celery Worker。以下清单不得用 fake 测试结果替代。

## 前置条件

- [ ] 使用隔离测试环境和专用 Information API Key，不使用生产 Key。
- [ ] 准备两个活跃测试租户，分别使用真实频道/知识空间配置创建人操作。
- [ ] 默认 `celery` Worker、`knowledge_celery` Worker 与 Beat 正常运行。
- [ ] 可查看 Information 订阅与文章接口、Redis 锁、数据库状态表、ES 文档、知识文件和 `BS_METRIC` 日志。
- [ ] 记录测试前远端订阅、`information_article_sync_state`、目标知识目录和 Beat schedule 快照。

## 1. 订阅并集与逐项收敛

覆盖：AC-01～AC-10、AC-33～AC-37。

- [ ] 两个租户各创建一个引用同一来源 A 的频道，执行：

  ```bash
  uv run celery -A bisheng.worker.main call bisheng.worker.information.reconcile.reconcile_information_subscriptions
  ```

- [ ] 远端只新增一条来源 A 订阅；请求体每次只有一个 `information_ids` 元素。
- [ ] `BS_METRIC domain=information_subscription_reconcile` 的 desired/actual/remaining drift 可解释，且日志不含 API Key。
- [ ] 删除一个租户的频道后再次执行，来源 A 仍保留。
- [ ] 删除最后一个引用后再次执行，默认逐项取消来源 A。
- [ ] 临时关闭自动退订，制造远端 extra 后执行；只报告 extra，不发取消请求。恢复默认开启。
- [ ] 将一个来源订阅调用制造失败；同轮其他来源仍处理，下一轮失败来源重新进入差集。
- [ ] 更换测试 API Key 后执行；使用新 Key 的空实际集合重新补齐完整期望集合。
- [ ] 验证 `channel_info_source` 可被两个租户读取，删除频道/租户不会删除公共元数据。

## 2. 晚同步、首次数量与包含式分页

覆盖：AC-11～AC-23、AC-33～AC-35。

- [ ] 让来源 A 的 `last_sync_at` 保持前一业务日，执行：

  ```bash
  uv run celery -A bisheng.worker.main call bisheng.worker.information.article.sync_information_articles
  ```

- [ ] 确认未调用来源 A 的文章接口，状态表不推进；后续轮询仍会检查。
- [ ] 让上游在当天稍后完成同步，再执行任务；公共 ES 出现新增文章。
- [ ] 清理来源 A 的状态行，在上游准备超过 20 篇文章并让第 20 篇与更多文章同秒；确认默认首次边界为第 20 篇时间，所有同秒文章均进入扫描范围。
- [ ] 将首次数量设为 1 和 100 分别验证；越界配置 0/101 应在配置校验阶段拒绝。
- [ ] 在首次分页中途制造失败，再向上游增加更新文章后重跑；原固化边界内的文章仍被处理，没有被新文章挤出。
- [ ] 制造 ES bulk 部分成功；成功新文档获得一次知识路由候选，但公共状态不推进，失败文章下轮仍拉取。
- [ ] 重复执行包含边界分页；ES 不产生重复 ID，已存在文章不再产生新的知识路由候选。
- [ ] 检查 `information_article_sync_state`：只有完整分页、严格 refresh、锁仍归属当前任务且 CAS 成功后才更新。

## 3. 主/子频道知识投递与终态失败

覆盖：AC-23～AC-34、AC-36。

- [ ] 租户 A 配置主频道投递；租户 B 配置只命中特定关键词的子频道投递。
- [ ] 同批新增一篇命中和一篇不命中文章；主频道收到两篇，子频道只收到命中文章。
- [ ] 两个配置指向不同空间/目录时分别尝试，不跨配置去重。
- [ ] 制造一篇文件重名、目标删除或权限失败；该篇记录真实终态失败，同批其他文章继续。
- [ ] 观察后续周期：失败项不重试、不补偿、不创建 delivery/outbox，也不扫描历史知识文件。
- [ ] 已接受文件后续解析失败时保留知识模块真实状态，Information 链路不再次投递。
- [ ] 关闭 `information_knowledge_delivery_enabled` 后同步新文章；只写公共 ES，不发布知识任务。
- [ ] 重新开启后执行后续周期；关闭期间文章不补投。

## 4. 调度、队列与多节点

覆盖：AC-10、AC-19、AC-22、AC-33～AC-36。

- [ ] 默认 Beat 仅每 3600 秒派发订阅 Dispatcher、每 1800 秒派发文章 Dispatcher。
- [ ] 观察多轮 countdown 均位于 0～600 秒；Worker 内无等待或 sleep。
- [ ] 六个 F060 任务由默认 `celery` queue 消费，没有 Information 专用队列或 Worker。
- [ ] 知识文件接受后的解析/向量化仍进入 `knowledge_celery`。
- [ ] 两个默认 Worker 同时执行同一来源；只有持有 Redis token 的任务写入，锁无法确认或续租失败时不推进状态。
- [ ] 日志中不存在旧 `sync_information_article` / `reconcile_all_tenants` 成功执行记录。

## 证据记录

| 项目 | 结果 | 证据位置/时间 |
|---|---|---|
| 订阅并集与逐项收敛 | 未执行 | 待真实测试环境 |
| 晚同步与首次边界 | 未执行 | 待真实测试环境 |
| ES 幂等与部分成功 | 未执行 | 待真实测试环境 |
| 主/子频道知识投递 | 未执行 | 待真实测试环境 |
| 失败终态与开关不补投 | 未执行 | 待真实测试环境 |
| 默认队列与随机调度 | 未执行 | 待真实测试环境 |
| 多节点 Redis 锁 | 未执行 | 待真实测试环境 |
| DM8 行为 | 未执行 | 待中央回归 |

## 当前结论

`PARTIAL`：本地自动化覆盖已具备；真实依赖 E2E、DM8 与多节点验证尚未执行，不能据此宣称完整 E2E PASS。
