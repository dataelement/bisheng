# 任务拆分 Tasks：Token 配置化统一文件同步接口

## 阅读摘要

- 本文档保留初版 F066 的 T001-T020 历史完成记录，并按 Test-First 顺序规划固定目录目标增量；新任务计划等待用户确认。
- 每个任务必须保持在声明边界内，不得实现多规则、旧 URL 兼容、自动迁移或其他非目标。
- 本次目录目标不新增数据库迁移；既有 migration 任务仅为初版历史记录，不得在未获单独批准时对真实环境执行 upgrade/downgrade。
- F066 是 v2 内 breaking change；旧路由删除、Token 配置、route whitelist 和调用方切换必须通过发布清单协调。
- T001-T020 的旧证据不自动覆盖本次修订；实施结束必须更新 `verification.md`，没有目录目标的新鲜证据不得勾选新增任务或声称变更后的 AC 通过。

## 元信息 Metadata

- Feature ID: `066-token-configured-filelib-sync`
- Status: `route-shadowing bugfix complete; T021 manual verification pending`
- Related requirements: `features/v2.6.0/066-token-configured-filelib-sync/requirements.md`
- Related design: `features/v2.6.0/066-token-configured-filelib-sync/design.md`
- Created: `2026-07-22`
- Updated: `2026-08-03`

## 任务格式 Task Format

每个任务固定包含：可观察 Done when、`_Requirements`、`_Acceptance`、`_Verification`、`_Depends` 和 `_Boundary`。实施时只有在声明验证得到新鲜证据后才能把 `[ ]` 更新为 `[x]`。

## 阶段 1：实施基线与数据库 Foundation

- [x] T001 记录实施基线并编写迁移/模型失败测试
  - Done when: 记录当前 branch、工作区状态、Python/uv 环境和 Alembic active heads；新增测试证明当前 `developer_token` 尚无 `file_sync_rule`，并定义目标列为 nullable `JsonType`、upgrade 幂等、无 DML/backfill、表/列不存在保护和 downgrade 删除行为。
  - _Requirements: REQ-008_
  - _Acceptance: AC-REQ-008-01, AC-REQ-008-02, AC-REQ-008-04, AC-REQ-008-05_
  - _Verification: V-AC-REQ-008-01, V-AC-REQ-008-02, V-AC-REQ-008-04, V-AC-REQ-008-05_
  - _Depends: none_
  - _Boundary: read-only baseline and `test/developer_token/test_developer_token_migration.py` only; no production schema or live database mutation_

- [x] T002 新增 `file_sync_rule` 迁移并映射 DeveloperToken 模型
  - Done when: 新 revision 接实施时实际 heads；upgrade 只增加 nullable `JsonType` 列且既有行保持 NULL；downgrade 只在列存在时删除；ORM 增加对应字段；T001 迁移/模型测试转绿，disposable DB 升降级证据可观察。
  - _Requirements: REQ-002, REQ-008_
  - _Acceptance: AC-REQ-002-01, AC-REQ-008-01, AC-REQ-008-02, AC-REQ-008-04_
  - _Verification: V-AC-REQ-002-01, V-AC-REQ-008-01, V-AC-REQ-008-02, V-AC-REQ-008-04_
  - _Depends: T001_
  - _Boundary: one Alembic revision and `developer_token.py` ORM field only; do not execute a configured/live database upgrade_

## 阶段 2：Token 规则与管理服务 Token Rule Management

- [x] T003 编写 Token 文件同步规则 schema、CRUD 和固定引用失败测试
  - Done when: 参数化测试覆盖四种合法 fixed/dynamic 组合、空/多余/未知字段、编码规范、结构 422、跨字段 19813、创建/更新/未提交/显式 null、列表/详情返回、换绑租户重校验、分类父子、固定域/空间、固定-固定双向绑定、失效/跨租户引用及审计无 secret；当前实现按预期失败。
  - _Requirements: REQ-002, REQ-003, REQ-007_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-007-03, AC-REQ-007-04_
  - _Verification: V-AC-REQ-002-01, V-AC-REQ-002-02, V-AC-REQ-002-03, V-AC-REQ-002-04, V-AC-REQ-002-05, V-AC-REQ-003-02, V-AC-REQ-003-03, V-AC-REQ-003-04, V-AC-REQ-007-03, V-AC-REQ-007-04_
  - _Depends: T001_
  - _Boundary: new `test/developer_token/test_developer_token_file_sync_rule.py` and strictly necessary fixtures only_

- [x] T004 实现严格规则 schema、保存校验、读模型与审计
  - Done when: `DeveloperTokenFileSyncRule` 及子值对象使用 `extra="forbid"` 和已确认规范化；create/update 正确区分 omitted/null，按最终绑定租户校验分类、域、空间和固定绑定；新增 19813；list/detail/create response 返回非敏感规则；审计只记录规则摘要；T003 全部转绿。
  - _Requirements: REQ-002, REQ-003, REQ-007_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-007-03, AC-REQ-007-04_
  - _Verification: T003 tests + V-AC-REQ-002-01..05 + V-AC-REQ-003-02..04 + V-AC-REQ-007-03..04_
  - _Depends: T002, T003_
  - _Boundary: DeveloperToken schemas/exports/service, 19813 error, and repository persistence only; no options endpoint, auth principal or Filelib runtime changes_

