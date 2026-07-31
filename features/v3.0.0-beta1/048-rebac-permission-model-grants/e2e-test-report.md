# F048 E2E 覆盖报告：ReBAC Permission Model Grants

> 执行日期：2026-07-30
> 分支：`feat/v3.0.0-beta1/048-rebac-permission-model-grants`
> 整体状态：**NOT RUN BY SCOPE — 实现验证通过，本地真实环境 E2E 经用户确认不执行**

## 1. 结论

F048 的功能实现、契约测试、迁移脚本专项、两端权限 UI 专项测试、生产构建、
架构守卫和新增代码质量检查已通过。用户于 2026-07-30 明确确认本地不执行
真实环境 E2E，因此专用 API、OpenFGA v1.15.1、MySQL/DM8、D0～D6 启服链路和
生产分布 BENCH-01 在本次开发完成口径中记为 `NOT RUN BY SCOPE`。

这不是实现失败，也不是生产发布批准。本报告保留未执行范围和后续清单，防止把
“功能与迁移脚本开发完成”误解为“目标部署环境已验证”。

## 2. 本次环境

| 项目 | 结果 |
|---|---|
| 工作区 | `/Users/zhangguoqing/works/bisheng` |
| Python | 仓库 `src/backend/.venv` / Python 3.11 |
| Platform / Client | 仓库现有 Node 依赖 |
| Backend | 未启动；`http://localhost:7860/health` 连接失败，HTTP `000` |
| Docker | 本次范围决策后未用于 F048 验证；未启动 F048 容器或持久化测试数据 |
| OpenFGA | 无可用的 disposable v1.15.1 实例和 digest 元数据 |
| MySQL / DM8 | 无两套 disposable F048 schema DSN |
| BENCH fixture | 仅 synthetic CI harness，`production_derived=false` |
| 已知集成主机 | `192.168.106.116` 网络可达，但当前会话 SSH 认证失败；未执行任何远程写操作，也无法确认其是否为专用 F048 环境 |

## 3. 自动化结果

| 验证层 | 命令摘要 | 结果 | 判定 |
|---|---|---:|---|
| F048 后端专项 | `pytest test/permission/test_f048_*.py ...` | 394 passed, 7 skipped | 实现 PASS；真实环境项未执行 |
| 本次变更文件回归 | 107 个已修改/新增 backend 测试文件 | 913 passed, 13 skipped | PASS；skip 均为显式外部环境门控 |
| 部门/SSO/组织同步整目录 | `pytest test/department test/sso test/org_sync` | 446 passed | PASS |
| BENCH-01 合同 | `pytest test_f048_performance_contract.py` | 12 passed | harness PASS |
| OpenFGA/DB gate | OpenFGA + database integration tests | 2 passed, 7 skipped | NOT RUN BY SCOPE |
| 真实 API E2E | `pytest test_e2e_f048_permission_model_grants.py` | 6 skipped | NOT RUN BY SCOPE |
| Platform 权限专项 | 13 个 F048/权限测试文件 | 57 passed | PASS |
| Client 权限专项 | 7 个 F048/权限测试文件 | 23 passed | PASS |
| Platform build | `npm run build` | success | PASS |
| Client build | `npm run build` | success | PASS |
| Python compile | 全部已修改/新增 backend Python | success | PASS |
| Architecture Guard | `scripts/arch-guard.sh` | success | PASS |
| Patch format | staged + unstaged `git diff --check` | success | PASS |
| 新增 Python Ruff/format | 127 个新增文件 | all checks passed / all formatted | PASS |
| 修改存量关键 Ruff | `ruff --select F,E9` | 本次引入项为 0；剩余 13 条为改动前基线 | PASS_WITH_BASELINE |
| 完整 permission 回归 | `pytest test/permission -q` | 540 passed, 7 skipped, 3 failed | 有既有基线失败 |

### 3.1 F048 后端专项

```bash
cd src/backend
uv run pytest \
  test/permission/test_f048_*.py \
  test/channel/test_f048_channel_permissions.py \
  test/knowledge/test_f048_preview_download_permissions.py \
  test/tool/test_f048_tool_permissions.py -q
```

结果：`394 passed, 7 skipped, 212 warnings in 3.41s`。

7 个 skip 均是显式外部环境门控：

- OpenFGA v1.15.1 disposable integration：5；
- MySQL/DM8 disposable schema integration：2。

覆盖 Catalog、action level 全模型重算、标准/自定义模型、Grant/source、
多 owner、INHERIT/CUSTOM、projection ledger、business verified target、
dashboard、preview/download、API/Worker/Linsight pin、D0～D6 coordinator、
legacy retirement、迁移脚本和 BENCH 合同。

