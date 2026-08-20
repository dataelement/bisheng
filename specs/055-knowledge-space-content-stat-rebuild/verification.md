# Verification: 知识空间内容统计数据集重建

## 元信息

- Feature ID: `055-knowledge-space-content-stat-rebuild`
- Status: `code-verified-awaiting-destructive-confirmation`
- Verified at: `2026-08-20`
- Covered tasks: `T001`～`T013`
- Pending task: `T014`

## 结论

代码实现、定向回归、静态语法检查、架构守卫和目标环境只读 dry-run 已完成。实际删除并重建 `mid_knowledge_space_content_stat` 尚未执行；旧预览、下载、收藏、门户参与度及额外的 5 条 `record_type=preview` 数据仍在现有索引中。

## 可执行证据

### 定向模块回归

最终相关回归组合：

```text
107 passed, 0 failed, 6 warnings
```

覆盖内容包括：

- 新 Mapping、8 个组织名称字段、缺失字段省略和三类日记录契约；
- 四级组织解析、五类空间所属组织来源和稳定维度哈希 ID；
- 事件快照、事件队列 claim/renew/reclaim/ack、永久回放起点和单调绝对计数；
- 预览、下载、收藏成功入口及普通门户遥测不重复计数；
- 组织改名、移动、标签、主组织和库绑定变更触发；
- file-only 全量校准、看板收藏指标与新维度；
- 重建确认值、owner lock、五类历史计数、事件队列保留和失败释放锁。

重建脚本增加未知记录类型预检后单独复验：

```text
5 passed, 0 failed
```

### 静态与架构验证

- 新增核心文件及重建脚本：`ruff check` 通过。
- 新增核心文件及重建脚本：`ruff format --check` 通过。
- 全部本次生产 Python 改动：`python -m py_compile` 通过。
- `bash scripts/arch-guard.sh`：退出码 `0`，无 VIOLATION。
- `git diff --check`：通过。
- 全修改文件的全文件 Ruff 扫描仍报告 239 个历史问题；本次未扩大范围清理旧代码。

## 目标环境 dry-run

执行命令：

```bash
cd src/backend
PYTHONPATH=./ uv run python scripts/rebuild_knowledge_space_content_stat.py
```

结果：退出码 `0`，`mode=dry-run`，未取得 owner lock、未设置回放起点、未删除或覆写数据。

### 数据预检

| 项目 | 数量 |
|---|---:|
| 关系库当前有效文件 | 1516 |
| 索引总文档 | 1903 |
| `file` | 1512 |
| `preview_daily` | 210 |
| `download_daily` | 12 |
| `favorite_daily` | 0 |
| `portal_engagement_daily` | 164 |
| 旧 `preview` | 5 |
| 缺失 `record_type` | 0 |

当前 file 快照比权威有效文件少 4 条；实际重建后应以 1516 条有效文件为验收基准。

### Redis 预检

- 新快照队列、事件队列、processing lease、scheduled flag 和 owner lock 均为 `0`。
- legacy 文件、预览、空间改名、空间删除队列和 legacy lock 均为 `0`。
- 当前 `replay_floor` 不存在；dry-run 未写入该值。

## T014 暂停条件

实际 apply 将精确删除整个索引，因此以下数据均不可恢复：

- `preview_daily`: 210 条；
- `download_daily`: 12 条；
- `favorite_daily`: 0 条；
- `portal_engagement_daily`: 164 条；
- 旧 `record_type=preview`: 5 条；
- 现有 1512 条 file 快照会被重新从关系库构建为预计 1516 条。

执行前还需：

1. 用户明确确认上述不可恢复清空范围，尤其是规格外识别出的 5 条旧 `preview`；
2. 安排短维护窗口，避免 `portal_engagement_daily` 写入器与索引删除竞争；
3. 再执行带精确索引确认值的 `--apply` 命令，并完成 T014 的新事件和看板验收。
