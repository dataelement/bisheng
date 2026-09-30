# 验证记录 Verification：Token 配置化统一文件同步接口

## 阅读摘要

- 初版统一接口、固定目录目标增量和生产组合路由遮蔽修复 T001-T020、T022-T031 已完成；发布环境人工任务 T021 尚未执行。
- 最新路由聚焦回归：真实生产 `router_rpc` 用例及旧路由兼容用例 `13 passed`；Ruff、format、arch guard 与 scoped diff check 通过。
- 目录目标已覆盖旧 JSON 兼容、绑定用户权限过滤、必要导航祖先、游标、保存/换绑复核、固定目录上传、动态根目录、当前路径批量解析及外部响应不变。
- 54 条验收标准重新分级为 `51 PASS / 3 MANUAL_REQUIRED`；真实 MySQL/DM8、预发布切流与应用回退仍需 T021 留证。

## 元信息 Metadata

- Feature ID: `066-token-configured-filelib-sync`
- Status: `automated_verified; manual_release_verification_pending`
- Related requirements: `features/v2.6.0/066-token-configured-filelib-sync/requirements.md`
- Related tasks: `features/v2.6.0/066-token-configured-filelib-sync/tasks.md`
- Created: `2026-07-22`
- Updated: `2026-08-03`

## 验证摘要 Verification Summary

- Overall status: `AUTOMATED_VERIFIED_MANUAL_PENDING`
- Completed tasks: `T001-T020, T022-T031`
- Remaining tasks: `T021`
- Blocked tasks: `无`
- Automated conclusion: 目录目标实现与生产组合路由遮蔽修复通过本地自动化门禁，可进入隔离预发布验证。
- Release conclusion: T021 未完成前不得标记 Feature 级 `VERIFIED`，也不得据此修改真实 Token、route whitelist、调用方或数据库。

## 最新执行命令 Commands Run

| Command | Purpose | Exit Code | Result | Evidence |
|---|---|---:|---|---|
| Backend T030 red `uv run pytest test/open_endpoints/test_filelib_sync.py::test_production_router_reaches_sync_handler_for_missing_params -q` | 生产组合路由遮蔽复现 | `1` | `EXPECTED_FAIL` | 真实 `router_rpc` 响应缺少同步 handler 的 `data.error_code=19905`，断言 `KeyError: data`；对应实际 `knowledge_id=sync` 422 |
| Backend T031 green 同一生产组合用例 | 最小修复验证 | `0` | `PASS` | `1 passed, 6 warnings in 9.49s` |
| Backend `uv run pytest test/open_endpoints/test_filelib_sync.py -k 'route' -q` | 生产统一路由、旧编号路由与 route contract 回归 | `0` | `PASS` | `13 passed, 22 deselected, 6 warnings in 9.63s` |
| Backend `uv run pytest test/open_endpoints/test_filelib_sync.py -q` | 当前完整 Filelib 同步测试文件调查 | `1` | `BASELINE_FAIL` | `34 passed, 1 failed`；既有 service 调用 `enqueue_file_title_extraction`，旧 fixture 缺少该方法，与路由 diff 无关 |
| Backend `uv run pytest test/developer_token test/open_endpoints/test_filelib_sync.py test/open_endpoints/test_filelib_sync_token_rule.py test/open_endpoints/test_filelib_sync_folder_target.py -q` | T029 历史 DeveloperToken、Knowledge 目标树、Filelib 根/目录回归 | `0` | `HISTORICAL_PASS` | `164 passed, 6 warnings in 2.99s`；相关 service/test 状态此后已变化，不作为 T031 新鲜证据复用 |
| Backend `uv run ruff check` / `ruff format --check`（本次两个聚焦文件） | Python 静态与格式门禁 | `0` | `PASS` | `bisheng/api/router.py` 与 `test/open_endpoints/test_filelib_sync.py` 全部通过 |
| Backend `python -m py_compile`（Knowledge/DeveloperToken/Filelib service） | 修改服务语法验证 | `0` | `PASS` | 无输出 |
| Backend `uv run alembic heads` | 迁移拓扑与无新增 migration 复核 | `0` | `PASS` | `f066_token_file_sync_rule (head)`；本增量未增加 revision |
| `scripts/arch-guard.sh` + scoped `git diff --check`（本次两个文件） | 架构与差异空白卫生 | `0` | `PASS` | 无 WARNING/VIOLATION 或空白错误输出 |
| Platform `npx vitest run`（6 个 F066 定向文件） | 目标树、规则、API、切换隔离、摘要与静态门禁 | `0` | `PASS` | `6 passed files, 34 passed tests` |
| Platform `npm run build` | TypeScript/Vite 生产构建 | `0` | `PASS` | `8313 modules transformed`；仅既有 ace/Browserslist/eval/chunk 警告 |
| Platform `npx tsc --noEmit \| rg 'DeveloperToken\|developerToken'` | 聚焦 TypeScript 错误扫描 | `0` | `PASS` | 无 F066 相关输出 |
| `wc -l`（7 个 F066 相关组件/hook） | 单文件 600 行门禁 | `0` | `PASS` | 最大 `DeveloperToken.tsx=523`，其余均低于 600 |
| `git diff --name-only -- .../alembic/versions` | 本增量无迁移 | `0` | `PASS` | 无输出 |
| route/secret/source 扫描 | 统一路由、无明文 secret、无 Token 文件元数据 | `0` | `PASS` | 生产路由仅命中 `@router.post("/file/sync")`；日志只使用受控 Token ID，不包含 secret |
| `git diff --check` | 差异空白卫生 | `0` | `PASS` | 无输出 |

