# 科室指标导出验证记录

- Feature ID: `068-office-metrics-export`
- Updated: `2026-09-29`
- Overall Status: `MANUAL_VERIFY_REQUIRED`（本地实现和自动验证完成；未在目标服务运行）

## 实际执行证据

除说明外，工作目录为 `src/backend`，使用已有 `.venv/bin/python` 和 `.venv/bin/ruff`，没有安装或更改依赖。

| Evidence | Command / Step | Result | Scope |
|---|---|---|---|
| E-001 | `.venv/bin/python -m pytest -q test/scripts/test_export_office_metrics.py --tb=short`（首次） | 预期失败：新计算模块未存在 | 先建立独立预期值样例 |
| E-002 | 同一命令下执行真实库存/组织查询用例 | 发现 JOIN 组织未被租户钩子识别；改为显式投影组织列后定向通过 | 跨租户、次组织、库存排除 |
| E-003 | `.venv/bin/python -m pytest -q test/scripts/test_export_office_metrics.py test/scripts/test_export_portal_category_usage.py test/scripts/test_export_expert_qa.py --tb=short` | PASS，41 passed | 当时新脚本17项 + 原有相关脚本24项 |
| E-004 | `.venv/bin/python -m pytest -q test/scripts/test_export_office_metrics.py --tb=short`（公司范围及 CASE 查询补充后） | PASS，18 passed，exit 0 | 最终新脚本行为；新增另一公司边界场景。E-003 的24项旧脚本证据复用，旧脚本未修改 |
| E-005 | `.venv/bin/ruff check scripts/export_office_metrics.py scripts/office_metrics_repository.py scripts/office_metrics_calculation.py test/scripts/test_export_office_metrics.py` | PASS，All checks passed | 最终新增 Python 文件 |
| E-006 | `.venv/bin/python -m py_compile scripts/export_office_metrics.py scripts/office_metrics_repository.py scripts/office_metrics_calculation.py` | PASS，exit 0 | 语法 |
| E-007 | `.venv/bin/python scripts/export_office_metrics.py --help` | PASS，exit 0 | 独立进程 CLI 导入/参数帮助，无数据库连接 |
| E-008 | 本次文件的 `git diff --check` 和新增文件 `git diff --no-index --check /dev/null <file>` | PASS，无空白错误输出 | README、新脚本和测试；未尝试修复已有无关文件的格式问题 |
| E-009 | 单文件合并前后 AST 比对 | PASS，21 个既有顶层函数/类保持一致（仅移除内部模块导入） | 行为保持；文档身份和节点日志函数从已有实现原样内置 |
| E-010 | `.venv/bin/python -m pytest -q test/scripts/test_export_office_metrics.py --tb=short`（单文件合并后） | PASS，19 passed，exit 0 | 原有18项复验，新增将单文件复制到隔离目录执行 --help、拒绝依赖其他脚本的测试 |
| E-011 | 单文件及测试 `ruff check`、脚本 `py_compile` 和 `--help` | PASS，exit 0 | 单文件最终静态检查及 CLI |

E-004 是多文件版本证据。用户要求合并后，最终代码证据以 E-009 至 E-011 为准；全部原有新脚本验收用例已在 E-010 复验，没有把代码阅读当成行为验证。

## 验收覆盖
| Acceptance | Evidence | Status | 证明范围 |
|---|---|---|---|
| AC-001 | E-002, E-004 | PASS | 子组织、主关系、重名映射、重叠拒绝、公司边界、固定十行 |
| AC-002, AC-003 | E-004 | PASS | 三库同文档只计一个贡献、库内分布、部门库外部贡献分母、成功库存过滤 |
| AC-004, AC-005 | E-004 | PASS | 原始登录去重、多轮问题、真实事件序列化、失败排除、专家问题无回答条件、两级分母 |
| AC-006 | E-004 | PASS | 八个 CSV、中文/数值读回、文件名公式防护、目录拒绝覆盖 |
| AC-007 | E-004 | PASS | PIT 完整分页、超时/分片/精确总数/重复游标/早停、缺索引、历史缺口不发布主表 |
| AC-008 | E-002, E-004 | PASS | 实际租户钩子 + ORM 查询、ES 跨租户拒绝、未知组织诊断、零分母、外部异常凭据不泄露 |
| V-004 | 无目标环境证据 | MANUAL_REQUIRED | 真实数据库/ES 数据、历史保留范围、实际组织映射、DM8 执行与全量耗时 |

数据库测试使用真实 SQLModel 查询和租户过滤器、精简 SQLite 表；全局夹具预模拟 User，因此测试用独立映射仅替代其读取的 user_id/user_name 两列。ES 使用只读协议 fake，问答事件另由实际 BaseTelemetryEvent/PortalQaEventData 序列化生成，以避免假数据字段与生产契约漂移。上述不能代替真实 MySQL/DM8/ES 集成结果。

## 目标环境验收步骤
1. 按 scripts/README.md 运行，传真实租户、公司、制造部 ID；科室名称不唯一时显式传 office-map。选择新输出目录，低峰期执行。
2. 确认来源诊断中的原始 ES 与看板 ES、三类索引扫描页数、时间覆盖范围及十科室组织 ID。
3. 用知识明细中的文档键和计入范围重算贡献数及部门库分母；用登录/问答明细的去重计入标志重算次数。
4. 核对其他科室/直属人员进入制造部合计，且不进入十科室使用占比分母；部门比例分母对应公司全范围。
5. 若出现历史覆盖差异、缺索引或未知身份，先核验来源；脚本不授权或执行数据回填。缺少上线以来的日志时不能宣称恢复了全历史。

## 变更边界
最终交付一个脚本文件 export_office_metrics.py 及一个测试文件，修改 scripts/README.md 和本规格。两个临时辅助模块已移除，脚本不再依赖其他运维脚本；仍需现有毕昇项目的模型、配置及依赖。未修改已有业务服务、租户过滤器或其他用户改动。未部署、未提交、未推送，未执行生产导出或 ES 迁移。