### 3.2 真实 OpenFGA 与数据库

```bash
cd src/backend
uv run pytest \
  test/permission/test_f048_openfga_integration.py \
  test/permission/test_f048_database_integration.py -q -rs
```

结果：`2 passed, 7 skipped`。

- 2 个通过项证明 F048 Alembic revision 的静态 DDL-only 合同；
- 5 个 OpenFGA 测试要求 `F048_OPENFGA_INTEGRATION=1`、批准的
  `openfga/openfga:v1.15.1@sha256:<digest>` 和 runtime metadata；
- 2 个数据库测试要求 `F048_DATABASE_INTEGRATION=1`、专用 MySQL/DM8 DSN、
  schema 名含 `f048_test` 以及显式 destructive-test ack。

未执行项包括真实 Check/BatchCheck/ListObjects、同 Store 新 model、显式 model
tuple 写删、higher consistency、atomic Write、resolve node limit，以及 MySQL/DM8
upgrade、lease/checkpoint/resume/checksum 对齐。

### 3.3 BENCH-01

```bash
cd src/backend
uv run pytest test/permission/test_f048_performance_contract.py -q
```

结果：`12 passed`。当前仓库 fixture：

| 字段 | 值 |
|---|---|
| contract checksum | `12654227efbcdb9ebc2effdd1da5c668723cdcd96c4333eb621f0229b190dc14` |
| dataset checksum | `ad302adc12b1807080f85c238b36c7e93a75ef1c39165e6250a3138710f6e54b` |
| authorization model checksum | `edf2c67ebabf5cd24bd9d520181e50ee12c9cf667061488c6886db2253042ee4` |
| dataset source | `synthetic-ci-harness-only` |
| production derived | `false` |

合同和脚本会验证 Check、BatchCheck 20/50/100、ListObjects
direct/department/group/inherit/multi-grant、10/100/1000 结果、完整结果 checksum
以及业务 cursor + BatchCheck，并输出 P50/P95/P99、错误率、dispatch 和 datastore
query count。

synthetic fixture 即使使用 `--allow-synthetic` 也只能验证 harness，报告必须保持
`release_ready=false`。正式通过必须使用批准的脱敏生产分布 fixture。

### 3.4 两端前端

Platform：

```bash
cd src/frontend/platform
npm test -- --run \
  src/test/f048ActionLevelBoard.test.tsx \
  src/test/f048DashboardPermissions.test.tsx \
  src/test/f048ModelEditor.test.tsx \
  src/test/f048PermissionApi.test.ts \
  src/test/f048PermissionDialog.test.tsx \
  src/test/f048PermissionGrantTab.test.tsx \
  src/test/f048PermissionI18n.test.ts \
  src/test/f048PermissionRoster.test.tsx \
  src/test/f048RolesAndPermissions.test.tsx \
  src/test/knowledgeSpaceGrantSubjects.test.tsx \
  src/test/permissionHookCache.test.tsx \
  src/test/subjectSearchUser.test.tsx \
  src/test/systemPageTabsVisibility.test.tsx
npm run build
```

结果：`13 test files / 57 tests passed`，生产构建成功。除 12 个 F048/权限文件外，
同时覆盖 `systemPageTabsVisibility.test.tsx` 的系统管理页签边界。仅有存量
`jsx` DOM attribute、Browserslist 和 bundle size 警告。

Client：

```bash
cd src/frontend/client
npm run test:ci -- --runTestsByPath \
  src/api/permission.test.ts \
  src/components/ChannelMemberDialog.test.tsx \
  src/components/permission/PermissionDialog.test.tsx \
  src/components/permission/PermissionGrantTab.test.tsx \
  src/components/permission/PermissionListTab.test.tsx \
  src/components/permission/permissionI18n.test.ts \
  src/pages/knowledge/FilePreview/TopBar.test.tsx
npm run build
```

结果：`7 suites / 23 tests passed`，生产构建成功。仅有存量 Browserslist、
bundle size、PWA glob 和 runtime font 警告。

### 3.5 专用真实 API E2E

新增：
`src/backend/test/e2e/test_e2e_f048_permission_model_grants.py`。

它只在 `F048_E2E=1` 时运行，双重清理
`e2e-f048-permission-*` 工作流，覆盖：