- [x] T005 编写文件同步配置 options API 失败测试
  - Done when: API/service 测试定义 `tenant_id` 管理范围、无门户配置 19813、合法分类父子、enabled 域、有效目标空间、`PageData(data,total)`、page/limit/keyword、参数化搜索、多租户 IDOR、异常时租户 ContextVar 恢复，并证明 options 不授予 Token 用户上传权限。
  - _Requirements: REQ-003, REQ-005, REQ-007_
  - _Acceptance: AC-REQ-003-01, AC-REQ-005-04, AC-REQ-005-05, AC-REQ-007-02_
  - _Verification: V-AC-REQ-003-01, V-AC-REQ-005-04, V-AC-REQ-005-05, V-AC-REQ-007-02_
  - _Depends: T003_
  - _Boundary: DeveloperToken admin API/service tests only; no production endpoint edits_

- [x] T006 实现租户安全的文件同步配置 options API
  - Done when: `GET /api/v1/admin/developer-tokens/config/file-sync-options` 定义在动态 token 路由之前；先校验 admin scope，再在受控租户上下文读取既有 Portal Config/Knowledge 能力；知识空间支持受限分页和关键词；响应不包含权限授予或 secret；所有路径恢复上下文；T005 转绿。
  - _Requirements: REQ-003, REQ-005, REQ-007_
  - _Acceptance: AC-REQ-003-01, AC-REQ-005-04, AC-REQ-005-05, AC-REQ-007-02_
  - _Verification: T005 tests + V-AC-REQ-003-01 + V-AC-REQ-005-04..05 + V-AC-REQ-007-02_
  - _Depends: T004, T005_
  - _Boundary: DeveloperToken options schemas, endpoint and service orchestration only; no cross-module API import or manual tenant filter_

## 阶段 3：认证 Principal 与安全优先级 Authentication

- [x] T007 编写 DeveloperTokenPrincipal 与依赖生命周期失败测试
  - Done when: 测试定义一次认证返回 token ID、tenant ID、UserPayload 和 raw rule；现有 user dependency 仍兼容；missing/invalid/disabled/IP/route/rate 顺序保持；19812/限流先于 19906；损坏规则只阻断 sync；success/error/cancel 均恢复 current/visible tenant ContextVar；日志无 Token secret。
  - _Requirements: REQ-005_
  - _Acceptance: AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-04, AC-REQ-005-05_
  - _Verification: V-AC-REQ-005-01, V-AC-REQ-005-02, V-AC-REQ-005-04, V-AC-REQ-005-05_
  - _Depends: T003_
  - _Boundary: `test/developer_token/test_developer_token_dependency.py` and focused service tests only_

- [x] T008 实现 Principal 认证结果和兼容 user dependency
  - Done when: 新 `authenticate_principal()` 复用现有认证链且不二次查 Token；generator dependency 集中 reset；`get_developer_token_user` 委托 principal；统一同步规则缺失/损坏映射 403/19906；其他 Open Endpoints 行为不变；T007 转绿。
  - _Requirements: REQ-005_
  - _Acceptance: AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-04, AC-REQ-005-05_
  - _Verification: T007 tests + existing DeveloperToken dependency/API regression_
  - _Depends: T004, T007_
  - _Boundary: DeveloperToken auth service/dependencies/schemas, Open Endpoints dependency adapter, and 19906 error only; no Filelib business resolution_

## 阶段 4：固定/动态业务解析 Runtime Resolution

- [x] T009 编写 Filelib 规则解析与失败关闭矩阵测试
  - Done when: 参数化测试覆盖 fixed/fixed、fixed/dynamic、dynamic/fixed、dynamic/dynamic；`department_id` 与 `responsible_person_id` 两种来源；指定 ID 缺失无 fallback；责任人零/多主部门；ID/名称一致性；分类 code 父子；固定/动态域零/一/多匹配；固定空间；F060 动态空间零/一/歧义/父级解析；stale/cross-tenant；最终域-空间双向绑定，所有解析失败均发生在临时文件保存前。
  - _Requirements: REQ-003, REQ-004, REQ-005_
  - _Acceptance: AC-REQ-003-05, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-004-05, AC-REQ-004-06, AC-REQ-005-04_
  - _Verification: V-AC-REQ-003-05, V-AC-REQ-004-01, V-AC-REQ-004-02, V-AC-REQ-004-03, V-AC-REQ-004-04, V-AC-REQ-004-05, V-AC-REQ-004-06, V-AC-REQ-005-04_
  - _Depends: T004_
  - _Boundary: `test/open_endpoints/test_filelib_sync.py` resolver/rule cases and isolated fixtures only_

- [x] T010 实现租户安全、确定性的分类/域/空间解析
  - Done when: Filelib repository 删除按名称取第一条的固定查询，按现有租户机制校验责任人并返回完整主部门集合；Service 按 Token code/ID、唯一动态来源、Portal `domains[].department_ids` 和 F060 resolver 解析；零候选 19903、歧义 19904、无 fallback、运行时绑定复核；T009 转绿。
  - _Requirements: REQ-003, REQ-004, REQ-005_
  - _Acceptance: AC-REQ-003-05, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-004-05, AC-REQ-004-06, AC-REQ-005-04_
  - _Verification: T009 tests + V-AC-REQ-003-05 + V-AC-REQ-004-01..06 + V-AC-REQ-005-04_
  - _Depends: T009_
  - _Boundary: Filelib domain schemas/service/repository resolution methods only; no router removal or upload orchestration rewrite_

