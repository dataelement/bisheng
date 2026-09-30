# 科室指标导出验证记录

- Feature ID: `068-office-metrics-export`
- Updated: `2026-09-30`
- Overall Status: `PASS_WITH_WARNINGS`（目标容器已按用户确认的 parent_id 和 raw 历史兼容口径完成导出及独立复算；历史完整性限制保留）

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
| E-012 | 新增 parent_id 路径恢复、环路及缺父节点用例 | 修复前 3 failed；修复后 22 passed | 生产旧路径回归，输入不被修改 |
| E-013 | `.venv/bin/python -m pytest -q test/scripts/test_export_office_metrics.py --tb=short`（raw 策略完成后） | PASS，24 passed，exit 0 | 旧事件重复、看板独有记录不叠加、双标识缺失拒绝及原严格模式回归 |
| E-014 | 最终脚本及测试 ruff check、脚本 py_compile、CLI --help、git diff --check | PASS，exit 0 | 最终静态及参数检查 |
| E-015 | 目标容器运行下述命令 | EXPORT_EXIT=0 | 真正数据库/ES 读取，8 个 CSV，正式汇总 11 行 |
| E-016 | 容器 `/app/verify-office-metrics-20260930.py` 独立按明细集合复算 | VERIFY_EXIT=0，全部 11 行数量/比例一致 | 5 类库、跨库并集、登录事件、三类问题、两级分母；33 条比例、CSV BOM/编码/结构/行数、无 ERROR |

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
| V-004 | E-015, E-016 | PASS_WITH_WARNINGS | 目标容器真实数据库/ES、实际组织映射、分页及明细对账通过；未证明上线以来历史完整性，未单独验证 DM8 |

数据库测试使用真实 SQLModel 查询和租户过滤器、精简 SQLite 表；全局夹具预模拟 User，因此测试用独立映射仅替代其读取的 user_id/user_name 两列。ES 使用只读协议 fake，问答事件另由实际 BaseTelemetryEvent/PortalQaEventData 序列化生成，以避免假数据字段与生产契约漂移。上述不能代替真实 MySQL/DM8/ES 集成结果。

## 目标环境验收步骤
1. 按 scripts/README.md 运行，传真实租户、公司、制造部 ID；科室名称不唯一时显式传 office-map。选择新输出目录，低峰期执行。
2. 确认来源诊断中的原始 ES 与看板 ES、三类索引扫描页数、时间覆盖范围及十科室组织 ID。
3. 用知识明细中的文档键和计入范围重算贡献数及部门库分母；用登录/问答明细的去重计入标志重算次数。
4. 核对其他科室/直属人员进入制造部合计，且不进入十科室使用占比分母；部门比例分母对应公司全范围。
5. 若出现历史覆盖差异、缺索引或未知身份，先核验来源；脚本不授权或执行数据回填。缺少上线以来的日志时不能宣称恢复了全历史。

## 变更边界
最终交付一个脚本文件 export_office_metrics.py 及一个测试文件，修改 scripts/README.md 和本规格。脚本不依赖其他运维脚本；仍需现有毕昇项目的模型、配置及依赖。2026-09-30 已在用户授权的容器另存修正版并执行生产只读导出；原脚本和失败目录保留。未修改业务服务、数据库记录、ES 索引数据、租户过滤器或运行配置；未提交、未推送、未重启服务。

## 2026-09-30 目标容器实际执行

容器：`bisheng-backend-shougang-666578b775-cznz7 / container-4q4yry`，工作目录 `/app`，既有 Python 3.10.19。
原脚本 SHA-256 `c7d6deca5dd7f965e9457fe4541b8a517dd0c040c499b287145e897ce23c17b4`；最终本地与容器修正版校验一致：
`d7a31e36fa4ad35324812f0a8438134da40b3fe57a75e8cd4bc31976a0911272`。

```bash
python scripts/export_office_metrics_20260930_r2.py \
  --tenant-id 1 --company-department-id 2199 --manufacturing-department-id 2210 \
  --office-map /app/offices-manufacturing-20260930.json \
  --qa-history-policy raw --output-dir /app/office-metrics-20260930-r2 --verbose
```

- 运行日志：`/app/office-metrics-20260930-r2.log`；独立核验日志：`/app/office-metrics-20260930-r2.verify.log`。
- 十科室映射依次：2225、2231、2230、2232、2228、2229、2227、2226、3255、3219。2232 实名为质量精益室；初次终端误读已向用户纠正。
- 租户组织 1,714 个；直接父子路径不一致 266 处；按父链重建后 330 条路径差异写入诊断。未发现父链环路，数据库未回写。
- ES 实际分页：用户统计 participation 183,344 条；问答投影 597 条。数据库有效库存读取 18,978 个入口，按明细边界输出 18,360 行。
- CSV 行数（不含表头）：汇总 11、其他组织 1、知识明细 18,360、登录明细 1,115、问答明细 527、分子分母 33、统计口径 20、来源诊断 661。
- 制造部合计：公共库 213、部门库 1,317、科室库 85、团队库 31、个人库 2,005；跨库贡献数 3,637、贡献比 21.15%；登录 132、访问比 11.87%；智能问答 112、文档问答 20、专家问答 1、问答比 25.24%。
- 643 条 WARNING、无 ERROR：组织路径 330、组织归属 3、旧问答事件标识 113、缺少登录日投影 109、问答投影差异及策略汇总 88。登录未发现投影次数多于原始事件的缺口。
- 看板独有的 18 个问题未叠加（17 个智能问答、1 个专家问题）；17 个智能问答都存在同用户同秒的旧成功事件，但没有据此猜测合并身份。旧事件使用稳定事件 ID，不能保证按真实问题完全去重；用户已明确接受该边界。
- 重跑须换新输出目录。容器文件仅对当前容器可用；此次未把脚本打入镜像，也未修改服务启动流程。
