# F118 统一升级流程实施与验证

用户已确认 spec AC-158～166、design §16，并要求先完成迁移简化与监控开发。实现位于独立分支 `codex/f118-upgrade-flow-20261120`，基线 `1a2f59a7273d694643cdfecef739cf591d34fc53`。本记录覆盖本轮开发及本地验证；没有把165此前旧脚本执行结果算作新实现验收，没有执行本轮现场升级或恢复服务。引用辅助化留待后续版本。

后续现场记录：2026-11-20至21已用实现提交2530742181，在165原completed Run执行新统一dry-run、幂等apply、严格后态复核及Redis验证，全部通过，见[实机验证报告](./165-f118-unified-flow-2530742181-20261121.md)。这是开发交付后的独立验证，不表示从迁移前快照重演首次迁移；下文“未现场验证”描述的是原开发检查点及当时边界。

后续合入记录：2026-11-23按用户新授权，以`56a461e2d7`将独立分支`952165f85e`合入`feat/3.1.0-beta1`，见[合入核对记录](./f118-upgrade-beta1-merge-20261123.md)与[3.0.0升级指南](../upgrades/v3.1.0-beta1.md)。文末“不合入”是原开发阶段边界，已由本次授权和合并取代；本次不发布镜像或部署现场。

## 实现结果

知识空间统一的标准操作为同一脚本的两条命令：

```bash
# src/backend，使用业务同配置；示例7须替换为现场实际有效用户
python scripts/unify_knowledge_spaces.py --run-id upgrade-site-a --dry-run
python scripts/unify_knowledge_spaces.py --run-id upgrade-site-a --apply --operator-id 7
```

中断后重复原 apply，自动识别原 Run 的 preparing、SQL、权限和引用位置。结构升级、模型配置、价格、Redis回填等功能仍执行各自既有步骤；标准知识迁移不再要求先运行另一个历史准备脚本。完整操作见[升级指南](../upgrades/v3.1.0-beta1.md)。

| 需求 | 交付行为 |
| --- | --- |
| 直观看到进度 | 约15秒心跳及阶段切换/错误即时输出；阶段、租户、单位、处理/提交数、耗时、速率、ETA、等待和原确认游标；终端与私有JSONL同步 |
| 减少耗时 | 本次执行的已验证页复用、64MiB热缓存及私有磁盘层；完整验证后sealed计划复用；SQL/权限已完成阶段先核验当前状态再跳过效果执行；引用批量前后读、批末checkpoint |
| 一次完整dry-run | 历史修复后事实视图、完整SQL/权限图/来源及目标预检；不真实apply再rollback；通过返回preflight_complete/can_apply=true，ready仍false |
| 自动处理并报告 | 复用原历史确定性规则，普通孤儿和失效历史按原保留策略报告；处理摘要区分自动修复、保留警告及计数scope，不逐项询问 |
| 同计划执行及恢复 | SHA/协议/环境/pin/真实before绑定；preparing创建、attempt及共享flow绑定同事务；历史共享回执、SQL实际ID结果页、权限admission、原引用提交链及完整Coverage |
| 写入互斥及不确定状态 | 专用数据库控制连接锁、代际token及事务围栏；有限外部意图持久化；未知请求未终结时拒绝接管，不用TTL猜结果 |

新增维护锁整表走既有模型发现和在线 `alembic upgrade head` 缺表创建合同；即使旧revision已在head，也须用包含新模型的源码执行结构升级。dry-run只读检查实际结构，不自行建表或创建锁种子。

默认材料目录 `/app/data/upgrade/3.1.0-beta1/f118/<run-id>/`，可用 `--materials-dir` 指定持久卷。目录0700、文件0600；原值备份保留在私有运维目录，共享恢复对象只包含执行必需材料。flow、历史、语义目录及结果页均内容寻址并严格回读；本地材料全部丢失可从原preparing绑定恢复。旧baseline/plan/四字段checkpoint/ordinal/fold不改。

退出码：0完整可执行预检或声明范围内成功；2参数/数据阻塞；3身份、材料、pin或事实漂移；4检查/执行未完成。失败结果包含原生阶段、最后已确认位置、提交是否未知、恢复命令及报告位置。报告或资源关闭失败不回滚已提交业务；已完成业务状态单独保留，不能伪报全流程成功。

`--verify`仅用于已完成Run；未完成或与旧阶段组合时写前拒绝。旧completed第一次使用统一入口的严格复核也只从本地候选叠加读取材料，执行原生完整校验，不创建控制锁种子、executor、绑定或远端制品，不改原Coverage epoch。

## 原生离线验证

使用现有Python3.11虚拟环境，配置文件仅为私有临时 `{}`，全目录对照统一阻止真实socket连接。数据库为每场景独立SQLite；业务Repository、Run/CAS、历史规则、权限投影、引用回填和Coverage均调用实际实现。仅替代外部FGA/MinIO协议传输与SQLite不支持的MySQL/DM8控制锁传输；未模拟关键planner或最终ready。