## 阶段 5：上传编排与统一路由 Upload and Route

- [x] T011 编写 Token 规则驱动的完整上传回归测试
  - Done when: 测试证明解析/权限在保存前完成；根目录、分类/子分类/域、`skip_approval=True`、`enqueue_processing=False`、固定编码、持久化先于一次入队、响应字段、排队语义、duplicate 409、失败清理、重复 external ID 非幂等、既有身份元数据及 `filelib_sync_endpoint="sync"`；文件元数据和日志无 Token secret/ID。
  - _Requirements: REQ-001, REQ-005, REQ-006_
  - _Acceptance: AC-REQ-001-03, AC-REQ-001-04, AC-REQ-005-03, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-006-04, AC-REQ-006-05_
  - _Verification: V-AC-REQ-001-03, V-AC-REQ-001-04, V-AC-REQ-005-03, V-AC-REQ-006-01, V-AC-REQ-006-02, V-AC-REQ-006-03, V-AC-REQ-006-04, V-AC-REQ-006-05_
  - _Depends: T010_
  - _Boundary: focused Filelib service interaction/failure tests only_

- [x] T012 把 Token 规则解析接入既有上传编排
  - Done when: `FilelibSyncService.sync()` 接收已认证 token ID/规则并按确认顺序解析；复用现有 KnowledgeSpaceService 上传、权限、编码、清理和 enqueue；来源元数据统一为 sync，Token ID 只用于受控日志；T011 及现有上传回归转绿。
  - _Requirements: REQ-001, REQ-005, REQ-006_
  - _Acceptance: AC-REQ-001-03, AC-REQ-001-04, AC-REQ-005-03, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-006-04, AC-REQ-006-05_
  - _Verification: T011 tests + existing `test_filelib_sync.py` upload/cleanup/encoding regression_
  - _Depends: T008, T010, T011_
  - _Boundary: Filelib service upload orchestration and strictly necessary dependency wiring only; do not alter Knowledge upload semantics or DB/Celery atomicity_

- [x] T013 编写统一路由、旧路由移除和契约失败测试
  - Done when: route/OpenAPI 测试定义只存在 `POST /filelib/file/sync`；11 个旧路径均 404 且 service 未调用；multipart 422/19905、请求/响应 fixture、19812 优先和其他 DeveloperToken Open Endpoints 回归得到覆盖。
  - _Requirements: REQ-001, REQ-005, REQ-008_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-005-01, AC-REQ-008-03, AC-REQ-008-05_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-02, V-AC-REQ-001-03, V-AC-REQ-005-01, V-AC-REQ-008-03, V-AC-REQ-008-05_
  - _Depends: T012_
  - _Boundary: Open Endpoints route/dependency contract tests only_

- [x] T014 注册统一接口并删除 11 个 handler 与静态规则表
  - Done when: 只保留 `POST /file/sync`；endpoint 通过 principal 注入 Token 规则和 ID；删除 `_sync_file(endpoint_code)`、11 个 handler、旧策略 enum/`FILELIB_SYNC_RULES` 及无用按名称代码；旧路径无重定向；T013 和所有 Open Endpoints 回归转绿。
  - _Requirements: REQ-001, REQ-005, REQ-008_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-005-01, AC-REQ-008-03, AC-REQ-008-05_
  - _Verification: T013 tests + route/OpenAPI source scan + existing Open Endpoints suite_
  - _Depends: T008, T012, T013_
  - _Boundary: Filelib router, Open Endpoints dependency injection and obsolete static rule/schema cleanup only; no compatibility route_

## 阶段 6：Platform 管理页 Platform UI

- [x] T015 编写前端规则验证、摘要和 API client 失败测试
  - Done when: Vitest 覆盖四组合、规范化、未知/失效 code/ID、模式切换清值、未配置/配置摘要、options query/分页类型和 create/update payload 的 omitted/null；当前实现按预期失败。
  - _Requirements: REQ-002, REQ-003, REQ-007_
  - _Acceptance: AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-003-01, AC-REQ-007-01, AC-REQ-007-03_
  - _Verification: V-AC-REQ-002-02, V-AC-REQ-002-03, V-AC-REQ-002-04, V-AC-REQ-003-01, V-AC-REQ-007-01, V-AC-REQ-007-03_
  - _Depends: T006_
  - _Boundary: `src/frontend/platform/src/test/developerTokenFileSyncRuleValidation.test.ts` and controller contract tests only_

- [x] T016 实现前端规则类型、API client、验证与摘要函数
  - Done when: controller 定义与后端一致的 rule/options/PageData 类型并使用现有 request wrapper；独立 validation 模块实现规范化、错误定位和本地化摘要数据；不引入新依赖；T015 转绿。
  - _Requirements: REQ-002, REQ-003, REQ-007_
  - _Acceptance: AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-003-01, AC-REQ-007-01, AC-REQ-007-03_
  - _Verification: T015 tests + TypeScript compile through Vitest/build_
  - _Depends: T015_
  - _Boundary: Platform DeveloperToken API controller and `developerTokenFileSyncRuleValidation.ts` only_

