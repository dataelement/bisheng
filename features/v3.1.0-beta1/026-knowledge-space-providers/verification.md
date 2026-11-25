# F026 / Wave 6 发布验证记录（2026-11-25）

**决策：不放行。** T056 的验收入口和本地回归已完成；T005、T056 均保持未勾选（54/56）。没有发布扩展提交、已部署镜像摘要、专用双库实跑或真实测试租户的证据。未触发远端 CI、未提交、未部署。

## 测试对象与来源

| 对象 | 当前能证明的来源 | 不能据此认定 |
|---|---|---|
| BiSheng | `feat/3.1.0-beta1-cnnc`，HEAD `150dbe62b98ef0a0a5fa567706df2177dc7b94d1` 加本地工作树变更 | HEAD 自身不是包含 F026 的发布提交 |
| WeKnora | `upstream-dev/WeKnora` 的 `feat/f026-cnnc`，HEAD `f17ee8a8da901bd658a4cb25f40b5fd41adbfdd7` 加未提交扩展 | 不是已经构建或运行的扩展镜像；不得用 v0.9.0 原版代替 |
| 上游对照 | `dist/WeKnora` 位于同一 v0.9.0 提交，检查时工作树干净 | 仅用于核对，不是写入或部署目标 |

## 本轮已实跑

| 范围 | 结果 | 判读 |
|---|---|---|
| 隔离 SQLite 应用配置；`test/knowledge/test_f026_*.py` + Alembic single head | **312 passed, 7 skipped** | 6 个专用数据库参数项、1 个真实证据包入口跳过。不含真实 HTTP E2E。 |
| [双库账本](../../../src/backend/test/knowledge/test_f026_ledger.py)及夹具安全回归 | **18 passed, 6 skipped** | 3 个 SQLite 对照 + 15 个离线夹具测试。独立连接争抢、重开连接池、旧回写拒绝均有断言；不能代替实际方言。 |
| `F026_REQUIRE_REAL_DBS=1`，无两个专用 DSN | **3 passed, 6 setup errors，退出 1** | 两个 DSN 冒用 SQLite 的负控也退出 1。缺方言不是通过，不会连接默认业务库。 |
| [真实 API 入口](../../../src/backend/test/e2e/test_e2e_f026_provider_release.py) | 默认 **4 skipped**；显式启动但无测试基址则 setup 报错 | 首次请求前停止。实际 Native/WeKnora 检索、引用点击、双普通账号与浏览器均未验。 |
| [证据包门槛](../../../src/backend/test/knowledge/test_f026_release_contract.py)，`F026_REQUIRE_RELEASE=1` | **7 passed, 1 failed，退出 1** | 七项仅验证检查器本身，含总数矛盾、多余用例、错误模块三种报告拒绝。缺少审核后的目标构建证据包，失败符合预期。 |

**故障断言单独复跑：** `test_department_lost_ack_only_reads_original_id_before_grant`、`test_durable_freeze_ready_barrier_and_single_unresolved_settings_write`、`test_workflow_identity_and_revocation`、`test_scan_proof_admission_and_crash_recovery` 共 4/4 通过。这是本地应用级夹具对丢 ACK、就绪屏障、撤权及过期租约接管的证据，已包含在组合测试范围内；不计作目标部署的故障演练。真实服务入口另经 `--collect-only` 核对，Native / WeKnora 的检索与引用共 4 项可发现，无网络请求。

**本轮发现并修复：** Work 实际 `POST /knowledge/space/retrieve` 曾在外部库绑定就绪、空间行未携带后端提示时走入 Native 路径。先行路由测试 1 失败、1 通过；修复后按请求装配 Provider，只发送当前用户可见候选，并过滤远端多返回项。相邻组合 **58 passed，另有 8 个 subtests 通过**（[路由回归](../../../src/backend/test/knowledge/test_f026_work_release_wiring.py)）。这是 ASGI + SQLite + 测试传输证据，不是实服证明。上述测试选择有重叠，不累加计数。

## 接手执行顺序

1. **确定测试版本。** 在另行授权的构建流程固定 BiSheng 与扩展 WeKnora 的实际提交、不可变镜像摘要、前端构建、能力修订与权限模型。当前工作树未发布。尤其确认外部上传的签名主体、可核验回执和用户/租户双预算；仍为 `unverified` 时，应记录必做上传用例未满足，不能以“正确拒绝”代替成功上传。
2. **双库。** 在受保护的 `f026-ledger-ci` runner 内配置专用 `F026_TEST_MYSQL_URL`、`F026_TEST_DM8_URL`（只通过 secret store）。两边都需要独占、空的 `f026_test_*` schema 和同名限权账号；不能使用业务库或已迁移的共享库。手工触发[账本 CI](../../../.github/workflows/f026-ledger.yml)。九个具名用例全过且无跳过才归档脱敏 ledger.xml 及 provenance.json；这不是整个应用迁移或真实 Worker 恢复的证明。
3. **真实 Native、WeKnora 与引用。** 准备非生产租户、两个不同的非管理员账号、已知的单文件双空间和已生成引用。按[夹具与安全命令](./e2e-checklist.md)注入 `F026_E2E_*`，只运行指定文件并生成 `--junitxml=<受控目录>/live.xml`；四个具名测试均须实际执行并通过。管理员或未命中结果不能替代授权正例。不要在对话、记录或制品中放 token、原文、原始响应、签名链接。
4. **受控演练与界面验收。** 用隔离的应用级夹具执行丢 ACK、半登记、撤去最后权限、双侧恢复时点不同和旧代次迟到。按原操作/资源/版本对照两侧脱敏证据，确认不重复写入、不暴露旧内容、Native 不受影响；再恢复测试基线。没有夹具不得直接改账本、停生产服务或模拟通过。浏览器走查及未覆盖场景见[手工清单](./e2e-checklist.md)与[55 个 QA 用例、37 项 AC 追溯](./test-cases.md)。当前这些目标环境结果均非通过。
5. **检查证据包后再做发布决策。** 仅从可信 CI/验收负责人获取工件。根目录 `manifest.json` 指定 `feature=F026`、`environment=dedicated-integration`、双方 `bisheng_commit`/`weknora_commit`（完整 SHA）、`bisheng_image`/`weknora_image`（sha256: 加 64 位十六进制）。`ledger`、`ledger_provenance`、`live`、`qa` 各为 `{file, sha256}`，文件都在同目录，不是 URL。`qa` JSON 复列双方提交/镜像，以及与清单一致的 `live` 工件引用；`cases` 以 `TC-KSP-001` 至 `TC-KSP-055` 为键，各项须有审核人 `reviewer`、`outcome=passed` 与指向实际脱敏观察文件的 `observation:{file,sha256}`。如果任何一项失败/未验，如实记录，检查应不通过。

```sh
# 在 src/backend，F026_RELEASE_EVIDENCE 由受保护作业设置为本次证据包目录
F026_REQUIRE_RELEASE=1 .venv/bin/python -m pytest -q --tb=line \
  test/knowledge/test_f026_release_contract.py::test_target_release_evidence
```

检查器验证完整性、用例执行状态、账本 CI 提交与报告摘要、人工观察记录和构建的一致性；它不验证签名或替审核人判读证据，也不会触发发布。来源未经确认的包，即便通过格式检查也不得放行。
