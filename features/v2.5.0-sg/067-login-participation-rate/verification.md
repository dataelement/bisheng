# 验证记录

Status: MANUAL_VERIFY_REQUIRED（本地实现和回归完成，真实 ES 及部署对账待执行）

## 证据

2026-09-21，在 src/backend 的现有 .venv 执行：

| Evidence | 命令 / 操作 | 结果 |
|---|---|---|
| E-001 | 修改生产代码前执行 `python -m pytest -q test/telemetry_search/test_login_participation.py --tb=short` | 2 failed：原两个用户数据集未使用累计登录策略，稳定复现旧配置 |
| E-002 | `.venv/bin/python -m pytest -q test/telemetry_search test/telemetry/test_user_engagement_merge.py test/test_realtime_dashboard.py --tb=short` | 138 passed，1 条现有 SQLAlchemy 弃用警告，2.10 秒 |
| E-003 | `TZ=UTC .venv/bin/python -m pytest -q test/telemetry_search/test_login_participation.py --tb=short` | 18 passed，验证服务器 UTC 时仍使用北京时间月/周边界 |
| E-004 | Ruff 检查新增查询模块、新增测试及新增错误定义 | PASS；对五个已有受影响模块与 HEAD 对比 Ruff 诊断，多重集无新增；未顺手修复旧风格问题 |
| E-005 | `python -m py_compile` 受影响后端模块；`git diff --check` | PASS |
| E-006 | `docker ps --format '{{.Names}}'` | 本地 Docker socket 不存在，未执行真实 ES 集成、性能压测或线上数据对账 |

## 验收覆盖

| Acceptance | Evidence | Status |
|---|---|---|
| AC-01 历史分母及未来用户排除 | E-002 | PASS |
| AC-02 日/周/月/年/区间去重 | E-002 | PASS |
| AC-03 登录来源限定及业务筛选 | E-002（查询契约和事实场景） | PASS |
| AC-04 零值及北京时间边界 | E-002, E-003 | PASS |
| AC-05 图表路由、两个入口、导出去重 | E-002 | PASS |

新算法同时查询参与率和实际登录人数时复用一次 PIT 快照。分页测试覆盖超时、分片失败、提前结束、重复游标及清理快照。其他指标仍走原路径；前端仅扩展 calculation 类型声明，未进行全量前端构建或浏览器验收。

## 部署和数据核对

1. 部署后端并完成正常启动的数据集配置刷新，确认两个数据集的 participation_rate、logged_in_employee_count 均为 calculation=login_participation。无需重建 ES 索引。
2. 检查 `mid_user_engagement_stat` 的 `metric_source=participation AND logged_in=true` 历史覆盖范围。该算法回溯索引所有已保留事实，没有报表开始日期下界；数据缺失时不能据此声称全历史人数完整。
3. 选取区间前登录、期间重复登录、期间首次登录、区间后首次登录四类用户，核对日/月/整体区间结果。部门分组按登录事实上的组织字段，分子分母保持相同业务筛选。
4. 上线样本验证查询耗时：读取量随累计登录人天数增加，内存为各组首次登录用户和期间用户集合；未提供生产性能保证。
5. 只改本地代码，没有执行 ES 写入、历史补数或部署；此前知识统计贮藏仍保留。

## 已知限制

- 当前数据是自然日事实，仅支持日及以上粒度。含时间的 OR/NOT、无法解析的时间条件，以及同时用多个时间维度分组会明确报错，避免产生没有唯一截止点的分母。
- “实际登录人数”在周/月/整段区间从人员日计数变为期间人数；“全员总数”“实际登录次数”保持原含义。
- 已保存组件的数字格式不会被覆盖；旧组件若仍以小数显示，可在组件中选百分比。新建指标默认百分比格式。