- [x] T017 编写配置组件、租户切换和主页面集成失败测试
  - Done when: 组件测试覆盖关闭/null、分类父子、fixed/dynamic 联动、动态来源显隐、options loading/error/search、存量失效值提示、绑定租户变化清空旧值、保存刷新、列表摘要、三语 key parity，并对所有相关 TS/TSX 文件设置 600 行门禁。
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03, AC-REQ-007-04, AC-REQ-007-05, AC-REQ-007-06_
  - _Verification: V-AC-REQ-007-01, V-AC-REQ-007-02, V-AC-REQ-007-03, V-AC-REQ-007-04, V-AC-REQ-007-05, V-AC-REQ-007-06_
  - _Depends: T016_
  - _Boundary: `src/frontend/platform/src/test/DeveloperTokenFileSyncRule.test.tsx`, focused DeveloperToken integration tests and i18n parity tests only_

- [x] T018 实现独立配置组件并接入 DeveloperToken 页面
  - Done when: 新受控 `DeveloperTokenFileSyncRule.tsx` 完成字段联动、可搜索空间 options 和失效提示；`DeveloperToken.tsx` 负责加载/提交/刷新并显示摘要；主文件与所有新文件不超过 600 行；zh-Hans/en-US/ja `bs.json` 同步；使用现有 bs-ui/request/useTranslation；T017 转绿。
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03, AC-REQ-007-04, AC-REQ-007-05, AC-REQ-007-06_
  - _Verification: T017 tests + focused Vitest + Platform production build + file line-count check_
  - _Depends: T006, T014, T016, T017_
  - _Boundary: Platform DeveloperToken page/component and `{zh-Hans,en-US,ja}/bs.json` only; no new UI/state/request library_

## 阶段 7：接口文档与发布契约 Documentation and Rollout

- [x] T019 发布统一接口文档并形成切换/回退清单
  - Done when: 新 `docs/api/filelib-file-sync.md` 完整定义统一 URL、Token 配置、动态必填 ID、响应/错误、权限、非幂等和示例；旧 split 文档只保留不含旧 URL 的迁移指针；发布清单明确现有 Token NULL、人工配置、人工 whitelist/调用方切换、无兼容、监控和应用优先回退；源码扫描仅历史 specs 允许出现旧路径。
  - _Requirements: REQ-001, REQ-008_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03, AC-REQ-008-02, AC-REQ-008-03, AC-REQ-008-04, AC-REQ-008-06_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-02, V-AC-REQ-001-03, V-AC-REQ-008-02, V-AC-REQ-008-03, V-AC-REQ-008-04, V-AC-REQ-008-06_
  - _Depends: T002, T014, T018_
  - _Boundary: the two Filelib API docs and F066 rollout/rollback documentation only; do not mutate Token, whitelist or deployment configuration_

## 阶段 8：初版自动化验收 Historical Verification

- [x] T020 执行全量定向验证并创建 `verification.md`
  - Done when: DeveloperToken/Filelib pytest、migration disposable DB、ruff check/format check、Alembic heads、Platform focused Vitest/build、i18n/600 行、arch guard、旧路由/静态表/secret 源码扫描和 `git diff --check` 均记录命令、exit code 与输出摘要；42 个 AC 均标为 PASS、FAIL、MANUAL_REQUIRED 或 NOT_RUN；未运行项不伪报。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008_
  - _Acceptance: AC-REQ-001-01..04, AC-REQ-002-01..05, AC-REQ-003-01..05, AC-REQ-004-01..06, AC-REQ-005-01..05, AC-REQ-006-01..05, AC-REQ-007-01..06, AC-REQ-008-01..06_
  - _Verification: all V-AC-REQ-* plus fresh `verification.md` evidence_
  - _Depends: T002, T004, T006, T008, T010, T012, T014, T018, T019_
  - _Boundary: tests, read-only quality commands, formatting limited to F066 touched files, and SDD verification/status docs only; no live database/config/external mutation_

## 阶段 9：固定目录目标增量 Folder Target Increment

- [x] T022 编写目录配置、权限树和当前路径的后端失败测试
  - Done when: 测试先证明旧 JSON 缺失/`null` `folder_id` 兼容根目录，动态目标拒绝目录字段；options/children 以绑定用户为主体，只返回公共/部门空间、授权目录及必要不可选祖先，隐藏兄弟/文件/团队/个人空间，支持空间搜索和统一目录游标，无效游标为 400/19814 且不回首页；保存/换绑覆盖 DIR、所属空间、租户、权限与不写库；列表/详情覆盖批量当前路径、移动/重命名、失效 ID 和固定查询次数；当前实现按预期失败。
  - _Requirements: REQ-002, REQ-003, REQ-005, REQ-007, REQ-009_
  - _Acceptance: AC-REQ-002-02, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-003-01, AC-REQ-003-03, AC-REQ-007-02, AC-REQ-007-03, AC-REQ-009-01, AC-REQ-009-03..08, AC-REQ-009-11_
  - _Verification: V-AC-REQ-002-02, V-AC-REQ-002-04, V-AC-REQ-002-05, V-AC-REQ-003-01, V-AC-REQ-003-03, V-AC-REQ-007-02, V-AC-REQ-007-03, V-AC-REQ-009-01, V-AC-REQ-009-03..08, V-AC-REQ-009-11_
  - _Depends: T020_
  - _Boundary: DeveloperToken/Knowledge focused tests and fixtures only; no production schema, endpoint, repository or UI edits_