| 验证组 | 已取得结果 | 覆盖 |
| --- | --- | --- |
| 新Run、已有CLI及统一E2E联合组 | 30 passed / 24.02s | 新Run完整历史→冻结→SQL/权限/引用/Coverage，原flow冻结后来源漂移在写前拒绝；此命令早于最后C3新增用例 |
| 入口审查故障组 | 10 passed / 4.46s | 缺/坏实际flow零种子写入、failed只读预览/原Run恢复、未知外部意图、旧token、取消/敏感异常、报告IO失败不激活候选 |
| 最后CLI/executor/progress组 | 28 passed / 16.06s | 原生退休checkpoint位置、累计恢复速率、重复apply范围与报告、互斥attempt协议 |
| 新Run及全部本地材料丢失 | 3个原生场景，已包含后续18 passed / 10.08s组合 | 首次完整迁移、before_history中断、history后freeze前中断，全部沿原共享计划恢复 |
| 历史/事实Owner组合 | 302 passed / 43.02s | 原规则与after闭包，生成身份精确物化、原生finalizer及兼容入口；不是全目录独立通过数 |
| 共享历史大对象 | 7 passed | 大于16MiB的完整历史记录分成最多200项/约1MiB页，SHA/目录/尾页破坏拒绝，原checksum不改 |
| 新增summary篡改 | 3 passed / 1.46s | 非dict、额外ready、结构合法伪造计数重新寻址后，均在DML/FGA/远端制品写前拒绝 |
| 冻结后跨租户子行 | 前检2 passed / 2.05s；尾检/完成严格复核4 passed / 5.01s | 已注册异租户/不存在租户的助手子行不能被strict tenant读取隐藏，不能错误can_apply或签Coverage |
| 最后引用原生回归 | 65 passed / 72.56s | 原批末游标、批中回滚/ACK未知、增量/旧证明、当前事实/尾检；大来源与规模另计 |
| 最后结构/参数/审查/legacy组合 | 38 passed / 16.03s | 在线缺表合同/单head、真实未完成Run的verify四负例、completed严格复核零写、旧阶段verify组合拒绝及此前审查回归 |
| 最后入口/兼容/终态复核组合 | 87 passed / 58.72s | 完整review/coordinator/CLI/legacy/registration/E2E及跨租户尾检矩阵；旧completed首次统一严格复核零SQL/FGA/远端写且不进入control |
| 最后fresh/helper消费者 | 3 passed / 5.01s | 新Run完整原生迁移、before_history中断及history后freeze前全部本地材料丢失恢复；与87项是独立命令，不相加为唯一总数 |

这些组有重叠且来自不同验证时点，不能相加为唯一用例总数。具体八列用例结果见[test-cases.md](../../features/v3.1.0-beta1/118-knowledge-space-unification/test-cases.md)的TC-MIG-FLOW-001～015；七维审查及发现的缺陷闭环见[代码审查记录](./f118-upgrade-flow-code-review-20261120.md)。

最后38项命令（工作目录src/backend，临时配置仅含`{}`）：

```bash
config=/private/tmp/f118-upgrade-flow-offline-tests.yaml python -m pytest -q --disable-warnings \
  test/database/test_alembic_online_helper.py test/database/test_alembic_single_head.py \
  test/knowledge_unification/test_upgrade_coordinator.py \
  test/knowledge_unification/test_upgrade_review_regressions.py \
  test/knowledge_unification/test_cli_legacy_executor.py --maxfail=2
```

最后87项及独立fresh3项使用同一配置：

```bash
config=/private/tmp/f118-upgrade-flow-offline-tests.yaml python -m pytest -q --disable-warnings \
  test/knowledge_unification/test_upgrade_review_regressions.py \
  test/knowledge_unification/test_upgrade_coordinator.py \
  test/knowledge_unification/test_migration_cli.py \
  test/knowledge_unification/test_cli_legacy_executor.py \
  test/knowledge_unification/test_migration_registration.py \
  test/e2e/test_e2e_f118_upgrade_flow.py \
  test/knowledge_unification/test_reference_upgrade_batches.py::test_final_tail_refuses_hidden_foreign_or_unknown_tenant_children \
  --maxfail=2
config=/private/tmp/f118-upgrade-flow-offline-tests.yaml python -m pytest -q --disable-warnings \
  test/knowledge_unification/test_upgrade_new_run.py
```

最终91个改动Python路径的Ruff check/format、仓库相对路径arch-guard及git diff --check通过。模型发现已注册新锁表；隔离SQLite以真实当前head记录执行原缺表helper，缺表创建后0seed，重复无变化。这只验证既有结构编排合同，不替代真实MySQL/DM8 DDL/锁验证。

广回归命令覆盖整个`test/knowledge_unification`及`test/e2e/test_e2e_f118_upgrade_flow.py`，同一离线配置、阻止真实socket连接，结果为 **7850 passed、110 failed、38 errors、8 skipped / 2393.90s**，exit1。它是测试进程启动时的实现检查点，早于最后跨租户子行门禁、verify拒绝及CLI断言修正；这些后续差异由上表最终定向组闭口，不能称最终树全组重跑。

