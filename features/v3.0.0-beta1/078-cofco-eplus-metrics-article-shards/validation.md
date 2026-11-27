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

## 2026-11-27：1125 线 clone/split 与默认原生校验

- 分支：`feat/cofco-1125-3.0.0-beta1`，最新远端基线 `d97ed9bc4101633e5f62504dbf56397cff68429e`。独立 worktree 开发，保留主工作区全部无关改动。
- 用户确认默认 clone 备份 + split 扩分片，并明确取消默认全文扫描；split 默认 `verification=native`，只查恢复完成、count、mappings/settings、分片、副本及 alias，原生一致性由 ES 提供。独立全文指纹是 `--verification full` 可选项；reindex 仍要求 full。批量默认 100，native 路径不分页、不读正文。Spec AC-23/Design/README 同步该决定。
- 测试环境：用户指定 `192.168.106.109`，已有镜像 `cr.dataelem.com/bitnami/elasticsearch:8.12.0` 启动专用容器 `codex-article-split-es-20261127`；cluster_name=`codex-f078-109-20261127`，cluster_uuid=`PkfehURSQuqbLc1vEuSh4g`，堆 1 GiB。仅绑定宿主 `127.0.0.1:39200`；单节点、测试索引副本 0。原有 ES 服务与业务数据不用于测试。
- pytest 最终 **70 passed，20 warnings，62.45s**，其中 59 项定向测试、11 项真实 ES 用例。警告为既有依赖及 ES Tasks API technical-preview，不跳过失败项。
- 真实用例：具体索引/alias × split-native、split-full、reindex-full 六种组合；完整停写前未刷新的新增/更新/删除；路由与 filtered/routed/hidden alias；default/final pipeline 不重复加工、恢复后正常加工；备份回切；空索引 1→3；多主分片默认真实 routing 空间 3→6；split 已受理后模拟响应丢失，保持原入口、备份及锁，可查询 SPLITTING_PENDING，拒绝重复 apply；大文章/native 场景。
- 大文章样本：25 篇，使用实际 `ARTICLE_MAPPINGS` 与 ngram 1..3，正文总计 **7,967,652 bytes**，最大单篇 JSON **9,793,092 bytes**（正文约 4.6 MiB，另含 HTML）。native 迁移耗时 **3.61s**，采样最高堆 **391,545,104 bytes**。用 spy 明确禁止运行中调用 reindex 或全文 search；迁移结束后由测试另行逐篇 GET 比对完整内容，全部一致。数字仅描述本次合成样本，不推算生产速度。
- 直接命令行实测：将最终三个脚本放在 109 已有 `bisheng-backend-dm` 容器的独立 `/tmp/cofco-article-split-20261127`，不覆盖服务代码；使用临时配置仅将 search/telemetry ES 指向专用测试实例。5 篇带 routing 的测试文章完成 dry-run → apply（complete）→ status（COMPLETE，write_block=false）→ 重复运行 noop；独立确认原文、3 主分片及新增/更新/删除正常。该过程使用实际 app context 初始化，不 mock CLI 初始化。
- 实测修正：ES 8.12 对已阻写目标重复 add_block 返回 `shards_acknowledged=false`；resize 目标自创建阻写，改为检查阻写仍在并 refresh。clone 显式补出的 `routing_partition_size=1` 与未声明的默认 1 做等价比较。多主分片使用 cluster metadata 的 `routing_num_shards`，不误用 get_settings 的声明默认值。
- Ruff format/check、变更文件 arch-guard、`git diff --check` 均通过。自查未发现未解决的切换/恢复缺陷。测试结束后清理专用容器、临时脚本及临时配置；不部署或操作客户业务索引，不清理其历史失败 run/写屏障。
- 结果 JSON：[`summary.json`](../../../docs/reviews/evidence/cofco-article-split-20261127/summary.json)；同目录保存 CLI dry-run/apply/status/noop 摘要，不包含连接凭据或文章正文。
- **边界**：未执行 119 GB / 198483 篇现场迁移、真实多节点/副本压力测试或全平台验收；这些不标通过。

复现命令（从 `src/backend/`，ES 必须是套件认可的专用集群）：

```bash
export config=<test-config-path>
export E2E_ARTICLE_SHARDS_ES_URL=http://127.0.0.1:<isolated-port>
python -m pytest test/channel/test_article_index_settings.py \
  test/channel/test_article_reshard_plan.py \
  test/channel/test_repartition_channel_articles.py \
  test/channel/test_article_reshard_cli.py \
  test/e2e/test_e2e_cofco_article_shards.py -q -s --tb=short
```