- [x] T023 实现绑定用户权限过滤的目标树、保存复核和结构化路径
  - Done when: schema 增加可空 `folder_id` 且旧配置可读；options 接收绑定用户并返回公共/部门空间分组游标；children 通过 Knowledge 领域只读契约、PermissionService 和 `common/cursor.py` 返回最小目录树，无效游标映射 19814；保存/同跨租户换绑复核最终节点；list/detail 批量返回非本地化 `file_sync_target_display` 且无 N+1；T022 转绿，Endpoint 不直查 ORM。
  - _Requirements: REQ-002, REQ-003, REQ-005, REQ-007, REQ-009_
  - _Acceptance: AC-REQ-002-02, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-003-01, AC-REQ-003-03, AC-REQ-005-04, AC-REQ-007-02, AC-REQ-007-03, AC-REQ-009-01, AC-REQ-009-03..08, AC-REQ-009-11_
  - _Verification: T022 tests + PermissionService failure-closed/IDOR tests + repository query-count assertion_
  - _Depends: T022_
  - _Boundary: DeveloperToken schema/service/repository/endpoint and Knowledge domain Service/Repository read contracts only; no authorization tuple writes, migration or Filelib upload changes_

- [x] T024 编写固定根/目录、动态根和运行时失败关闭测试
  - Done when: 测试先覆盖固定根 `parent_id=None`、固定目录 `parent_id=folder_id`、动态目标强制根目录；DIR/所属空间/租户复核、重命名/同空间移动继续有效、删除/错配 19903 无 fallback、权限撤销 19902；显式权限预检先于临时对象/持久化，`add_file` 二次校验；目录成功响应与根目录字段完全一致；当前实现按预期失败。
  - _Requirements: REQ-003, REQ-005, REQ-006, REQ-009_
  - _Acceptance: AC-REQ-003-05, AC-REQ-005-03, AC-REQ-006-01, AC-REQ-006-05, AC-REQ-009-02, AC-REQ-009-04, AC-REQ-009-07..10_
  - _Verification: V-AC-REQ-003-05, V-AC-REQ-005-03, V-AC-REQ-006-01, V-AC-REQ-006-05, V-AC-REQ-009-02, V-AC-REQ-009-04, V-AC-REQ-009-07..10_
  - _Depends: T022_
  - _Boundary: focused Open Endpoints Filelib service tests only; no production runtime edits_

- [x] T025 实现最终目标节点解析、权限复核和目录上传
  - Done when: FilelibSyncService 解析 `ResolvedFileSyncTarget`；固定目录按稳定 ID复核，动态目标始终 `folder_id=None`；以 principal.user 预检最终节点后调用 `KnowledgeSpaceService.add_file(parent_id)`；目录失效/错配/权限丢失无 fallback；外部响应不增加目录字段；T024 与既有上传/清理/编码回归转绿。
  - _Requirements: REQ-003, REQ-005, REQ-006, REQ-009_
  - _Acceptance: AC-REQ-003-05, AC-REQ-005-03, AC-REQ-006-01, AC-REQ-006-05, AC-REQ-009-02, AC-REQ-009-04, AC-REQ-009-07..10_
  - _Verification: T024 tests + existing Filelib upload/cleanup/response regression_
  - _Depends: T023, T024_
  - _Boundary: Filelib schemas/service and strictly necessary Knowledge service calls only; no response schema, DB/Celery transaction or dynamic directory changes_

- [x] T026 编写目标树、切换和路径摘要的前端失败测试
  - Done when: Vitest/DOM 测试先覆盖公共/部门分组、根/目录单选、展开不选中、空间搜索、目录游标追加、导航祖先不可选、文件/无关节点不展示、loading/error/empty/no-permission/stale 文案、租户/绑定用户切换清缓存和旧请求、结构化当前路径摘要、三语 key parity 和所有相关文件 600 行门禁；当前实现按预期失败。
  - _Requirements: REQ-007, REQ-009_
  - _Acceptance: AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03, AC-REQ-007-05, AC-REQ-007-06, AC-REQ-009-03, AC-REQ-009-05, AC-REQ-009-06, AC-REQ-009-11_
  - _Verification: V-AC-REQ-007-01, V-AC-REQ-007-02, V-AC-REQ-007-03, V-AC-REQ-007-05, V-AC-REQ-007-06, V-AC-REQ-009-03, V-AC-REQ-009-05, V-AC-REQ-009-06, V-AC-REQ-009-11_
  - _Depends: T023_
  - _Boundary: focused Platform tests and i18n parity fixtures only; no production component/controller/locales edits_

