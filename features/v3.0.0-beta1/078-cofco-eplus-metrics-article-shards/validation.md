# F078 实现与验证记录

**日期**：2026-10-27。**开发分支**：codex/cofco-1028-eplus-metrics-es-shards。
**基线**：origin/feat/cofco-1028-3.0.0-beta1，8ebcfdcc270fbfa1c20b100262ccd5d83844c76c。
**工作区**：/Users/zhangguoqing/.codex/worktrees/cofco-eplus-es-shards/bisheng。
保留主检出无关修改；本地验证完成时未提交/推送，用户随后明确授权合并并推送至目标线；未运行生产迁移。

## 结果与边界

- 新增 eplus_robot_request / eplus_robot_connection，复用 BS_METRIC 及总开关/E+ 开关。自包含请求终态在事务提交后输出；用户 hash、原 msgid 供监控去重。连接沿用现有协议心跳与租约，不新增 Redis 聚合或统计持久化。
- channel_article_index.number_of_shards 严格正整数，默认 3；已有实体不自动重建。脚本加载同一配置并完整初始化业务 ES 上下文，默认只读，apply 需显式停写声明。
- 迁移已实现原子预留、写屏障/refresh、独立恢复副本、异步 reindex、全量内容指纹、pipeline/alias 策略保持及切换后确认；失败保留现场，不自动重放/解锁。
- 最终测试结果：398 passed，16 warnings，6.56s；其中 395 项定向回归、3 项真实 ES 演练，无失败/跳过。
- Ruff 对全部 25 个变更 Python 文件 format/check 通过；git diff --check 通过。arch-guard 无新增违规；settings.py 的 RULE-7 匹配在基线与当前均为同一处旧值，不新增凭据。
- 不提供全仓测试、生产性能、多节点 ES、副本高可用或客户 E+ 验收结论。

## 复现命令

在 worktree 的 src/backend/，使用项目 Python 3.11 环境、相同服务 config。以下 E2E 地址只能是测试套件认可的专用集群：

```bash
export PYTHONPATH=.
export PYTHONDONTWRITEBYTECODE=1
export config=<service-config-path>
export E2E_ARTICLE_SHARDS_ES_URL=http://127.0.0.1:<isolated-port>
python -m pytest -p no:cacheprovider   test/eplus/ test/metric_log/   test/channel/test_article_index_settings.py   test/channel/test_article_reshard_plan.py   test/channel/test_repartition_channel_articles.py   test/channel/test_article_reshard_cli.py   test/e2e/test_e2e_cofco_article_shards.py -q --tb=short
```

本次使用主检出既有 .venv Python 3.11.13，测试导入 worktree 代码。未安装/升级依赖。

## 真实 ES 演练

- 镜像：本机已有 docker.elastic.co/elasticsearch/elasticsearch:8.12.2。
- 专用临时容器 codex-f078-es-20261027，cluster_name=codex-f078-isolated，cluster_uuid=ZEFBG8kVRHGTTqgGOuhW-w。
- 仅绑定 127.0.0.1:32770；单节点、测试 index 副本 0、堆 512 MB，无生产数据。没有据此证明真实多节点或现网容量。
- 三项真实用例通过：具体索引与别名迁移，完整未刷新增删改、routing、analysis、filtered/routed/hidden 关联 alias、default/final pipeline、不重复加工；迁移后查询/写改删；从核验恢复副本回切并恢复写入。
- 专用资源按 ownership 标记精确清理，临时容器结束后停止并由 --rm 自动移除；已核对容器完整 ID 后停止，仅任务专用容器被移除；docker ps -a 精确名称过滤确认无残留。

## 故障测试和审查修正

- SQLite 实际业务事务验证无权限/繁忙/重复、提交成功、回滚不输出、超时、恢复、重复完成不再输出。
- 本地 WebSocket 验证协议认证拒绝也会输出 closed；观察器失败/失租约/结束后迟到心跳不改变业务或伪造存活。
- 既有 supervisor 测试曾在“client 创建”后立即断言“认证完成”，全套运行出现竞态。改为等待真实认证状态，未更改业务逻辑。
- 可观察 ES double 覆盖 dry-run 零写、task 失败、内容损坏、模板 alias 注入、red/磁盘/分片容量、活跃任务、已有恢复实体、源写限制、切换响应丢失及切换后的最终 metadata ack 失败。后者统一返回切换待核实 code=5，避免误判为复制前失败。
- 去掉接管事件重复输出，连接终态后拒绝迟到的认证/心跳宣告。
- 本机沙箱最初拒绝 WebSocket bind；授予仅本机隔离端口执行权限后重跑通过。真实 E2E 首次清理顺序和 alias fixture 客户端参数问题均只涉及测试，修复后重跑。
- 测试警告为既有依赖弃用与 ES Tasks API technical-preview 警告；没有忽略测试失败。

真实 E+ 双 Worker、MySQL/DM8、部署配置/采集与频道 API 验收清单见 [e2e-checklist.md](./e2e-checklist.md)；这些未执行项不标通过。

## 2026-10-28：迁移批量参数补充

- 按用户要求新增 `--batch-size`，严格正整数，默认 5；统一传入所有全量指纹分页与备份/目标 reindex 的 `source.size`，报告和运行元数据记录实际值。参数不改变分片配置来源或故障恢复规则。
- RED：新增参数和分页用例后、实现前，定向运行 11 failed、5 passed、22 deselected；失败包含 CLI 缺少参数及运行函数未接收参数。随后实现通过。
- 定向回归：`test/channel/test_article_reshard_cli.py`、`test/channel/test_article_reshard_plan.py`、`test/channel/test_repartition_channel_articles.py`，**38 passed**，7 项既有依赖警告。覆盖 CLI 默认/覆盖/非法值、初始化前拒绝非法值、真实编排的五轮全量扫描及两次 reindex 参数、完整跨页内容指纹、只读 status 返回运行批量。
- 真实 ES 8.12.2：专用本机容器 `codex-f078-batch-es-20261028`，cluster_name=`codex-f078-batch-20261028`，仅绑定 `127.0.0.1:32772`，512 MB 堆、1 GB 容器内存。既有 E2E 文件 **3 passed**，13 项既有依赖/Tasks API 警告；具体索引和 alias 两个迁移用例显式使用 `batch_size=1` 迁移两篇文档，证明跨页全量校验及复制；恢复用例使用默认批量。仅使用测试数据，完成后停止专用容器并通过 `--rm` 清理。
- 上述测试不证明 105 环境 MemoryError 已解决；批量按文档条数控制，单篇大文档仍需足够内存。本次未部署、未重新执行生产迁移，也未清理或解锁旧运行。