其中统一CLI重复apply用例仍沿用旧整dict相等断言，因本次报告位置及执行计数scope不同失败；已修正为原Run/hash/epoch/proofs稳定、重复执行计数为0且有报告的真实合同，最后28项入口组通过。该参数化节点不在HEAD collection中，不能冒称其在HEAD已失败。

其余 **147个唯一失败/错误节点** 在固定HEAD `1a2f59a7273d694643cdfecef739cf591d34fc53` 的私有git archive、相同Python/离线配置/网络拦截中，完整collection后用私有插件只执行这些节点：**109 failed、38 errors、7721 deselected / 12.33s**。逐节点首个异常/断言原因仅规范化backend路径与对象内存地址后，**147/147相同，首因差异0**。不是仅按同名节点判定。此前HEAD全目录在旧规模区段中断，保留partial log/XML；不将其报为一次完整HEAD全组结果。

| 既有失败类别 | 节点数 | 对照结论 |
| --- | ---: | --- |
| 数据库/permission_runtime上下文或F048注册未配置 | 44 | HEAD同首因，含Database URL required |
| 沙箱内本地服务PermissionError | 38 | HEAD同首因，服务夹具无法在当前沙箱启动 |
| SQLite夹具缺表 | 12 | HEAD同首因，knowledge_processing_fence 6、resource_reference_tombstone 3、knowledgefile 3 |
| 既有test double契约不足 | 16 | HEAD同首因，SimpleNamespace、KnowledgeUtils占位或slots签名等 |
| 既有就绪性、业务断言、异常映射契约 | 37 | HEAD同首因，含CoverageNotReady、HTTP503/400；不统称环境问题 |

广回归日志为`/private/tmp/f118-upgrade-flow-full-qa-20261120.log`；精确HEAD对照证据保存在私有归档目录的`failure-comparison.json`与`comparison-summary.json`。本轮新实现的后续修复以最终定向原生组验证，无未关闭的本轮新增失败；整个知识模块仍有上述既有失败，不报全绿。

## 性能及容量实测

引用规模夹具走真实SQL、事务与完整签证，以下SQL计数包含新增必要的孤儿/租户闭口检查及签证尾检。

| 放大方式 | 规模 | 完整流程SQL | 完整流程事务 | 仅登记SQL | 仅登记事务 | 语义采集SQL |
| --- | --- | --- | --- | --- | --- | --- |
| 同一业务根增加来源 | 13→25来源 | 601→637 | 96→96 | 197→221 | 31→31 | 4→4 |
| 来源同时增加独立业务根 | 14→26根，13→25来源 | 671→779 | 96→96 | 230→290 | 31→31 | 4→4 |

最终规模组 **8 passed / 16.80s**。同根13/25来源完整流程1.775/2.244s，Python分配峰8.004/7.859MB；独立根完整流程2.274/2.063s，峰7.853/7.857MB。仅登记同根0.378/0.450s、峰1.434/1.473MB；独立根0.393/0.509s、峰1.368/1.871MB。时长受共享本机负载影响，单次样本不用于外推；分配峰不是RSS。

改造前逐来源语义读取在13/25来源时为26/50次SQL；新批量路径为4/4。必要current-after、完整FGA before/staged/after和最终O(root)尾检保留；不能把它们作为重复读取删除，也不声称每类I/O都减少。

真实单来源5120条引用、5MiB配置填充的成功及中断回滚/恢复共 **2 passed / 67.85s**。完整成功25.44s，Python新增分配峰49.85MB；写完批次后注入中断、原子回滚再恢复37.10s，新增分配峰63.72MB。尾检实际业务与完整索引canonical字节为8,282,110。pytest进程生命周期RSS高水位950.6/983.1MB包含导入/夹具及额外断言，不能当阶段增量或独立CLI常驻内存。

批次最多100来源且不跨租户，按明细和序列化计划字节分批；一个超预算source独立原子处理。原生单source配置与索引仍完整加载，现有tuple set和单租户collector也有全量成本；共享历史读取重建完整native dict，不宣称恒定内存。原16MiB单制品上限保持，非source总JSON上限，不引入更低的数据拒绝上限。

## 交付边界

尚未取得真实MySQL/DM8 NOWAIT/失连接管、真实FGA/MinIO网络中断及生产规模克隆的本轮演练。上述本机时间不用于推算165或生产维护窗口；新实现未在165部署，本轮未恢复165服务。全部写入者停服仍是完整签证前提，维护锁只串行迁移执行者，不能宣称任意在线写入下线性一致。

普通孤儿默认保留内容并报告。缺少安全、持久恢复配方的物理清理明确not_evaluated，不能为“自动”删除不确定内容或虚构成功；真实未知授权、归属冲突、材料损坏或当前漂移仍阻断。既有阶段诊断/旧计划入口仅保留兼容，不当标准完整流程；有活动统一attempt的写入须遵守同一事务围栏。

提交保持独立分支，不合入3.1.0-beta1；原spec首行用户未提交修改不纳入本轮提交。