- [x] T027 实现独立目标树、懒加载 hook 和当前路径摘要
  - Done when: controller 定义 `folder_id`、target display、options/children cursor 契约；独立 `DeveloperTokenFileSyncTargetTree.tsx` 与 hook 完成交互、请求取消/陈旧响应隔离和状态文案；规则组件联动清值，Token 表/编辑使用结构化路径；三语同步且文件不超过 600 行；T026、定向 Vitest 和 Platform build 转绿。
  - _Requirements: REQ-002, REQ-007, REQ-009_
  - _Acceptance: AC-REQ-002-02, AC-REQ-007-01..06, AC-REQ-009-01, AC-REQ-009-03, AC-REQ-009-05, AC-REQ-009-06, AC-REQ-009-11_
  - _Verification: T026 tests + focused Vitest + Platform production build + file line-count/i18n parity checks_
  - _Depends: T023, T026_
  - _Boundary: Platform DeveloperToken controller/page/components/tests and `{zh-Hans,en-US,ja}/bs.json` only; no new UI/state/request library_

- [x] T028 更新接口文档、发布和应用回退清单
  - Done when: 文档明确固定根/目录、动态根目录、绑定用户权限过滤、目录失效/权限错误、外部响应不变和无新 migration；回退清单证明旧 `extra=forbid` 应用对 `folder_id` 的风险，并给出导出清理/转换或 forward fix 路径；不改 Token、白名单或部署配置。
  - _Requirements: REQ-008, REQ-009_
  - _Acceptance: AC-REQ-008-04, AC-REQ-008-06, AC-REQ-009-01, AC-REQ-009-02, AC-REQ-009-08, AC-REQ-009-10_
  - _Verification: V-AC-REQ-008-04, V-AC-REQ-008-06, V-AC-REQ-009-01, V-AC-REQ-009-02, V-AC-REQ-009-08, V-AC-REQ-009-10_
  - _Depends: T025, T027_
  - _Boundary: `docs/api/filelib-file-sync.md` and F066 rollout/rollback documentation only; no live configuration or schema mutation_

- [x] T029 执行目录目标自动化验收并更新 `verification.md`
  - Done when: DeveloperToken/Knowledge/Filelib pytest、PermissionService 失败关闭、查询次数、ruff、arch guard、Platform Vitest/build、i18n/600 行、无新 migration、外部 response fixture、源码安全扫描和 `git diff --check` 均记录命令/exit code/摘要；全部 53 个 AC 重新分级，变更 AC 不复用旧 PASS；未运行项如实标记。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009_
  - _Acceptance: AC-REQ-001-01..04, AC-REQ-002-01..05, AC-REQ-003-01..05, AC-REQ-004-01..06, AC-REQ-005-01..05, AC-REQ-006-01..05, AC-REQ-007-01..06, AC-REQ-008-01..06, AC-REQ-009-01..11_
  - _Verification: all V-AC-REQ-* plus fresh folder-target `verification.md` evidence_
  - _Depends: T023, T025, T027, T028_
  - _Boundary: tests, read-only quality commands, formatting limited to touched files, and SDD verification/status docs only; no live database/config/external mutation_

## 阶段 10：生产组合路由遮蔽修复 Production Route Shadowing Bugfix

- [x] T030 建立生产组合路由失败回归
  - Done when: 测试通过真实 `router_rpc` 请求 `POST /api/v2/filelib/file/sync`，修复前稳定复现 `sync` 被解释为整数 `knowledge_id` 的 422，并以同步 handler 的 `19905` 作为期望契约。
  - _Requirements: REQ-001_
  - _Acceptance: AC-REQ-001-05_
  - _Verification: V-AC-REQ-001-05 red regression evidence_
  - _Depends: T029_
  - _Boundary: `src/backend/test/open_endpoints/test_filelib_sync.py` only; reuse the existing missing-multipart API test instead of adding duplicate coverage_

- [x] T031 调整生产路由顺序并完成聚焦回归
  - Done when: 静态统一同步 router 先于旧 Filelib 动态 router 注册；生产组合回归、路由相关 Filelib 同步测试、Ruff 和差异检查通过；接口 URL、业务 handler 和非法动态路径契约不做其他修改。
  - _Requirements: REQ-001_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-03, AC-REQ-001-05_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-03, V-AC-REQ-001-05 and updated verification.md evidence_
  - _Depends: T030_
  - _Boundary: `src/backend/bisheng/api/router.py`, focused Filelib sync tests, and F066 SDD status only_

## 阶段 11：环境与发布人工验收 Manual Verification

- [ ] T021 执行预发布 E2E、MySQL/DM8 与切换回退人工验收
  - Done when: 经发布负责人授权后，在隔离环境验证既有 migration、无配置 19906、19812 优先、四种 fixed/dynamic 组合及两种来源、固定根/目录和动态根、深层权限、stale/歧义/权限撤销、同步后真实目录位置与解析状态、11 个旧 URL 404、route whitelist/调用方切换，以及旧严格 schema 的应用回退处置；真实 MySQL/DM8 在 CI/预发布留证；所有 MANUAL_REQUIRED AC 更新结论。
  - _Requirements: REQ-001, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009_
  - _Acceptance: AC-REQ-001-01..05, AC-REQ-003-05, AC-REQ-004-01..06, AC-REQ-005-01..05, AC-REQ-006-01..05, AC-REQ-007-01..06, AC-REQ-008-01..06, AC-REQ-009-01..11_
  - _Verification: staging E2E evidence, MySQL/DM8 CI evidence, folder placement evidence, rollout/rollback checklist, updated verification.md_
  - _Depends: T031_
  - _Boundary: authorized staging/manual verification only; the agent must not mutate production data, Token configuration, route whitelist or live schema without separate explicit approval_

