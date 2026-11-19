# F118 选中目录继承修复与退役私有库保留

基线 `af009d929348d38a2f69a20cd63463ed5b8c278e`。升级继续执行时发现两类历史准备阻塞：活动库目录完全缺少 mode/FGA 关系；退役 type=2 私有库文件也被要求补权限。用户明确确认选中目录应继承父库，旧私有库保留且不新增授权。本修复落实 F118 AC-115/116 的保留、显式准备及同计划恢复规则，不改正式 M2 的图或 checkpoint 合同。

## 决策与行为

- `prepare_f118_history.capture` 在父链/归属校验后保留 type=2 文件/文档，不为其修层级、补 mode 或父边。正常 type=0/3 的 mode 缺失检查保持；不因此忽略不合法父链或外租户事实。
- 独立 `repair_f118_folder_inheritance.py` 只处理升级人员明确选择并确认继承的目录。默认预览，保存不可覆盖的 0600 计划；apply 必须 `--confirm-inherit`，后续重试读原计划/操作者。已有 mode、Grant、visible-source、FGA 关系或其他台账拒绝；续跑只认可本计划的原操作。
- 小范围计划冻结目录/祖先/Root 原值、CURRENT pin、父权限 mode 及父 FGA 原事实。父目录先于子目录；每次写入复查本目录及祖先，不逐项重扫全部兄弟目录。
- 纯继承计划只有 5 个 WRITE：父边、两类主体的 inherit_mode、两类主体的 permission_enabled。`HISTORICAL_INHERIT_REPAIR` 区别新建资源，不伪造 CREATOR、不生成 owner/人员/角色 Grant，不改业务行。使用原生 control-state `prepare_owner` 空 Grant 分支建立 version=0 的 PENDING/PROJECTING mode 和原操作围栏，再由原生 ProjectionService 验证/finalize 到 CURRENT/version=1；脚本不直接写 FGA、不强制 SQL 状态。
- 核对完整原生台账、before/after checksum、版本/操作围栏；FAILED_CLOSED 的续跑只允许冻结键的 WRITE 修正，由已有 checksum-bound recovery 服务完成。未知提交、stage/finalize 中断和原 PREPARED 尚未绑定 mode 都保留原操作恢复。已完成资源只校验，不再次写入。
- 全程要求停写且无冻结 F118 Run。维护上下文复用 `f048_maintenance_runtime`，使用服务配置和 DB/Redis/读 pin 的 FGA，显式关闭全部拥有的资源，不启动 FastAPI、发布模型或初始化存储。
- 原历史计划不编辑、不覆盖。原 apply 完成既定清理并报告 blocked 后，串行执行选中修复；用不同文件名捕获后续历史计划重新复核。只有新计划 `blocked=[]`、apply `preparation_complete=true` 才能进入正式迁移。

## 验证

新增 21 项原生 SQL 测试，FGA 传输严格拒绝重复 WRITE，恢复与 SQL/projection 逻辑未 mock。覆盖：

- 显式选择、父子顺序、原文件字段和父权限保持、无新增 Grant、复跑无重复写。
- PREPARED 未建立 mode、FGA 提交后、SQL finalize 后中断；部分 COMMIT 进入 FAILED_CLOSED 后原台账前向恢复。
- 路径、租户、根类型、根 mode、外租户 mode、pin、FGA 新关系或条件改变时拒绝，且不覆盖后续模式修改。
- 无显式继承确认时不初始化运行时；旧私有库文件保持，不能用继承修复入口为其补权限。
- 原历史计划完成选中项但仍报告 blocked → 独立继承修复 → 新历史计划复核/apply ready 的完整链路，原文件字节保持。

组合回归：`test_folder_inheritance_repair`、历史准备/业务/物理/恢复/性能、权限迁移、namespace、转换计划/仓库、结构保留及 F048 投影/SQL/恢复 CLI，**318 通过**（41.82 秒）。Ruff format/check/F821、架构守卫、CLI 帮助及 diff 空白检查通过。SQL 使用现有双库 ORM/类型，没有 DDL；真实 DM8 本轮未执行。

### 查询成本

选中最多 20 目录/200 祖先，父 tuple 最多 500；相关表各枚举最多 200 个 distinct tenant key。枚举使用 tenant-leading 索引，再按 tenant/resource/scope 索引取选中事实，包含外租户候选，不以当前租户过滤掩盖冲突。Grant/visible 只作 limit-1 存在性证明，journal 最多选中数+1；不加载整个授权表或所有来源 payload。超限明确拒绝，不抽样。

本机原生 SQLite + 严格 FGA 传输，独立兄弟目录的完整 apply：

| 目录数 | SQL | commits | FGA 写请求 |
|---:|---:|---:|---:|
| 4 | 139 | 29 | 8 |
| 8 | 267 | 57 | 16 |

每增加 4 个目录增加 SQL 128、commits 28、写请求 8，按选中规模线性增长。本次不把本机耗时用作维护窗口估算。

实际 MySQL 的只读 EXPLAIN 核对：mode tenant 枚举使用 `ix_resource_permission_mode_tenant_id` range / index for group-by；选中 modes 使用 `uq_resource_permission_mode` range；journal 枚举及选中范围使用 `ix_perm_projection_scope` range，选中资源估算 3～4 行。未执行该补充脚本的真实权限写入来替代本地回归；现场执行独立记录于原 data 卷的运行日志/台账。

## 七维审查

按 `sdd-code-review`，对照 AC-115/116、D12、脚本完整变更自审。

| 维度 | High | Medium | 结论 |
|---|---:|---:|---|
| 边界条件 | 0 | 0 | PASS |
| 权限/认证/租户 | 0 | 0 | PASS |
| 并发/幂等/恢复 | 0 | 0 | PASS |
| 信息泄漏 | 0 | 0 | PASS |
| 测试覆盖 | 0 | 0 | PASS |
| 代码风格 | 0 | 0 | PASS |
| 文档同步 | 0 | 0 | PASS |

结论 PASS。用户确认继承是业务意图输入；脚本不自动推断任意缺失权限。该入口不作为通用资源创建/授权 API，也不放宽在线权限运行时。补充修复与已运行历史清理串行，保留原计划与所有原生证据。