## 目录目标专项证据 Folder Target Evidence

- Schema/兼容：`folder_id` 只允许正整数或 `null`；缺失与 `null` 均解释为空间根目录；动态目标拒绝目录；没有新 migration/backfill。
- 权限主体：options、children、保存、同租户换绑和运行时均使用 Token 绑定用户，通过 `PermissionService` 检查 `upload_file`；管理员入口本身不授予目标权限。
- 最小披露：只查询公共/部门空间；深层目录授权只扩展必要祖先，祖先不可选，无关兄弟与文件不返回。
- 稳定目标：保存 `knowledge_id + folder_id?`；重命名或同空间移动按当前 ID/路径展示，删除、跨空间错配映射失效且不回退根目录。
- 上传：固定根使用 `parent_id=None`，固定目录使用 `parent_id=folder_id`，动态目标强制根目录；最终节点预检发生在临时文件保存前，`add_file` 保留二次权限校验。
- 性能：列表/详情按租户批量解析空间、目标目录和祖先路径；查询次数断言证明不会随 Token 数量线性增长。
- 外部契约：目录与根目录成功响应 fixture 字段完全一致，不新增 `folder_id` 或路径字段。
- 双库兼容：新增查询使用 ORM 与方言无关比较；空间作用域已有 `space_id` 唯一约束，因此移除 `DISTINCT + CASE ORDER BY`，避免 DM8 排序限制。

## 验收覆盖 Acceptance Coverage