## 覆盖矩阵 Coverage Matrix

| Requirement | Acceptance Criteria | Tasks | Verification |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..05 | T011, T012, T013, T014, T019, T020, T029, T030, T031, T021 | V-AC-REQ-001-01..05 |
| REQ-002 | AC-REQ-002-01..05 | T002, T003, T004, T015, T016, T020, T022, T023, T027, T029 | V-AC-REQ-002-01..05 |
| REQ-003 | AC-REQ-003-01..05 | T003, T004, T005, T006, T009, T010, T015, T016, T020, T022, T023, T024, T025, T029, T021 | V-AC-REQ-003-01..05 |
| REQ-004 | AC-REQ-004-01..06 | T009, T010, T020, T029, T021 | V-AC-REQ-004-01..06 |
| REQ-005 | AC-REQ-005-01..05 | T005, T006, T007, T008, T009, T010, T011, T012, T013, T014, T020, T022, T023, T024, T025, T029, T021 | V-AC-REQ-005-01..05 |
| REQ-006 | AC-REQ-006-01..05 | T011, T012, T020, T024, T025, T029, T021 | V-AC-REQ-006-01..05 |
| REQ-007 | AC-REQ-007-01..06 | T003, T004, T005, T006, T015, T016, T017, T018, T020, T022, T023, T026, T027, T029, T021 | V-AC-REQ-007-01..06 |
| REQ-008 | AC-REQ-008-01..06 | T001, T002, T013, T014, T019, T020, T028, T029, T021 | V-AC-REQ-008-01..06 |
| REQ-009 | AC-REQ-009-01..11 | T022, T023, T024, T025, T026, T027, T028, T029, T021 | V-AC-REQ-009-01..11 |

## 执行顺序 Execution Order

```text
T001 -> T002 -------> T003 -> T004 -----> T005 -> T006 --------┐
   \----------------> T007 -> T008 -----------------------------┤
                         T004 -> T009 -> T010 -> T011 -> T012 --┤
                                                T013 -> T014 ---┤
                                      T006 -> T015 -> T016 -----┤
                                                     T017 -> T018
T002 + T014 + T018 -> T019 -------------------------------------┤
全部初版实现与文档任务 ---------------------------------------> T020
T020 -> T022 -> T023 ----┐
         T024 -> T025 ----┤
         T023 -> T026 -> T027
         T025 + T027 -> T028
         T023 + T025 + T027 + T028 -> T029 -> T030 -> T031 -> T021
```

T001-T020 已按初版规格完成。新增阶段中 T022/T024/T026 均为测试先行；T024 可在 T022 契约明确后准备，T026 必须等待 T023 固定 API 契约。共享文件修改必须串行合并，禁止并发编辑 `DeveloperTokenService`、Knowledge repository 或 `DeveloperToken.tsx`。

## 任务质量门 Task Quality Gate

- [x] Every task references at least one requirement ID.
- [x] Every behavioral task references acceptance criteria.
- [x] All 54 acceptance criteria are covered by implementation or verification tasks.
- [x] Every task has an observable done condition.
- [x] Test tasks precede their corresponding implementation tasks.
- [x] Dependencies are explicit where ordering is not obvious.
- [x] Boundary annotations prevent unrelated code edits and live mutations.
- [x] No task implements multi-rule, compatibility routes, automatic migration or other excluded scope.
- [x] Backend, Platform, documentation, migration, security and release verification are represented.
- [x] T001-T020 的历史证据与 T022-T029 的目录目标新鲜证据明确分离，旧证据不覆盖新范围。
- [x] T030-T031 以真实生产 `router_rpc` 子进程回归记录红灯和绿灯，不复用仅注册同步子路由的旧测试证据。

## 实现记录 Implementation Notes

