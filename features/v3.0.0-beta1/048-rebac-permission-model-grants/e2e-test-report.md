# F048 可见性增量 E2E 覆盖报告

> 执行日期：2026-08-13
> 分支：`feat/3.0.0-beta1`
> 整体状态：**PARTIAL — 实现与真实 OpenFGA 集成通过，专用业务 E2E 和真实 MySQL/DM8 未执行**

## 1. 结论

本次单槽浅层 `visible`、来源投影、joined ID-first、department/file candidate-first、模型
inactive 生命周期和单 run 迁移均已实现并完成定向回归。116 隔离内存 Store 上的真实
OpenFGA v1.15.1 集成测试 5/5 通过，并发现、修复了 v1.15.1
StreamedListObjects 的 `result` 包络兼容问题。

当前不能给出生产发布 PASS：没有配置专用 F048 业务部署账号，也没有 disposable MySQL 与
DM8 DSN，因此真实 API E2E 为 6 skip，数据库集成的 2 个外部用例为 skip。正式发布仍须完成
[手工与运维验证清单](./e2e-checklist.md)，尤其是五类 joined 来源、5,001 容量、故障无 SQL
fallback、MySQL/DM8 和 D0～D6 迁移链路。

## 2. 自动化结果

| 验证层 | 结果 | 判定 |
|---|---:|---|
| T144～T188 各波次定向测试 | 全部通过 | PASS |
| Wave 13 后端回归 | 51 passed, 2 skipped | PASS；skip 为 MySQL/DM8 环境门控 |
| 116 OpenFGA v1.15.1 集成 | 5 passed | PASS |
| OpenFGA 客户端单测 | 16 passed | PASS |
| F048 扩展全集 | 562 passed, 7 skipped, 11 failed | PARTIAL；见 §5 |
| 专用真实 API E2E | 6 skipped | NOT RUN；未设置 `F048_E2E=1` 和专用账号 |
| Platform 可见性增量 | 3 files / 24 tests passed | PASS |
| Client GrantTab 增量 | 9 tests passed | PASS |
| Platform / Client ESLint | 两端全量通过 | PASS |
| Platform / Client strict typecheck | 361 / 1214 strict files passed | PASS |
| `pnpm check-i18n` | no new i18n drift | PASS |
| Ruff（本次后端范围） | all checks passed | PASS |
| Architecture Guard / `git diff --check` | passed | PASS |

## 3. 真实 OpenFGA v1.15.1

环境为 `192.168.106.116` 上只监听 `127.0.0.1:18080` 的隔离内存实例，通过 SSH 本地转发
执行测试；每个测试创建并删除自己的 `f048-integration` Store，不写业务 Store。

| 项目 | 证据 |
|---|---|
| 版本 | v1.15.1，commit `1db35fb8b33d7512666e49e6b75cbd2cca8c4694` |
| 二进制 SHA-256 | `e54deb580c4de50dbd61d689ced8a6b8ed0ed26024add74def1b0a392c512a9c` |
| 测试 | `F048_OPENFGA_INTEGRATION=1 ... pytest test_f048_openfga_integration.py -q` |
| 结果 | `5 passed` |

覆盖单槽模型结构（无 A/B/switch）、direct/department/group/system、具体 action 不展平、
Check/BatchCheck/StreamedListObjects 集合一致、higher consistency、Store-scoped legacy tuple
删除、Write 原子性及 resolve depth。

首次运行暴露真实 v1.15.1 NDJSON 行为为：

```json
{"result":{"object":"workflow:direct"}}
```

客户端此前只接受顶层 `object`，会把正常流误判为不完整。修复后同时兼容 v1.15.1 包络和兼容
代理的未包络形式，单测 16/16、真实集成 5/5 通过。

## 4. 可见性增量覆盖

| 合同 | 自动化证据 | 状态 |
|---|---|---|
| Grant 即可见、模型 inactive 不撤权 | visibility compiler / grant policy / migration tests | PASS |
| 多来源最后撤销才删除聚合 tuple | visibility projection/reconcile tests | PASS |
| 单资源、BatchCheck、完整 stream 同语义 | permission service + 真实 OpenFGA | PASS |
| joined 为完整 visible ID-first、排除本人、管理员无扩权 | `test_space_joined_visible_ids.py` | PASS |
| joined 5,000 上限与无静默截断 | permission service / joined tests | PASS |
| department 候选后一次分块 BatchCheck | department permission tests | PASS |
| file 跨批扫描、稳定 cursor、最终子项 visible | file pagination tests | PASS |
| OpenFGA 异常无 SQL fallback | permission service / business authorization tests | PASS |
| 来源/列表指标与告警、不记录 PII | visibility observability tests | PASS |
| inactive 行两端保留、target 过滤、精确 MOVE/REMOVE | Platform 5 tests / Client 9 tests | PASS |
| 删除零引用/零 residual、停用非前置 | ModelEditor / catalog / D4 verifier tests | PASS |
| 旧系统单 run 迁移、无 A/B 或二次迁移 | migration CLI/coordinator/verifier tests | PASS |

## 5. 未关闭的环境项与基线项

### 5.1 环境门控

- 真实 MySQL/DM8：新来源投影表、唯一键、索引、cursor/checkpoint 和 contribution 用例已编写，
  但未提供 `F048_MYSQL_TEST_DSN` / `F048_DM8_TEST_DSN`，2 个 live 用例跳过。
- 真实业务 API E2E：`test_e2e_f048_permission_model_grants.py` 使用
  `e2e-f048-permission-` 前缀双重清理；当前未提供专用部署和三类账号，6 个用例跳过。
- 页面手工验证、5,001 条真实容量、OpenFGA 故障注入、D0～D6 迁移及生产脱敏 BENCH
  尚未执行，不能据此批准发布。

### 5.2 F048 扩展全集的 11 个失败

`pytest test/permission/test_f048_*.py ...` 得到 `562 passed, 7 skipped, 11 failed`。复跑首个失败
及相关单文件后，失败边界为：

- decision/grant/dashboard 的旧 HTTP/Service 测试没有注入新的 async `permission_actor` 身份解析
  依赖，单文件同样会尝试初始化未注册的 `permission_runtime`；这是测试 harness 未随共享身份
  入口更新，不是此次 visible 集合断言失败；
- 既有 domain-boundary 测试仍识别到 `grant_subject_service.py` 中 5 个历史业务 ORM import；
- 两个 Linsight 用例的预期错误文案仍为旧 `F048 OpenFGA runtime`，当前实现返回
  `permission runtime is not ready`；
- 一个 migration runtime 用例只在扩展全集顺序下缺少 tenant Context，单独复跑通过，属于测试
  Context 隔离问题。

这些失败未指向本次单槽 visible 语义结果不一致，但仍是可复现的历史测试/架构债务，不能将
“扩展全集”标成 PASS。若发布门禁要求整个 F048 历史全集全绿，应先修复共享测试 harness、
domain boundary 与 Context 隔离后复跑。

## 6. 发布判定

本次开发代码可进入后续专用集成环境验证；当前报告判定为 **PARTIAL**，不是发布批准。
完成清单中的真实 MySQL/DM8、业务 API/UI、故障注入、5,001 容量和 D0～D6 后，才可将状态
更新为 PASS。