| Acceptance ID | Requirement | Verification Method and Evidence | Status |
|---|---|---|---|
| AC-REQ-001-01 | REQ-001 | route/OpenAPI 与源码扫描仅保留统一 POST 路由 | `PASS` |
| AC-REQ-001-02 | REQ-001 | 11 个旧 URL 回归为 404 且 service 未调用 | `PASS` |
| AC-REQ-001-03 | REQ-001 | multipart、params、响应 fixture 与状态语义回归 | `PASS` |
| AC-REQ-001-04 | REQ-001 | 重复 external_file_id 保持非幂等上传语义 | `PASS` |
| AC-REQ-001-05 | REQ-001 | 真实生产 `router_rpc` 子进程回归命中同步 handler，缺参返回 19905 而非 `knowledge_id=sync` | `PASS` |
| AC-REQ-002-01 | REQ-002 | NULL/省略/显式清空规则及其他 Token API 回归 | `PASS` |
| AC-REQ-002-02 | REQ-002 | folder 缺失/null/正整数和 strict schema 矩阵 | `PASS` |
| AC-REQ-002-03 | REQ-002 | 分类必填、编码与请求不可覆盖固定分类 | `PASS` |
| AC-REQ-002-04 | REQ-002 | fixed/dynamic 真值表包含目录清空与动态拒绝目录 | `PASS` |
| AC-REQ-002-05 | REQ-002 | 跨租户及同租户换绑用户均重新校验目标 | `PASS` |
| AC-REQ-003-01 | REQ-003 | options 按绑定用户返回公共/部门分组与 cursor | `PASS` |
| AC-REQ-003-02 | REQ-003 | 分类稳定编码、父子关系和展示名称变化 | `PASS` |
| AC-REQ-003-03 | REQ-003 | 固定空间/目录类型、所属空间、租户和权限矩阵 | `PASS` |
| AC-REQ-003-04 | REQ-003 | fixed/fixed 保存及混合模式运行时绑定复核 | `PASS` |
| AC-REQ-003-05 | REQ-003 | 空间/目录失效、错配、移动及禁止根目录回退 | `PASS` |
| AC-REQ-004-01 | REQ-004 | department_id 缺失/合法/跨租户且无 fallback | `PASS` |
| AC-REQ-004-02 | REQ-004 | 责任人不存在、跨租户、零/多/唯一主部门矩阵 | `PASS` |
| AC-REQ-004-03 | REQ-004 | department_ids 精确零/一/多域匹配 | `PASS` |
| AC-REQ-004-04 | REQ-004 | F060 唯一/缺失/歧义目标空间与零上传副作用 | `PASS` |
| AC-REQ-004-05 | REQ-004 | 四种 fixed/dynamic 组合只解析动态维度 | `PASS` |
| AC-REQ-004-06 | REQ-004 | ID/名称一致性和文件元数据默认行为 | `PASS` |
| AC-REQ-005-01 | REQ-005 | Token/IP/route/rate 顺序保持，19812 优先 | `PASS` |
| AC-REQ-005-02 | REQ-005 | 无规则同步 403/19906，其他白名单 API 不受影响 | `PASS` |
| AC-REQ-005-03 | REQ-005 | 固定根/目录最终节点权限与权限撤销 | `PASS` |
| AC-REQ-005-04 | REQ-005 | 目录 IDOR、绑定用户主体、最小祖先披露 | `PASS` |
| AC-REQ-005-05 | REQ-005 | success/error/cancel 恢复租户 ContextVar | `PASS` |
| AC-REQ-006-01 | REQ-006 | 根/目录 `add_file(parent_id)` 与动态根矩阵 | `PASS` |
| AC-REQ-006-02 | REQ-006 | 固定编码、先持久化且只入队一次 | `PASS` |
| AC-REQ-006-03 | REQ-006 | 重复冲突、记录与临时对象清理边界 | `PASS` |
| AC-REQ-006-04 | REQ-006 | 身份元数据保留且无 Token ID/secret 元数据 | `PASS` |
| AC-REQ-006-05 | REQ-006 | 根/目录成功响应字段与排队语义一致 | `PASS` |
| AC-REQ-007-01 | REQ-007 | 公共/部门、根/目录单选且展开不选中 | `PASS` |
| AC-REQ-007-02 | REQ-007 | 租户/绑定用户切换清配置、缓存和旧请求 | `PASS` |
| AC-REQ-007-03 | REQ-007 | 结构化当前路径、移动重命名与 stale 摘要 | `PASS` |
| AC-REQ-007-04 | REQ-007 | 保存后刷新列表/详情，审计无 secret | `PASS` |
| AC-REQ-007-05 | REQ-007 | 独立组件/hook、build 与 600 行门禁 | `PASS` |
| AC-REQ-007-06 | REQ-007 | loading/error/empty/no-permission/stale 三语状态 | `PASS` |
| AC-REQ-008-01 | REQ-008 | nullable JsonType、disposable DB 升降级与 active head | `PASS` |
| AC-REQ-008-02 | REQ-008 | 既有行保持 NULL，迁移无 DML/backfill | `PASS` |
| AC-REQ-008-03 | REQ-008 | 自动化证明系统不改 Token/白名单；真实切流待 T021 | `MANUAL_REQUIRED` |
| AC-REQ-008-04 | REQ-008 | 已记录旧 strict schema 风险与处置；真实应用回退待 T021 | `MANUAL_REQUIRED` |
| AC-REQ-008-05 | REQ-008 | 本地矩阵通过；真实 MySQL/Linux DM8 待 T021 | `MANUAL_REQUIRED` |
| AC-REQ-008-06 | REQ-008 | 接口、目录、权限、错误、无迁移与回退文档 | `PASS` |
| AC-REQ-009-01 | REQ-009 | JSON folder 兼容、校验与无新 migration | `PASS` |
| AC-REQ-009-02 | REQ-009 | 动态目标拒绝目录并始终上传根目录 | `PASS` |
| AC-REQ-009-03 | REQ-009 | 仅公共/部门分组，排除团队/个人/文件 | `PASS` |
| AC-REQ-009-04 | REQ-009 | 加载/保存/运行时均按绑定用户失败关闭 | `PASS` |
| AC-REQ-009-05 | REQ-009 | 深层权限必要祖先不可选且兄弟隐藏 | `PASS` |
| AC-REQ-009-06 | REQ-009 | 空间搜索、目录 cursor、19814、展开与单选 | `PASS` |
| AC-REQ-009-07 | REQ-009 | 目录保存/换绑、19813 与失败不写库 | `PASS` |
| AC-REQ-009-08 | REQ-009 | 重命名/移动继续有效，删除/错配无 fallback | `PASS` |
| AC-REQ-009-09 | REQ-009 | 权限顺序、根/目录 parent_id 与二次校验 | `PASS` |
| AC-REQ-009-10 | REQ-009 | 目录成功响应与根目录字段完全一致 | `PASS` |
| AC-REQ-009-11 | REQ-009 | 批量当前路径、根标识、失效 ID 与无 N+1 | `PASS` |

