# F054 验证报告

验证日期：2026-09-09。代码基线：`v3.0.0-beta1-fix` / `02592397a3706252c201a05ce68b0640a47fd1ef`。本报告记录提交前验证，未执行环境部署。

## 1. 覆盖与结果

| 范围 | 结果 |
|---|---|
| 完整 `test/permission/` + 新增组织仓储测试 | 821 passed、9 skipped、14 failed；14 个失败全部在未修改 tag 的临时 worktree 上复现，见下表 |
| 排除上述既有失败所在的 7 个文件 | 783 passed、9 skipped；该子集同时排除了这些文件内的其他通过用例，不代表完整套件全绿 |
| 原版 OpenFGA HTTP + SQLite 组织仓储 | 2 passed；独立 Store 在 finally 中删除并 GET 验证 404 |
| Ruff check / format | 通过；所有本次变更的 Python 文件 |
| arch-guard / git diff --check | 通过；守卫按仓库相对路径运行，绝对路径误报见 tasks.md |

AC-01/02：完整 F048 模型验证包含下级与直属成员分离。AC-03：下载/编辑的旧新模型 ALLOW/DENY 对照，删除/权限管理/授权等级、门禁撤销。AC-04：Check、跨 50 项边界的 BatchCheck、ListObjects、StreamedListObjects，以及 API/worker 装配。AC-05：新操作观察数据库成员移除、父级迁移，操作内复用、用户隔离、无永久展开写入。AC-06：40 层部门旧模型超限、新模型正常；另外覆盖 101 个输入、循环、缺失及非 CURRENT/归档。AC-07：无关身份不读取组织，旧 LLM 缓存不得参与子树关系判断。AC-08：发布扫描翻页、永久子树成员阻断、合法资源 userset 引用保留。

### 基线既有失败

| 文件 | 失败数 | 基线表现 |
|---|---:|---|
| test_f027_role_scope_nullsafe_unique.py | 3 | 迁移测试字段/约束预期不匹配 |
| test_f048_decision_api.py | 3 | API 测试身份/业务错误码预期不匹配 |
| test_f048_domain_boundaries.py | 1 | 既有 grant_subject_service 导入业务 DAO |
| test_f048_grant_api.py | 3 | 既有 API 测试运行时/响应契约失败 |
| test_f048_legacy_runtime_retirement.py | 1 | 前端已有退役契约引用 |
| test_f048_linsight_runtime.py | 2 | 启动失败错误消息与预期正则不符 |
| test_legacy_rbac_sync_service.py | 1 | 既有测试未装配 permission_runtime |

这些失败未通过删测试或修改无关业务代码隐藏。基线验证使用同一 Python 环境、同一 config 入口；临时基线 worktree 验证后清理。

## 2. 性能与深度验证

OpenFGA 二进制来自未修改的 `feat/dm` 基线 `eecdfd106d9466553c833cfb805c242228d4ab48`，内存 datastore；组织侧使用实际 Repository/Provider + SQLite，localhost HTTP，显式 HIGHER_CONSISTENCY。旧新模型共用测试 Store，差异仅为 subtree_member 定义。不能据此推断 DM8/MySQL 线上延迟或并发 SLA。

4681 个部门，4 条边的深度、每层分叉 8。下表每行是一轮十文件批量请求，均断言十项结果一致；旧路径从根部门向下展开，新路径含组织 SQL 查询成本：

| 动作与用户 | 预期 | 旧模型 ms | 新模型 ms |
|---|---|---:|---:|
| download / 子树成员 | ALLOW × 10 | 1268.14 | 21.43 |
| download / 外部成员 | DENY × 10 | 1602.31 | 15.62 |
| edit / 子树成员 | ALLOW × 10 | 1125.89 | 17.86 |
| edit / 外部成员 | DENY × 10 | 1582.69 | 17.59 |

另以 60 个空间做 30 轮 BatchCheck，每轮跨两个 HTTP 分块、组织 Provider 恰好读取一次：median 8.78 ms，nearest-rank p95 13.80 ms。两种列表 API 均返回完整 60 项，外部成员返回空集。

40 个部门构成单链（39 条边），叶子用户获根部门文件授权：旧模型 Check 抛出 FGAClientError，新模型 Check 允许；根部门的直属 member Check 仍拒绝。

## 3. 复现入口

在 `src/backend/` 执行，`config` 指向本机已有测试配置，禁止将敏感配置提交到仓库：

```bash
config=/path/to/config.yaml PYTHONPATH=. python -m pytest \
  test/permission/ test/department/test_permission_context.py -q

config=/path/to/config.yaml PYTHONPATH=. \
FGA_CONTEXTUAL_TEST_URL=http://127.0.0.1:18089 python -m pytest \
  test/permission/test_department_contextual_openfga.py -q -s
```

第二条须先在独立测试实例启动原版 OpenFGA。测试自行创建 Store，不接管已有 Store。普通回归默认跳过依赖外部实例的测试；本报告单独列出实际运行的 HTTP 集成结果。

## 4. 发布环境尚需验证

本次为权限模块及 OpenFGA HTTP 集成验证，不是完整毕昇 API/UI E2E，也没有在 192.168.106.105 部署新代码/模型。发布时补充：

- 使用 MySQL/DM8 验证祖先查询耗时、超时和多租户组织挂载。
- API、Celery、Linsight 启动并核对同一 model ID/checksum。
- 从业务 API 验证资源可见/编辑、仅直属和包含下级、成员移除/调岗、权限门禁撤销。
- 使用生产相同的缓存参数验证新旧上下文变化、完整列表与代表性并发负载。

## 5. beta1-test 合并验证（2026-09-09）

目标基线 `fa47f95942`，合入 hotfix `af3137d0d`。保留目标的公共空间语义后，组合模型为 `f048-v4-contextual-departments`，checksum 为 `1898712aa30c46354edbb1878f3bd9ebb17483926b39e696c1a13c29a6a1e733`，对应性能合同 checksum 已同步。目标的 F053 属于开放 API，部门优化文档在此分支编号调整为 F054。

- 86 项针对性回归通过：部门事实及请求上下文、模型、发布前检查、启动装配、审批有效直接用户列表、知识广场/已加入空间查询和性能合同。
- 2 项原版 OpenFGA HTTP 集成通过：组合模型下 4681 部门的 ALLOW/DENY 与旧部门遍历语义一致，40 层链仍可鉴权；测试 Store 删除后返回 404。
- 60 空间、30 轮批量检查：median 9.87 ms、p95 13.97 ms。环境仍为 SQLite + 本地内存 OpenFGA，不代表生产 SLA。
- Ruff 格式检查、架构守卫、差异检查通过；`knowledge.py` 存在 24 条目标基线原有 Ruff 诊断，逐规则/消息对照无新增，其他变更 Python 文件 Ruff 检查通过。未执行完整测试套件或部署。
