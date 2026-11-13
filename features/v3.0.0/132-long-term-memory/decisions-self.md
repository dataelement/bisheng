# 自己做的决定

按 goal-runbook §4"自己定"处理的事项，每条一行：任务号｜遇到什么｜怎么定的｜为什么。

- T001｜worktree 软链的是主检出的 `.venv`，`uv run` 默认会按本 worktree 的 lock 同步这个共享环境｜后端测试一律用 `uv run --no-sync python -m pytest`（清代理六变量）代替 `uv run pytest`｜不改共享环境；`-m pytest` 让 `import bisheng` 解析到 worktree 代码而不是主检出的 editable 安装
- T001｜基线运行期间本 worktree 已有改动，直接跑会污染基线｜基线改在 `git worktree add --detach` 出的干净目录（scratchpad/basewt，代码等于 origin/feat/3.0.0）上生成｜基线必须是未改动代码的结果
- T001｜串行全量后端测试约 5 小时（无中间件时大量连接超时）｜〔基线比对〕改为按 `test/` 顶层条目轮转分 8 片并行（scratchpad/shard_run.py），基线与比对用同一分片规则，合并 junit 后用 compare_junit.py 比较；两处既有收集错误用 `--continue-on-collection-errors` 跳过｜判定口径不变（新增失败数），只是运行方式
- T001｜〔架构检查〕的 xargs 串行要 15 分钟以上｜加 `-P8` 并行，输出排序后与基线比较｜输出集合与串行一致
- T002–T008｜V1–V8 的调查与实验由三个并行子代理完成，结论原文进 verification.md｜—｜节省主线上下文
- T009｜V1、V3、V4、V5、V6 的结论改了落点或实现细节，方向更严或等价｜作为 design §9 末的 R1–R7、R9 直接回写｜不改验收标准含义，不放宽隔离/权限/脱敏
- T010｜tasks 列的错误码之外还需要"类型非法""内容为空""无可用整理模型"｜增加 12110、12111、12112，同批进三语文案｜guard 与整理需要可区分的原因码
- T012｜实现需要几列 design §4.2 没列的字段｜`memory_item.rewritten`（过期事件只改写一次，T093）；`memory_turn_record.scene_class`、`ended`（常驻快照归因与深度研究轮结束）；索引名按表加前缀｜纯新增列，不影响契约
- T013｜`src/backend/AGENTS.md`：独立新表由 `create_all(checkfirst=True)` 建，revision 只管既有表｜迁移只给 `assistant` 加 `memory_enabled`；downgrade 删该列并删六张新表｜符合仓库的迁移规则，且可逆
- T014｜服务需要 Redis（常驻缓存、计数、整理锁），测试不能依赖 Redis｜新增窄接口 `MemoryKV`（`services/kv.py`，真实实现 `RedisKV` 直接用原始命令不走 pickle）与测试替身 `InMemoryKV`；数据库会话经 `repositories/_db.py` 一个接缝供测试替换｜与三个 ports 同一思路