## 安全复核 Security Review

- 目标配置不授予权限；options/children、保存、换绑和运行时均以 Token 绑定用户为主体。
- 目录树后端只返回授权最终节点和必要不可选祖先，不返回文件、团队/个人空间或无关兄弟。
- 最终节点校验发生在临时上传前；目录失效/错配返回 19903，无权限返回 19902，均不回退根目录。
- Token secret、密文、哈希和 Token ID 不进入文件元数据；审计仅记录非敏感规则摘要。
- 无效或跨上下文 cursor 映射 400/19814，不回到首页，避免重复/越权读取。
- 认证顺序仍为 Token 状态、租户/用户、IP、route whitelist、rate limit，再读取业务规则；19812 优先于 19906。

## 人工验证 Manual Verification

| Acceptance ID | Manual Steps | Expected Result | Actual Result | Status |
|---|---|---|---|---|
| AC-REQ-008-03 | 在隔离预发布逐 Token 配置并手工切换 route whitelist/调用方到统一 URL | 未配置为 19906；配置和白名单完成后只调用统一 URL；系统不自动修改配置 | 未执行，缺少预发布环境与发布负责人授权 | `NOT_RUN` |
| AC-REQ-008-04 | 备份配置，先执行保留列的应用回退；旧 strict schema 前清理/转换含 folder_id 规则或采用 forward fix | 应用回退不丢列；旧应用不因未知 folder_id 启动/读取失败 | 未执行，禁止未经授权修改真实应用或数据 | `NOT_RUN` |
| AC-REQ-008-05 | 在真实 MySQL 与 Linux DM8 执行 upgrade、既有 NULL 检查、smoke 与受控 downgrade | 两种方言成功，无 DML/backfill，行为与本地矩阵一致 | 本机 macOS 无 DM8 驱动，待 CI/预发布留证 | `NOT_RUN` |
| T021 发布门禁 | 用真实文件覆盖四组合、两种来源、固定根/目录、动态根、深层权限、stale/歧义/撤权、异步状态和旧 URL | 文件落到指定节点并排队；错误在上传前返回稳定码；旧 URL 404；UI 无越权或陈旧提交 | 未执行，等待隔离环境与授权 | `NOT_RUN` |

## 已知基线与限制 Failures and Gaps

- Platform 全仓 `npx tsc --noEmit` 仍为 exit `2`，尾部错误位于 `src/workspace/*` 等既有模块；过滤 `DeveloperToken|developerToken` 无输出，生产 build 通过。本任务未扩大范围修复无关 TypeScript 基线。
- `knowledge_space_service.py` 全文件 Ruff F 规则存在 5 个既有错误，位置为 2820、2979、4203、4208、11848；本次新增区域位于 465-906，`py_compile`、导入排序和聚焦测试通过，未顺手修改无关大文件历史问题。
- 真实 MySQL、Linux DM8、预发布 Token 配置、route whitelist、第三方调用方切换、旧 strict schema 应用回退和真实异步解析尚未执行；T021 保持未勾选。
- Vitest 出现既有 bs-ui `jsx` 非布尔属性警告；Vite build 出现既有 ace、Browserslist、依赖 eval 和大 chunk 警告，命令 exit code 均为 0。
- `features/` 被仓库 `.gitignore` 忽略，SDD 状态文件已写入工作区但普通 `git status` 不展示。
- 当前完整 `test_filelib_sync.py` 有 1 个与本 bugfix 无关的基线失败：`FilelibSyncService.sync()` 新增调用 `enqueue_file_title_extraction`，对应旧测试 fixture 尚未提供该方法；本次未扩大范围修复。

## 验证质量门 Verification Quality Gate

- [x] 54 个验收标准均有显式 `PASS` 或 `MANUAL_REQUIRED` 状态。
- [x] 目录目标使用新鲜后端、前端、构建、权限、查询次数与外部契约证据，没有复用旧 PASS 冒充。
- [x] Ruff、py_compile、arch guard、迁移、行数、安全扫描和 `git diff --check` 已执行。
- [x] 基线失败与 F066 聚焦通过分开记录，没有伪报全仓绿色。
- [x] T022-T029 自动化实施与验证已完成。
- [x] T030-T031 生产路由遮蔽回归已记录红灯/绿灯与新鲜聚焦证据。
- [ ] T021 预发布、真实双库、真实目录位置与切换回退尚未执行，Feature 保持人工发布验证待完成。