- 四个标准模型和 Catalog 超管边界；
- 新资源 `CUSTOM`、受保护 creator owner 及禁止删除；
- viewer Grant 幂等新增、roster 唯一、具体 `visible` ALLOW 和 `delete` DENY；
- 非 `manage_permission` 用户不能读取 roster；
- 撤销后的随后读取立即 DENY；
- 跨租户业务目标不可解析；
- 无 canonical parent 的顶级 workflow 不能切换 `INHERIT`；
- 未登记 action 返回 `25001`。

本机执行：

```bash
cd src/backend
uv run pytest test/e2e/test_e2e_f048_permission_model_grants.py -q
```

结果：`6 skipped`，原因是未设置 `F048_E2E=1`，且本机 backend/Docker
确实不可用。正式命令和账号变量见
[E2E 手工与运维验证清单](./e2e-checklist.md)。

## 4. 完整 permission 回归的既有失败

```bash
cd src/backend
uv run pytest test/permission -q
```

结果：`540 passed, 7 skipped, 3 failed`。3 个失败全部位于
`test_f027_role_scope_nullsafe_unique.py`：

1. `test_upgrade_adds_scope_key_and_swaps_to_nullsafe_unique_constraint`
2. `test_upgrade_dedupes_existing_null_scope_collisions_before_creating_constraint`
3. `test_downgrade_restores_previous_constraint_and_drops_scope_key`

前两个失败是 F027 测试桩构造的 `role` table 缺少 `department_id`；第三个测试桩
与当前 F027 downgrade 的约束探测不一致。它们不经过 F048 revision、Catalog、
Grant、OpenFGA model 或新迁移脚本，本次没有扩大范围修复。F048 专项为全绿。

## 5. AC 覆盖状态

| AC 类别 | 自动化状态 | 仍需真实环境 |
|---|---|---|
| Catalog / action / model（AC-01～18、148～149、156） | Domain/API/UI 专项通过 | 真实发布确认、并发管理员、审计 |
| Grant / 来源 / owner（AC-19～27、36～44、157） | Domain/API/UI 专项通过 | 真实用户/部门/组成员变化链路 |
| Check / List / fail closed（AC-28～35、69～70） | adapter、合同和故障单测通过 | pinned OpenFGA、真实故障注入 |
| INHERIT / CUSTOM（AC-45～57、150～152） | mode/domain/adapter 专项通过 | 两端交互、真实移动/复制 |
| roster / explain（AC-58～65） | 两端组件及 API 专项通过 | Platform/Client 浏览器清单 |
| dashboard（AC-153） | 后端与 Platform 专项通过 | 真实 dashboard 全动作与分享链接 |
| preview/download（AC-154） | 后端与 Client 专项通过 | 原件/打包文件真实 HTTP 下载 |
| business boundary（AC-155） | architecture/static/adapter 测试通过 | SQL/log 运行时观察 |
| 数据迁移（AC-71～147、158） | mapper/coordinator/CLI/DDL 合同通过 | MySQL、DM8、D0～D6 维护窗口 |
| 性能（AC-28～35、69） | BENCH harness 合同通过 | production-derived fixture 正式跑数 |

## 6. 未执行的生产发布验证项

若后续需要确认某个目标环境可发布，仍应补齐以下四类证据：

1. **真实 OpenFGA**：批准的 v1.15.1 tag@digest、runtime metadata、同一 Store、
   一个新 runtime model、5 个集成测试全部通过；
2. **真实数据库和迁移**：MySQL 与 DM8 disposable integration 全绿，并在维护窗口
   完成 D0～D6、全实例 heartbeat/pin 和旧 tuple/Config 清理证明；
3. **真实 API/UI**：专用 E2E 6/6 通过，并完成 Platform、Client、dashboard、
   preview/download、故障注入、跨租户、Worker/Linsight 清单；
4. **正式 BENCH-01**：批准的脱敏生产分布 fixture，`production_derived=true`，
   所有阈值通过且 `release_ready=true`。

本次按用户确认不继续建立本地 E2E 环境。已知主机
`root@192.168.106.116` 在 2026-07-30 的只读 SSH 探测中返回认证失败，因此本轮既没有
取得容器/版本证据，也没有对该主机、数据库或 OpenFGA 做任何修改。

本次范围结论：

- T140 以“记录范围决策和未执行证据报告”收口；
- 可以确认 F048 功能、DDL 与正式数据迁移/校验脚本开发完成；
- 不把该结论表述为目标环境已完成发布验证；
- 不执行生产数据迁移；
- 不声明 OpenFGA 性能无损；
- 不通过 model A/B、切 Store、预演或应用级回滚规避门禁。