- 任务规划时当前分支为 `feat/sg/7.24`；普通 `git status` 仅显示本 Feature 的 `release-contract.md` 修改，F066 新目录因仓库 `.gitignore` 的 `features/` 规则显示为 ignored。
- 实施前必须重新检查 worktree 并保护届时出现的用户变更；不得 reset、覆盖或顺手格式化无关文件。
- `DeveloperToken.tsx` 当前 572 行；T027 必须新增独立目标树和 hook，不能把目录树状态继续堆入主文件。
- Alembic heads 会变化；T001 必须读取实施时真实 heads，禁止照抄规格生成时快照。
- macOS 没有真实 DM8 驱动；本地只能执行方言无关测试和 disposable DB 验证，真实 DM8 留给 Linux CI/预发布。
- 不执行真实数据库 upgrade、Token 业务配置、route whitelist 修改或第三方调用方切换，除非发布负责人对明确环境和目标另行授权。
- 旧 URL 立即移除是已确认 breaking change；若实施期间要求兼容、灰度或自动迁移，必须先更新 requirements/design/tasks 并重新确认。
- T018 实施发现新建 Token 的现有 `DepartmentUsersSelect` 仅返回部门标识，无法满足已确认 options API 的 `tenant_id` 参数。实现补充从组织树挂载关系推导的 `DepartmentUserOption.tenant_id` 前端提示，并在根租户场景回退当前登录租户；该值只用于加载 options，后端仍按部门、管理员范围和 Token 绑定独立校验，未扩大权限边界。
- 为满足 600 行硬门禁并保持单一职责，T018 同时将原页面既有的全局设置和 Token 列表展示拆为 `DeveloperTokenGlobalSettings.tsx`、`DeveloperTokenTable.tsx`；业务行为保持不变。
- T020 自动化验收结论为后端 `145 passed`、Platform F066 定向 `43 passed`、生产构建与静态门禁通过；真实 MySQL/DM8、Token/白名单/调用方切换和应用回退保留给 T021，详见 `verification.md`。
- `2026-07-22` 用户追加固定目录目标：仅公共/部门空间，按 Token 绑定用户 `upload_file` 过滤，深层权限展示必要不可选祖先，空间搜索、目录游标懒加载，动态目标仍为根目录，外部响应不变。
- 本次通过可空 `folder_id` 扩展既有 JSON，不新增 migration；旧应用 `extra=forbid` 读取新字段是应用回退风险，T028/T021 必须留证。
- T022 红灯证据：`uv run pytest test/developer_token/test_developer_token_file_sync_rule.py test/developer_token/test_developer_token_file_sync_options.py test/developer_token/test_developer_token_file_sync_target.py -q` 在收集阶段因目录目标 schema/children API 尚不存在而产生 2 个预期 ImportError；测试已覆盖旧 JSON、动态目录拒绝、换绑复核、绑定用户权限主体、必要祖先、统一游标 19814 和列表批量摘要入口。
- T023 绿灯证据：同一组 DeveloperToken 目录目标定向测试完成 `37 passed`；生产实现已增加绑定用户权限主体、公共/部门空间游标分组、目录懒加载、19814 映射、最终节点保存/换绑复核和按页批量当前路径展示。
- T024 红灯证据：`uv run pytest test/open_endpoints/test_filelib_sync_folder_target.py -q` 在收集阶段因运行时尚无 `ResolvedFileSyncTarget` 产生预期 ImportError；测试已定义固定根/目录、动态根、19903/19902、上传前预检、`parent_id` 和外部响应不变契约。
- T025 绿灯证据：`uv run pytest test/open_endpoints/test_filelib_sync_folder_target.py test/open_endpoints/test_filelib_sync.py test/open_endpoints/test_filelib_sync_token_rule.py -q` 完成 `56 passed`；固定目录使用稳定 ID、动态目标为根目录、最终节点预检发生在临时上传前，外部响应 schema 未增加目录字段。
- T026 红灯证据：`npm test -- --run src/test/developerTokenFileSyncApi.test.ts src/test/DeveloperTokenFileSyncTargetTree.test.tsx` 按预期因 children API 与独立目标树组件尚不存在而失败，并捕获旧 options 仍发送 page/limit 的契约差异；测试定义了空间分组、展开不选中、导航祖先不可选、目录游标追加、根/目录单选及 loading/error/no-permission/stale 状态。
- T027 绿灯证据：6 个 F066 Platform 定向文件完成 `34 passed`，`npm run build` 完成 `8313 modules transformed`；新增目标树/两个 hook，绑定用户切换会取消旧请求并清理选择，三语 key 对齐且相关 TypeScript 文件均低于 600 行。
- T028 文档证据：`docs/api/filelib-file-sync.md` 已记录 `folder_id`、固定根/目录与动态根、绑定用户权限树、children 游标、19814/19902/19903、外部响应不变、无新 migration，以及旧 `extra=forbid` 应用回退前的导出/清理/转换或 forward fix 路径。
- T029 自动化验收：后端聚焦回归 `164 passed`，Platform 6 个定向文件 `34 passed`，生产构建 `8313 modules transformed`；Ruff/py_compile/arch guard、无新 migration、600 行、权限失败关闭、查询次数、外部响应 fixture、安全扫描和 `git diff --check` 均通过。53 个 AC 已重分级为 `50 PASS / 3 MANUAL_REQUIRED`，真实 MySQL/DM8、预发布切流和应用回退保留给 T021。
- T030 红灯证据：真实生产 `router_rpc` 子进程请求 `/api/v2/filelib/file/sync`，目标断言因响应没有同步 handler 的 `data.error_code=19905` 而 `KeyError: data`；实际请求先命中 `/file/{knowledge_id}`，稳定复现 `knowledge_id=sync` 路由遮蔽。
- T031 绿灯证据：交换 `filelib_sync_router_rpc` 与 `filelib_router_rpc` 注册顺序后，同一生产组合用例通过；路由聚焦回归 `13 passed`，Ruff、format、arch guard 和 scoped `git diff --check` 均通过。完整 `test_filelib_sync.py` 当前为 `34 passed / 1 failed`，失败来自既有 service 新增 `enqueue_file_title_extraction` 后旧 fixture 缺少该方法，与本次路由 diff 无关，未越界修改。
