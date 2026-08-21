# Verification: 知识空间内容统计数据集重建

## 元信息

- Feature ID: `055-knowledge-space-content-stat-rebuild`
- Status: `req008-correction-passed`
- Verified at: `2026-08-20`
- Covered tasks: `T001`～`T013`、`T019`～`T022`；`T015`～`T018` 已执行但其旧 `REQ-008` 证据已失效
- Pending tasks: `T014`（独立破坏性索引重建）

## 结论

`REQ-001` 至 `REQ-007` 的既有实现和验证保持有效。`REQ-008` 已完成口径纠正：数据集只暴露唯一 `knowledge_contribution_ratio`，按“完整维度组合有效文件数 ÷ 当前全部筛选条件下有效文件总数”计算。分母移除全部普通维度和 stack dimension，但保留数据集、看板联动和时间筛选；缺少所选维度值的文件仍进入分母。后端、前端和构建验证均通过。实际索引重建仍未执行，远端 `dashboard_dataset` 也未由本次任务直接刷新。

## `REQ-008` 验证结果

| Verification ID | 当前状态 | 实际证据 |
|---|---|---|
| `V-CONTRIBUTION-SCHEMA-001` | `PASS` | 数据集契约测试确认只存在 `knowledge_contribution_ratio`，两个旧字段、层级配置和持久化模型字段均不存在；目标投影、Mapping 和重建脚本差异检查退出码为 `0` |
| `V-CONTRIBUTION-QUERY-001` | `PASS` | 参数化测试覆盖分类、业务域、知识空间、上传人、所属组织、多维与 stack；确认分母清空全部分组、筛选保持一致、缺失维度文件仍入分母、无维度和零分母稳定 |
| `V-CONTRIBUTION-FORMAT-001` | `PASS` | 前端测试确认唯一新指标首次添加使用 `percent + 1` 位小数，已有组件格式优先 |
| `V-CONTRIBUTION-REGRESSION-001` | `PASS` | 后端相关组合 51 项通过，前端相关组合 8 项通过，既有 divide、数据集 seed 刷新路径、实时看板和饼图行为保持通过 |

纠正后的 `REQ-008` 不依赖 T014，不需要删除或重建索引，也不需要回填文件数据。本次实现修改了查询策略、系统数据集 seed 和前端类型/测试，但未直接修改数据库、ES Mapping、文件投影、重建脚本或 ES 数据。

### 失效原因与复现证据

- 当前 `query_share_of_parent_metric` 仅在所选字段命中组织层级时计算父级占比；未命中时直接把非零结果改为 `1.0`，因此分类、业务域、知识空间等维度显示 `100%`。
- 只读索引检查确认目标索引有 `1516` 条文件快照，八个组织字段也存在非空数据，故问题不是 ES 无文件或组织字段全空。
- 旧测试与旧规格一致，但旧规格本身不符合用户实际口径，因此测试通过不能继续作为验收证据。

### 纠正后实际证据

- 测试先行红灯：新契约在旧实现上得到 `12 failed, 3 passed`，失败集中在缺少 `SHARE_OF_TOTAL` 和唯一新指标，证明用例能捕获原错误路径。
- 后端回归：`51 passed, 0 failed`，包含占比查询、数据集契约、幂等 seed 刷新路径和实时看板回归。
- 前端回归：3 个测试文件、`8 passed, 0 failed`，覆盖新指标格式、饼图 tooltip 和饼图数据行为。
- Vite 生产构建通过；仅有项目既有的外部脚本、浏览器数据、依赖 `eval` 和大 chunk 警告。
- `ruff format --check`：2 个本次测试文件通过；`ruff check --select E9,F63,F7,F82,I001`：目标 Python 文件通过；`py_compile`：目标 Python 文件通过。
- `bash scripts/arch-guard.sh` 和 `git diff --check` 均退出码 `0`。
- `knowledge_space_content.py`、`knowledge_space_content_dimensions.py`、`rebuild_knowledge_space_content_stat.py` 的目标差异检查退出码为 `0`，确认本次纠正未增加持久化字段、Mapping 或重建步骤。

### 实际命令

```bash
cd src/backend
uv run pytest \
  test/telemetry_search/test_knowledge_contribution_ratio.py \
  test/telemetry_search/test_knowledge_space_content_dataset.py \
  test/telemetry_search/test_dashboard_enum_labels.py \
  test/test_realtime_dashboard.py \
  -q

uv run ruff format --check \
  test/telemetry_search/test_knowledge_contribution_ratio.py \
  test/telemetry_search/test_knowledge_space_content_dataset.py
uv run ruff check --select E9,F63,F7,F82,I001 <目标 Python 文件>
uv run python -m py_compile <目标 Python 文件>

cd src/frontend/platform
npx vitest run \
  src/test/knowledgeContributionMetricFormat.test.ts \
  src/test/pieChartTooltip.test.ts \
  src/test/pieChartData.test.ts
npm run build

cd ../../..
bash scripts/arch-guard.sh
git diff --check
```

### 未执行项与真实环境建议

- 未直接刷新远端 `dashboard_dataset`；部署重启时 `_upgrade_dashboard_datasets` 会幂等覆盖目标数据集 `schema_config`。
- 未迁移已有组件；引用两个旧指标的组件需人工重新选择 `knowledge_contribution_ratio`。
- 未向 ES 发起任何写入、删除或重建操作，T014 仍独立暂停。
- 部署后建议分别用“业务域”“月份＋所属部门”“知识分类＋上传人”验证，并用相同筛选范围的总文件数手工复算至少一个分组；对于存在维度缺失值的场景，可见占比之和小于 `100%` 属于预期。

以下内容保留为 `T015`～`T018` 的历史执行记录，不代表当前 `REQ-008` 通过。

### 后端定向回归

```bash
cd src/backend
uv run pytest \
  test/telemetry_search/test_knowledge_contribution_ratio.py \
  test/telemetry_search/test_knowledge_space_content_dataset.py \
  test/test_realtime_dashboard.py \
  -q
```

结果：`30 passed, 0 failed`。

### 前端定向回归与构建

```bash
cd src/frontend/platform
npm test -- \
  src/test/knowledgeContributionMetricFormat.test.ts \
  src/test/pieChartTooltip.test.ts
npm run build
```

结果：`2` 个测试文件、`5` 个测试全部通过；Vite 生产构建通过。构建仅输出项目既有的依赖与大分块警告。

### 静态与架构证据

- `ruff check --select E9,F63,F7,F82,I`：目标 Python 文件全部通过。
- `python -m py_compile`：目标 Python 文件全部通过。
- `ruff format --check`：2 个新测试文件已符合格式；5 个共享旧文件的全文件格式基线未满足，因此该命令整体退出码为 `1`。为避免扩大范围，本批未机械格式化整份旧文件。
- `bash scripts/arch-guard.sh`：退出码 `0`，无 VIOLATION。
- `git diff --check`：通过。
- 对 `knowledge_space_content.py` 和 `rebuild_knowledge_space_content_stat.py` 的目标差异检查为空，确认没有新增占比持久化字段或重建逻辑。

### 历史未执行项与纠正后手工建议

- 旧实现未在真实看板中验证任意非组织维度，用户实际验证发现均为 `100%`，该缺口已使旧贡献占比证据失效。
- 纠正实现后应在看板分别选择“业务域”“月份＋所属部门”“知识分类＋上传人”进行手工查询，并用同一筛选范围总文件数复算至少一个结果。
- 应额外验证某个维度存在缺失值时，可见占比之和小于 `100%`，并确认这是预期口径。
- 上述验证不授权 T014 或任何索引写入、删除、重建。

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
