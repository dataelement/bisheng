# 任务拆分 Tasks：门户带水印 PDF 下载、知识预览与问答水印

## 阅读摘要

- 本文档用于指导已确认的完整实现；下载与知识预览水印 T001-T092 已完成（T030 发布门禁除外），问答水印 T093-T097 已完成实现，T098 保留真实登录态视觉门禁；T099-T101 已完成智能写作展示时机修复，T102 保留登录会话态视觉验证；T103-T105 已将最新透明度口径统一为 `0.31`。
- 后端行为使用 Test-First；前端已有 Node test 基线，公共下载逻辑和静态接线契约必须自动化验证。
- 每个任务必须保持在声明边界内，不得实现历史补齐脚本、异步水印、管理端/非知识下载改造或部署服务变更；按需生成只复用 F063 现有转换、Artifact 表和对象命名。
- F064 跨 BiSheng、Portal BFF 和 Portal frontend，发布前必须作为同一功能单元完成端到端验证；Portal BFF 匿名正文门禁与 Portal frontend 登录提示必须成对发布。
- 门户只支持单文件带水印下载；BiSheng client 门户知识工作台下线多选批量与文件夹行级下载，旧单文件 URL endpoint 收口为水印 PDF 二进制并迁移仓库内调用方。

## 元信息 Metadata

- Feature ID: `064-portal-watermarked-pdf-download`
- Status: `partial`
- Related requirements: `features/v2.6.0/064-portal-watermarked-pdf-download/requirements.md`
- Related design: `features/v2.6.0/064-portal-watermarked-pdf-download/design.md`
- Created: `2026-07-21`
- Updated: `2026-07-23`

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| requirements.md | ✅ 已更新 | REQ-002/006/008/010 已切换为下载时按需确保统一 PDF |
| design.md | ✅ 已更新 | 新增共享 processor、文件级 single-flight、300/60 秒 deadline 与 370 秒 BFF 代理 |
| tasks.md | 🟨 实施中 | 105 个任务；T103-T105 已完成；T102/T098/T030 人工视觉门禁待执行 |
| implementation | ✅ 已完成 | PDF、Worker、Portal 与 BiSheng 透明度已统一为 `0.31` |
| verification.md | 🟨 `MANUAL_REQUIRED` | 既有 T092 证据保留；T098 与 T030 待执行 |

## 执行规则

- BiSheng backend：先写失败测试，再写最小实现；新测试位于 `src/backend/test/knowledge/` 或其 `pdf/` 子目录。
- Portal BFF：先在 `backend/tests/` 建立普通/分享/流式/错误场景，再修改实现。
- Portal frontend：先更新 `frontend/tests/` 中公共工具和源码接线契约，再修改页面。
- BiSheng client 门户 host：先更新 `PortalKnowledgeWorkbench.test.tsx`，再通过默认兼容的共享组件 capability 收缩入口。
- 本次扩展：先完成 T033 规格对齐，再按 T034-T040 执行 endpoint Test-First、Blob helper、入口接线、文件夹隐藏和目标验证。
- 预览扩展：T041 先更新规格；T042/T044/T046 分别为 Portal BFF、Portal frontend、BiSheng client 建立红灯，再按 T043/T045/T047 最小实现，T048 统一验证。
- 按需产物扩展：T049 先更新规格；T050/T052/T054 建立红灯，再按 T051/T053/T055 最小实现，T056 统一验证。
- 预览边界回归：T057 记录根因与范围；T058 建立红灯；T059 将 overlay 下沉到各正文 surface；T060 统一验证。
- 三行文案统一：T061 更新规格；T062 建立主部门/无部门与三行红灯；T063 实现字段透传和统一 formatter；T064 统一验证。
- 两行文案与视觉统一：T065 更新规格；T066/T068 分别建立后端和两端预览红灯；T067/T069 实现服务端两行黑体水印及前端动态密度；T070 渲染 PDF、执行回归并更新验证。
- 自适应无重叠视觉：T071 更新规格；T072/T074 分别建立 PDF 布局和两端 SVG pattern 红灯；T073/T075 实现文字度量、自适应错位布局与常量级前端节点；T076 统一渲染、回归和安全审计。
- 轻度增密：T077 更新规格；T078 将 PDF/两端预览最小单元和 A4 密度切换为新红灯；T079 仅调整三端最小单元常量；T080 执行目标回归、构建、渲染和差异审计。
- 中等增密：T081 更新规格；T082 将 PDF/两端预览最小单元和 A4 密度切换为新红灯；T083 仅调整四处生产常量；T084 执行目标回归、构建、渲染和差异审计。
- 预览切片修复：T089 更新缺陷规格；T090 为两端 surface 坐标、ResizeObserver 和无 pattern 建立红灯；T091 实现全尺寸 SVG 逐坐标绘制；T092 执行回归、构建、浏览器视觉和差异审计。
- 问答水印扩展：T093 更新范围与 iframe 责任；T094/T095 分别为 Portal/BiSheng 建立红灯；T096/T097 实现两端显式 surface 接线；T098 执行回归、构建、浏览器视觉/交互和差异审计。
- 任一任务发现范围、API、权限或 60 秒超时设计不成立时，停止实现并先更新 requirements/design/tasks。
- 禁止修改当前无关脏文件：`src/backend/scripts/README.md`、`src/backend/scripts/move_knowledge_space_files.py`、`src/backend/test/scripts/test_move_knowledge_space_files.py`、门户 `docker-compose.yaml`。

## 阶段 1：契约与基础配置 Foundation

- [x] T001 登记版本依赖并建立实施前基线
  - Done when: `release-contract.md` 登记 F064 依赖 F063、明确只读 `KnowledgeFilePdfArtifact`；记录两个仓库初始 `git status` 和现有相关测试基线，不覆盖无关改动。
  - _Requirements: REQ-002, REQ-008_
  - _Acceptance: AC-REQ-002-04, AC-REQ-008-04_
  - _Verification: V-AC-REQ-002-04, V-AC-REQ-008-04_
  - _Depends: none_
  - _Boundary: release contract and read-only baseline evidence only_

- [x] T002 [P] 为水印配置、下载 DTO、entry point 和错误码编写失败测试
  - Done when: 测试覆盖 60 秒/并发 2/锁 TTL 配置校验、9 个合法 entry point 与非法归一、内部 grant 字段、180xx 新错误码唯一性。
  - _Requirements: REQ-006, REQ-007, REQ-008_
  - _Acceptance: AC-REQ-006-02, AC-REQ-006-04, AC-REQ-007-02, AC-REQ-007-04, AC-REQ-008-01_
  - _Verification: V-AC-REQ-006-02, V-AC-REQ-006-04, V-AC-REQ-007-02, V-AC-REQ-007-04, V-AC-REQ-008-01_
  - _Depends: none_
  - _Boundary: BiSheng config/schema/errcode tests only; parallel-safe_

- [x] T003 实现水印配置、下载 DTO、entry point 和错误码
  - Done when: `KnowledgePdfWatermarkConf`、内部下载/grant DTO、entry point 归一和稳定错误码通过 T002；配置不包含秘密且不引入依赖。
  - _Requirements: REQ-006, REQ-007, REQ-008_
  - _Acceptance: AC-REQ-006-02, AC-REQ-006-04, AC-REQ-007-02, AC-REQ-007-04, AC-REQ-008-01_
  - _Verification: T002 tests + V-AC-REQ-008-01_
  - _Depends: T002_
  - _Boundary: `core/config/settings.py`, `initdb_config.yaml`, portal download schemas, knowledge_space errcodes only_

## 阶段 2：PyMuPDF 水印核心 Watermark Core

- [x] T004 [P] 为纯水印引擎编写失败测试
  - Done when: 固定时钟样本覆盖每页四项水印、多 tile、中文、透明/倾斜、横向/旋转页面、页数/尺寸/关键文本保持、输入 SHA256 不变、损坏/加密/零页失败。
  - _Requirements: REQ-003_
  - _Acceptance: AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04_
  - _Verification: V-AC-REQ-003-01, V-AC-REQ-003-02, V-AC-REQ-003-03, V-AC-REQ-003-04_
  - _Depends: none_
  - _Boundary: `test/knowledge/pdf/test_pdf_watermark.py` only; parallel-safe_

- [x] T005 实现纯 PyMuPDF 水印引擎和中文字体解析
  - Done when: 引擎只读输入、新路径输出，按页面动态平铺任意角度半透明文字；WQY/系统黑体/仓库 Noto Sans 可用且候选全部缺失时明确失败，T004 全部通过。
  - _Requirements: REQ-003, REQ-008_
  - _Acceptance: AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-008-01_
  - _Verification: T004 tests + V-AC-REQ-008-01_
  - _Depends: T004_
  - _Boundary: `bisheng/knowledge/pdf/watermark.py` only_

- [x] T006 为隔离 watermark worker 编写失败测试
  - Done when: 测试覆盖 stdin spec、argv 不含身份、stdout/stderr 脱敏、成功 metadata、部分输出清理、非零退出和父进程可 terminate/kill/reap。
  - _Requirements: REQ-003, REQ-006, REQ-007_
  - _Acceptance: AC-REQ-003-02, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-007-02_
  - _Verification: V-AC-REQ-003-02, V-AC-REQ-006-02, V-AC-REQ-006-03, V-AC-REQ-007-02_
  - _Depends: T005_
  - _Boundary: watermark worker process tests only_

- [x] T007 实现隔离 watermark worker CLI
  - Done when: worker 使用最小环境和请求工作目录，从 stdin 读取身份，调用 T005 引擎，失败不回显敏感内容；父进程能够按 deadline 终止并回收。
  - _Requirements: REQ-003, REQ-006, REQ-007_
  - _Acceptance: AC-REQ-003-02, AC-REQ-003-04, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-007-02_
  - _Verification: T006 tests_
  - _Depends: T006_
  - _Boundary: `bisheng/knowledge/pdf/watermark_worker.py` and narrow worker launch helper only_

## 阶段 3：分享下载授权 Share Authorization

- [x] T008 [P] 为分享下载 grant 与 live recheck 编写失败测试
  - Done when: 测试覆盖 claims、域隔离签名、TTL、allow_download、密码/邀请码通过后签发、篡改、wrong-purpose、cross-user/tenant/token/file、过期以及链接撤销/到期/部门变化实时阻断。
  - _Requirements: REQ-005, REQ-007_
  - _Acceptance: AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-005-05, AC-REQ-007-02_
  - _Verification: V-AC-REQ-005-01, V-AC-REQ-005-02, V-AC-REQ-005-03, V-AC-REQ-005-05, V-AC-REQ-007-02_
  - _Depends: none_
  - _Boundary: BiSheng share grant/service tests only; parallel-safe_

- [x] T009 实现分享下载 grant、可选签发和 live recheck 窄接口
  - Done when: 登录用户分享验证可得到用户绑定 grant，匿名查看验证不获得可用下载 grant；下载时复核 ShareLink 当前状态、allow_download 和部门范围；token 不进入日志。
  - _Requirements: REQ-005, REQ-007_
  - _Acceptance: AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-005-05, AC-REQ-007-02_
  - _Verification: T008 tests_
  - _Depends: T003, T008_
  - _Boundary: grant service, existing Shougang share verify/live-check methods and schemas only_

## 阶段 4：BiSheng 下载领域服务 BiSheng Domain

- [x] T010 为 Artifact、普通权限和服务端身份编写失败测试
  - Done when: 测试覆盖文件/空间/租户匹配、file-level download_file、view-only、UserRepository 姓名/external_id/账号回退、三种 Artifact 来源及所有 unavailable 状态；断言无 fallback/copy/upload。
  - _Requirements: REQ-002, REQ-003, REQ-004_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-003-02, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04_
  - _Verification: V-AC-REQ-002-01, V-AC-REQ-002-02, V-AC-REQ-002-03, V-AC-REQ-003-02, V-AC-REQ-004-01, V-AC-REQ-004-02, V-AC-REQ-004-03, V-AC-REQ-004-04_
  - _Depends: T003, T005, T009_
  - _Boundary: `test_portal_pdf_download_service.py` authorization/artifact/identity tests only_

- [x] T011 实现下载服务的授权、身份和 Artifact 前半链路
  - Done when: 新 Service 通过注入 Repository 和现有权限窄接口完成校验，只读 F063 accessor；普通与分享授权分支互斥且 fail closed；T010 通过。
  - _Requirements: REQ-002, REQ-003, REQ-004, REQ-005_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-003-02, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-005-03, AC-REQ-005-05_
  - _Verification: T010 tests + T008 tests_
  - _Depends: T010_
  - _Boundary: `portal_pdf_download_service.py`, dependency injection and narrow permission adapter only_

- [x] T012 为 storage、deadline、并发、清理和 first-chunk 遥测编写失败测试
  - Done when: 测试覆盖分块 Artifact 读取、60 秒 remaining deadline、worker terminate/kill、进程并发 2、Redis ownership lock、success/error/timeout/disconnect cleanup、首块一次事件和首块前失败零事件。
  - _Requirements: REQ-006, REQ-007_
  - _Acceptance: AC-REQ-006-02, AC-REQ-006-03, AC-REQ-006-04, AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03, AC-REQ-007-04_
  - _Verification: V-AC-REQ-006-02, V-AC-REQ-006-03, V-AC-REQ-006-04, V-AC-REQ-007-01, V-AC-REQ-007-02, V-AC-REQ-007-03, V-AC-REQ-007-04_
  - _Depends: T007, T011_
  - _Boundary: portal PDF download lifecycle tests only_

- [x] T013 实现 storage、水印运行控制、容量限制和 response lifecycle descriptor
  - Done when: Artifact 写入隔离目录、worker 按 remaining deadline 运行、输出 validator 通过；容量/锁有界；prepared descriptor 在全部响应终止路径清理并按首块规则触发一次遥测。
  - _Requirements: REQ-002, REQ-003, REQ-006, REQ-007_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-03, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-006-04, AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03, AC-REQ-007-04_
  - _Verification: T012 tests + existing PDF validator tests_
  - _Depends: T012_
  - _Boundary: `portal_pdf_download_service.py` lifecycle portion, MinIO read adapter and exact temp cleanup only_

- [x] T014 为 BiSheng 门户二进制 endpoint 编写失败测试
  - Done when: API 测试覆盖成功 headers/body/中文文件名、normal/share 模式、401/403/404/409/429/503/504/500、grant header、响应前错误和断连 finally。
  - _Requirements: REQ-001, REQ-004, REQ-005, REQ-006, REQ-007_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-03, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-005-03, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-03, V-AC-REQ-004-01, V-AC-REQ-004-02, V-AC-REQ-005-03, V-AC-REQ-006-02, V-AC-REQ-006-03, V-AC-REQ-007-01, V-AC-REQ-007-02, V-AC-REQ-007-03_
  - _Depends: T013_
  - _Boundary: `test_shougang_portal_endpoint.py` portal PDF endpoint tests only_

- [x] T015 实现 BiSheng 门户二进制 endpoint
  - Done when: 新 endpoint 使用当前 UserPayload 和注入的 download service，返回安全 StreamingResponse；业务错误有真实 HTTP status；现有工作台下载 endpoint 未改。
  - _Requirements: REQ-001, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-03, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-005-03, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03, AC-REQ-008-03_
  - _Verification: T014 tests + V-AC-REQ-008-03_
  - _Depends: T014_
  - _Boundary: Shougang portal endpoint and its dependency wiring only; existing knowledge-space download excluded_

## 阶段 5：Portal BFF 分享会话与流式代理

- [x] T016 [P] 为 Redis 分享访问 session store 编写失败测试
  - Done when: 测试覆盖序列化、TTL、跨实例读取、token/space/file/portal-session 绑定、匿名 view session、opaque grant、过期、Redis 错误 fail closed 和开发内存回退。
  - _Requirements: REQ-005_
  - _Acceptance: AC-REQ-005-01, AC-REQ-005-04, AC-REQ-005-05_
  - _Verification: V-AC-REQ-005-01, V-AC-REQ-005-04, V-AC-REQ-005-05_
  - _Depends: none_
  - _Boundary: Portal BFF share store tests only; parallel-safe_

- [x] T017 实现 Redis 分享访问 session store 和应用依赖
  - Done when: 进程字典被独立 Store 替换；Redis v2 key/TTL、开发 fallback、app.state/dependency 接线完成；旧 cookie 无记录时要求重新验证。
  - _Requirements: REQ-005_
  - _Acceptance: AC-REQ-005-01, AC-REQ-005-04, AC-REQ-005-05_
  - _Verification: T016 tests_
  - _Depends: T016_
  - _Boundary: `portal_share_access_store.py`, BFF app lifespan/dependencies and removal of in-process share dict only_

- [x] T018 [P] 为 BishengClient 下载专用 stream 编写失败测试
  - Done when: 测试覆盖认证 header/cookie、可选 grant header、entry point 参数、70 秒专用 read timeout、401 refresh once、非缓冲 body 和所有路径 `aclose()`。
  - _Requirements: REQ-006, REQ-007_
  - _Acceptance: AC-REQ-006-05, AC-REQ-007-01, AC-REQ-007-02_
  - _Verification: V-AC-REQ-006-05, V-AC-REQ-007-01, V-AC-REQ-007-02_
  - _Depends: none_
  - _Boundary: `backend/tests/test_bisheng_client.py` download stream tests only; parallel-safe_

- [x] T019 实现 BishengClient 下载专用 stream
  - Done when: 新方法支持 endpoint-specific timeout 和私有 headers，不修改全局 client timeout；auth refresh 和响应 ownership 明确，T018 通过。
  - _Requirements: REQ-006, REQ-007_
  - _Acceptance: AC-REQ-006-05, AC-REQ-007-01, AC-REQ-007-02_
  - _Verification: T018 tests_
  - _Depends: T018_
  - _Boundary: Portal BFF `clients/bisheng.py` and timeout setting only_

- [x] T020 为 BFF 分享 verify、详情权限和统一下载路由编写失败测试
  - Done when: 测试覆盖登录 gate、普通下载、分享 session/grant/allow_download、grant 不出公开 JSON、详情 `can_download`、preview 下载字段清空、safe headers、上游错误映射、stream/disconnect close、旧 download-event 不重复写事件。
  - _Requirements: REQ-001, REQ-004, REQ-005, REQ-006, REQ-007_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-04, AC-REQ-004-01, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-005-01, AC-REQ-005-04, AC-REQ-005-05, AC-REQ-006-05, AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-04, V-AC-REQ-004-01, V-AC-REQ-004-03, V-AC-REQ-004-04, V-AC-REQ-005-01, V-AC-REQ-005-04, V-AC-REQ-005-05, V-AC-REQ-006-05, V-AC-REQ-007-01, V-AC-REQ-007-02, V-AC-REQ-007-03_
  - _Depends: T009, T015, T017, T019_
  - _Boundary: Portal BFF knowledge API/service integration tests only_

- [x] T021 实现 BFF 分享 verify 隐藏 grant、详情权限和统一流式下载路由
  - Done when: share access public response不含 grant；Store 保存 grant；download route 要求登录并转发 opaque grant；上游成功不缓冲、错误可展示、finally 关闭；详情正确透传/覆盖 can_download；preview 不再暴露 original download URL。
  - _Requirements: REQ-001, REQ-004, REQ-005, REQ-006, REQ-007_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-04, AC-REQ-004-01, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-005-01, AC-REQ-005-04, AC-REQ-005-05, AC-REQ-006-05, AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03_
  - _Verification: T020 tests_
  - _Depends: T020_
  - _Boundary: Portal BFF knowledge routes/service/schemas only_

## 阶段 6：Portal Frontend 统一下载

- [x] T022 [P] 为统一二进制下载工具编写失败测试
  - Done when: 测试覆盖 URL/query、credentials、PDF response、RFC 5987/ASCII filename、stem+.pdf fallback、JSON/非 JSON error、Blob anchor、URL revoke 和无前端 success telemetry。
  - _Requirements: REQ-001, REQ-006, REQ-007_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-03, AC-REQ-001-04, AC-REQ-006-01, AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03, AC-REQ-007-04_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-03, V-AC-REQ-001-04, V-AC-REQ-006-01, V-AC-REQ-007-01, V-AC-REQ-007-02, V-AC-REQ-007-03, V-AC-REQ-007-04_
  - _Depends: none_
  - _Boundary: `frontend/tests/fileDownload.test.ts` and pure API test seams only; parallel-safe_

- [x] T023 实现统一二进制下载 API 和浏览器保存工具
  - Done when: `content.ts`/`fileDownload.ts` 不再从 preview 解析下载 URL，统一 Fetch/Blob、错误和 `.pdf` filename 行为通过 T022。
  - _Requirements: REQ-001, REQ-006, REQ-007_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-03, AC-REQ-001-04, AC-REQ-006-01, AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03, AC-REQ-007-04_
  - _Verification: T022 tests_
  - _Depends: T021, T022_
  - _Boundary: Portal frontend `api/content.ts` and `utils/fileDownload.ts` only_

- [x] T024 为搜索、列表、详情、访客和 view-only UI 接线编写失败测试
  - Done when: 源码/行为测试要求 Search=`search`、List=`knowledge_list`、Detail 动态 entry point；详情使用 button/loading 且受 `user && canDownload` 控制；guest/view-only 无可用动作；不调用 recordFileDownloadEvent。
  - _Requirements: REQ-001, REQ-004, REQ-006, REQ-007_
  - _Acceptance: AC-REQ-001-01, AC-REQ-004-01, AC-REQ-004-03, AC-REQ-006-01, AC-REQ-007-03, AC-REQ-007-04_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-004-01, V-AC-REQ-004-03, V-AC-REQ-006-01, V-AC-REQ-007-03, V-AC-REQ-007-04_
  - _Depends: T023_
  - _Boundary: frontend page wiring tests only_

- [x] T025 接入搜索、列表和详情下载按钮
  - Done when: 三个页面使用统一工具；搜索/列表复用现有 FileListItem pending；详情把“下载原文件”改为“下载 PDF” button 并提供 pending/error；普通权限和分享提示正确。
  - _Requirements: REQ-001, REQ-004, REQ-005, REQ-006, REQ-007_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-03, AC-REQ-004-01, AC-REQ-004-03, AC-REQ-005-01, AC-REQ-006-01, AC-REQ-007-02, AC-REQ-007-03, AC-REQ-007-04_
  - _Verification: T024 tests + frontend build_
  - _Depends: T024_
  - _Boundary: SearchPage, ListPage, DetailPage and necessary CSS only_

- [x] T026 为首页、专家问答和 QA 引用建立统一详情来源
  - Done when: 首页/相关推荐/收藏保留来源；专家问答只对结构化 `(space_id,file_id)` 生成门户详情 URL；QA citation 带 `qa_citation`；外链/图片/普通附件不变。
  - _Requirements: REQ-001, REQ-007_
  - _Acceptance: AC-REQ-001-02, AC-REQ-007-04_
  - _Verification: V-AC-REQ-001-02, V-AC-REQ-007-04_
  - _Depends: T023_
  - _Boundary: HomePage, ExpertQADetailPage, QAPage and focused route tests only_

- [x] T027 完成分享下载前端回归和登录重新验证行为
  - Done when: 匿名公共分享仍可按既有路径进入查看，但下载按钮不可用；登录后的分享验证能建立下载 session；匿名验证后切换登录必须重新验证；grant 不可从 frontend 类型/响应访问。
  - _Requirements: REQ-004, REQ-005_
  - _Acceptance: AC-REQ-004-01, AC-REQ-005-01, AC-REQ-005-04, AC-REQ-005-05_
  - _Verification: V-AC-REQ-004-01, V-AC-REQ-005-01, V-AC-REQ-005-04, V-AC-REQ-005-05_
  - _Depends: T017, T021, T025_
  - _Boundary: ShareDocumentPage/share access utility and focused tests only_

- [x] T031 [P] 为门户知识工作台批量下载入口下线编写失败测试
  - Done when: 行为测试覆盖文件、文件夹和混合多选均无“批量下载”；只具下载权限且无其他动作时不显示空批量菜单；管理员批量重试/删除保持；门户多选不调用 `batchDownloadApi`，现有 client API 契约仍由既有测试覆盖。
  - _Requirements: REQ-009_
  - _Acceptance: AC-REQ-009-01, AC-REQ-009-02, AC-REQ-009-03, AC-REQ-009-04_
  - _Verification: V-AC-REQ-009-01, V-AC-REQ-009-02, V-AC-REQ-009-03, V-AC-REQ-009-04_
  - _Depends: none_
  - _Boundary: `src/frontend/client/src/pages/knowledge/portal/PortalKnowledgeWorkbench.test.tsx` only; parallel-safe_

- [x] T032 实现门户 host 批量下载能力关闭
  - Done when: `KnowledgeSpaceContent` 增加默认 `false` 的 `hideBatchDownload`；门户 host 显式开启并清理未使用批量接线；共享 `SpaceDetail` 默认批量入口、现有 `batchDownloadApi`、后端 endpoint 及行级单文件/文件夹下载保持；T031 通过。
  - _Requirements: REQ-009_
  - _Acceptance: AC-REQ-009-01, AC-REQ-009-02, AC-REQ-009-03, AC-REQ-009-04_
  - _Verification: T031 tests + V-AC-REQ-009-01..04_
  - _Depends: T031_
  - _Boundary: `src/frontend/client/src/pages/knowledge/SpaceDetail/index.tsx` and `src/frontend/client/src/pages/knowledge/portal/PortalKnowledgeWorkbench.tsx` only_
  - Historical note: 本任务按初始范围保留了行级文件/文件夹旧下载；2026-07-21 的范围更新由 T033-T040 覆盖并替代该部分行为，已完成的批量菜单能力仍保留。

## 阶段 7：兼容性、验证与交付 Verification

- [x] T028 执行旧下载、预览、依赖和部署兼容回归
  - Done when: 非门户知识空间详情单文件/批量 ZIP/开放接口和门户行级文件/文件夹下载行为保持；portal viewer/chunks 预览保持；旧 download-event 不产生重复成功；依赖 lock、数据库 migration、Compose、Dockerfile、entrypoint、Celery 均无 F064 功能性改动。
  - _Requirements: REQ-001, REQ-007, REQ-008, REQ-009_
  - _Acceptance: AC-REQ-001-04, AC-REQ-007-03, AC-REQ-008-01, AC-REQ-008-02, AC-REQ-008-03, AC-REQ-008-04, AC-REQ-009-03, AC-REQ-009-04_
  - _Verification: V-AC-REQ-001-04, V-AC-REQ-007-03, V-AC-REQ-008-01, V-AC-REQ-008-02, V-AC-REQ-008-03, V-AC-REQ-008-04, V-AC-REQ-009-03, V-AC-REQ-009-04_
  - _Depends: T015, T021, T025, T026, T027, T032_
  - _Boundary: regression tests and read-only diff/source review only_

- [x] T029 运行全部自动验收并创建 `verification.md`
  - Done when: BiSheng ruff/目标 pytest、Portal BFF pytest、两个 frontend 的目标 test/build/lint 命令、exit code 和输出摘要写入 verification；每个 AC 标记 PASS/FAIL/MANUAL_REQUIRED/NOT_RUN。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009_
  - _Acceptance: AC-REQ-001-01..04, AC-REQ-002-01..04, AC-REQ-003-01..04, AC-REQ-004-01..04, AC-REQ-005-01..05, AC-REQ-006-01..05, AC-REQ-007-01..04, AC-REQ-008-01..04, AC-REQ-009-01..04_
  - _Verification: verification.md with V-AC-REQ-001-01..V-AC-REQ-009-04 evidence_
  - _Depends: T001..T028, T031, T032_
  - _Boundary: verification execution and SDD status updates only_

- [ ] T030 执行发布门禁、视觉、安全、性能和断连人工验收
  - Done when: 有效/缺失/损坏/历史产物代表集、各格式、中文/横向/旋转下载水印、A/B 用户、两次时间、view-only、公共/部门分享撤销、50 MB、同文件并发复用、并发 2/429、PDF 就绪 300 秒/水印 60 秒/504、浏览器断连 cleanup、门户多选菜单收缩和非门户批量兼容均记录结果；两端知识预览各格式/富媒体的 CSS 水印视觉与交互、匿名元数据/摘要可见和正文登录提示/401、非知识预览无水印均人工确认；所有 MANUAL_REQUIRED 项得到结论。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, REQ-010, REQ-011_
  - _Acceptance: AC-REQ-001-01..03, AC-REQ-002-01..05, AC-REQ-003-01..04, AC-REQ-004-01..04, AC-REQ-005-01..05, AC-REQ-006-01..05, AC-REQ-007-01..04, AC-REQ-008-01..04, AC-REQ-009-01..04, AC-REQ-010-01..04, AC-REQ-011-01..07_
  - _Verification: design.md representative manual acceptance + verification.md evidence_
  - _Depends: T029, T040, T048, T056, T070, T080, T084_
  - _Boundary: staging/manual verification and documentation only; no production data mutation by agent_

## 阶段 8：BiSheng 门户入口统一与旧契约收口

- [x] T033 更新 BiSheng 门户下载扩展规格
  - Done when: requirements 新增 REQ-010、更新 REQ-008/009；design 覆盖旧 endpoint 二进制收口、BiSheng Blob helper、四类入口和文件夹 host capability；tasks/verification mapping 无孤儿 ID。
  - _Requirements: REQ-007, REQ-008, REQ-009, REQ-010_
  - _Acceptance: AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-04, AC-REQ-008-03, AC-REQ-009-04, AC-REQ-010-01, AC-REQ-010-02, AC-REQ-010-03, AC-REQ-010-04_
  - _Verification: spec source scan + traceability review_
  - _Depends: T001-T032_
  - _Boundary: F064 requirements.md, design.md, tasks.md planning content only_

- [x] T034 为旧单文件 endpoint 二进制契约编写失败测试
  - Done when: 测试证明旧路径当前返回 JSON，并定义目标 PDF body、中文文件名、安全 headers、entry point、401/403/404/409/429/503/504/500、stream cleanup 和无 URL 泄漏契约。
  - _Requirements: REQ-007, REQ-008, REQ-010_
  - _Acceptance: AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-04, AC-REQ-008-03, AC-REQ-010-02, AC-REQ-010-03_
  - _Verification: V-AC-REQ-007-01, V-AC-REQ-007-02, V-AC-REQ-007-04, V-AC-REQ-008-03, V-AC-REQ-010-02, V-AC-REQ-010-03_
  - _Depends: T033_
  - _Boundary: knowledge-space download endpoint tests and shared response helper tests only_

- [x] T035 收口旧单文件 endpoint 并扩展遥测入口
  - Done when: 旧路径复用 `PortalPdfDownloadService` 返回 `StreamingResponse(application/pdf)`；不再调用 `get_file_download`/返回 URL；两个二进制 endpoint 共享安全响应逻辑；新增四个 BiSheng entry point；T034 通过。
  - _Requirements: REQ-007, REQ-008, REQ-010_
  - _Acceptance: AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-04, AC-REQ-008-03, AC-REQ-010-02, AC-REQ-010-03_
  - _Verification: T034 tests + existing portal endpoint/service tests + ruff_
  - _Depends: T034_
  - _Boundary: portal download schema、knowledge_space/shougang_portal endpoints、必要 response helper 与旧 service method only_

- [x] T036 为 BiSheng Client Blob 下载 helper 编写失败测试
  - Done when: 测试覆盖 URL/query、Axios `responseType=blob`、RFC 5987/ASCII 文件名、stem+.pdf fallback、JSON Blob/HTTP 错误、Object URL 创建与释放、重复入口参数。
  - _Requirements: REQ-007, REQ-010_
  - _Acceptance: AC-REQ-007-02, AC-REQ-010-03, AC-REQ-010-04_
  - _Verification: V-AC-REQ-007-02, V-AC-REQ-010-03, V-AC-REQ-010-04_
  - _Depends: T033_
  - _Boundary: `src/frontend/client/src/api/knowledge.test.ts` download helper tests only_

- [x] T037 实现 BiSheng Client Blob 下载 helper
  - Done when: 旧 `getFileDownloadApi` JSON DTO 被水印 Blob helper 替换；使用现有 Axios 认证链路；错误可展示；文件名安全；Object URL 必然释放；T036 通过。
  - _Requirements: REQ-007, REQ-008, REQ-010_
  - _Acceptance: AC-REQ-007-02, AC-REQ-008-03, AC-REQ-010-03, AC-REQ-010-04_
  - _Verification: T036 tests + TypeScript compile_
  - _Depends: T035, T036_
  - _Boundary: `src/frontend/client/src/api/knowledge.ts` and focused API tests only_

- [x] T038 为全部 BiSheng 门户入口和文件夹隐藏编写失败测试
  - Done when: 行为测试覆盖文件卡片/表格行、门户原地预览、收藏源空间、独立预览、版本历史 ID、pending/error，以及门户文件夹卡片/表格/菜单无下载且非门户默认保持。
  - _Requirements: REQ-009, REQ-010_
  - _Acceptance: AC-REQ-009-04, AC-REQ-010-01, AC-REQ-010-02, AC-REQ-010-04_
  - _Verification: V-AC-REQ-009-04, V-AC-REQ-010-01, V-AC-REQ-010-02, V-AC-REQ-010-04_
  - _Depends: T036_
  - _Boundary: PortalKnowledgeWorkbench、SpaceDetail/FilePreview focused tests only_

- [x] T039 接入全部 BiSheng 门户入口并隐藏文件夹下载
  - Done when: 文件行、原地预览、收藏、独立预览和版本历史调用水印 helper 并传正确 entry point/space/file；门户启用 `hideFolderDownload`；所有入口有 pending/error 恢复；T038 通过。
  - _Requirements: REQ-009, REQ-010_
  - _Acceptance: AC-REQ-009-04, AC-REQ-010-01, AC-REQ-010-02, AC-REQ-010-04_
  - _Verification: T038 tests + BiSheng client production build_
  - _Depends: T037, T038_
  - _Boundary: SpaceDetail、PortalKnowledgeWorkbench、FilePreviewPage 及必要展示组件 only_

- [x] T040 执行扩展范围自动验证并更新 verification
  - Done when: backend endpoint/service/schema 目标 pytest + ruff、BiSheng client API/workbench/preview/version 目标 Jest + build、旧 URL 源码扫描、diff/check 和部署边界审计均记录；新增 AC 有 PASS/MANUAL_REQUIRED 结论。
  - _Requirements: REQ-007, REQ-008, REQ-009, REQ-010_
  - _Acceptance: AC-REQ-007-01..04, AC-REQ-008-01..04, AC-REQ-009-01..04, AC-REQ-010-01..04_
  - _Verification: verification.md fresh evidence + source/diff audit_
  - _Depends: T035, T037, T039_
  - _Boundary: tests, formatting, source scans, verification/tasks status only; no production data mutation_

## 阶段 9：知识预览 CSS 水印与匿名正文门禁

- [x] T041 更新知识预览扩展规格
  - Done when: requirements 新增 REQ-011 并修正匿名分享语义；design 覆盖两端知识预览基础层、身份/时钟、Portal 三路门禁和 CSS 安全边界；tasks mapping 无孤儿 ID。
  - _Requirements: REQ-005, REQ-011_
  - _Acceptance: AC-REQ-005-01, AC-REQ-011-01..05_
  - _Verification: spec source scan + traceability review_
  - _Depends: T040_
  - _Boundary: F064 requirements.md, design.md, tasks.md planning content only_

- [x] T042 为 Portal BFF 匿名预览正文门禁编写失败测试
  - Done when: 集成测试证明匿名分享 detail/摘要仍可读取，但 `/preview`、`/preview/content`、`/chunks` 目标契约为 401 且不调用 BiSheng；登录用户、Range 和既有错误语义仍有回归覆盖。
  - _Requirements: REQ-005, REQ-011_
  - _Acceptance: AC-REQ-005-01, AC-REQ-011-04, AC-REQ-011-05_
  - _Verification: V-AC-REQ-005-01, V-AC-REQ-011-04, V-AC-REQ-011-05_
  - _Depends: T041_
  - _Boundary: Portal `backend/tests/test_knowledge_api.py` focused tests only_

- [x] T043 实现 Portal BFF 三路登录门禁
  - Done when: 三个 preview routes 在分享检查和上游调用前读取 Portal session，匿名统一 401；detail route 不变；T042 与既有登录预览回归通过。
  - _Requirements: REQ-005, REQ-011_
  - _Acceptance: AC-REQ-005-01, AC-REQ-011-04, AC-REQ-011-05_
  - _Verification: T042 tests + focused preview/share regression_
  - _Depends: T042_
  - _Boundary: Portal `backend/app/api/routes/knowledge.py` and focused tests only_

- [x] T044 为 Portal 预览水印和匿名 UI 编写失败测试
  - Done when: 测试定义认证用户身份与 Asia/Shanghai 固定挂载日期、目标水印内容、不可交互/不可选择/辅助技术隐藏，以及 DetailPage 匿名不请求 preview/chunks 并显示“登录后预览”的契约；具体三行主部门口径由 T062 覆盖更新。
  - _Requirements: REQ-011_
  - _Acceptance: AC-REQ-011-01, AC-REQ-011-03, AC-REQ-011-04, AC-REQ-011-05_
  - _Verification: V-AC-REQ-011-01, V-AC-REQ-011-03, V-AC-REQ-011-04, V-AC-REQ-011-05_
  - _Depends: T041_
  - _Boundary: Portal `frontend/tests/previewWatermark.test.ts` only_

- [x] T045 实现 Portal 详情预览水印与匿名登录提示
  - Done when: 新共享组件/纯 formatter 接入 DetailPage；登录用户所有 DocumentPreview 模式显示水印，匿名只加载 detail/related、显示登录提示且不请求 preview/chunks；搜索/列表 iframe 复用不复制逻辑；T044、目标回归和 production build 通过。
  - _Requirements: REQ-011_
  - _Acceptance: AC-REQ-011-01, AC-REQ-011-03, AC-REQ-011-04, AC-REQ-011-05_
  - _Verification: T044 tests + file preview regression + Portal frontend build_
  - _Depends: T043, T044_
  - _Boundary: Portal PreviewWatermark component/style/formatter、DetailPage and focused tests only_

- [x] T046 为 BiSheng 知识预览水印编写失败测试
  - Done when: Jest 测试定义认证用户身份、固定北京日期、目标水印内容、`aria-hidden` 和基础层接线；源码范围断言覆盖普通/富媒体知识 viewer，且聊天上传、SOP、Artifact 不新增接线；具体三行主部门口径由 T062 覆盖更新。
  - _Requirements: REQ-011_
  - _Acceptance: AC-REQ-011-02, AC-REQ-011-03, AC-REQ-011-05_
  - _Verification: V-AC-REQ-011-02, V-AC-REQ-011-03, V-AC-REQ-011-05_
  - _Depends: T041_
  - _Boundary: BiSheng `KnowledgePreviewWatermark.test.tsx` and focused source-contract tests only_

- [x] T047 实现 BiSheng 知识预览共享水印
  - Done when: 新组件从 Recoil 当前用户读取身份并接入 `FilePreview`/`RichKnowledgePreview` 成功 viewer 外层；独立、门户、收藏、版本对比和知识引用通过既有复用链路覆盖；播放器/文档交互不被遮挡；T046、目标回归和 client build 通过。
  - _Requirements: REQ-011_
  - _Acceptance: AC-REQ-011-02, AC-REQ-011-03, AC-REQ-011-05_
  - _Verification: T046 tests + knowledge preview regressions + BiSheng client build/check-imports_
  - _Depends: T046_
  - _Boundary: BiSheng FilePreview 水印组件/style、`index.tsx`、`RichKnowledgePreview.tsx` and focused tests only_

- [x] T048 执行预览扩展自动验证并更新 verification
  - Done when: Portal BFF 目标 pytest、Portal frontend test/build、BiSheng client target Jest/build/check-imports、入口/非入口源码扫描和两仓 diff 审计均记录；REQ-011 每个 AC 有 PASS 或 MANUAL_REQUIRED 结论，T030 增补预览视觉/交互/匿名验收。
  - _Requirements: REQ-005, REQ-008, REQ-011_
  - _Acceptance: AC-REQ-005-01, AC-REQ-008-01..04, AC-REQ-011-01..05_
  - _Verification: verification.md fresh evidence + source/diff audit_
  - _Depends: T043, T045, T047_
  - _Boundary: tests, builds, source scans, verification/tasks status only; no production data mutation_

## 阶段 10：下载时按需确保统一 PDF

- [x] T049 更新按需 PDF 扩展规格
  - Done when: requirements 移除缺产物严格 409，定义全部不可用状态、同步持久化、同文件 single-flight、300/60 秒 deadline 和最终提示；design 覆盖共享 processor、两类 Redis lock、一次强制修复、BFF 370 秒；tasks mapping 无孤儿 ID。
  - _Requirements: REQ-002, REQ-006, REQ-007, REQ-008, REQ-010_
  - _Acceptance: AC-REQ-002-01..05, AC-REQ-006-01..05, AC-REQ-007-02, AC-REQ-008-01..04, AC-REQ-010-02_
  - _Verification: spec source scan + traceability review_
  - _Depends: T048_
  - _Boundary: F064 requirements.md, design.md, tasks.md planning content only_

- [x] T050 为按需 generation、共享 processor 与文件锁编写失败测试
  - Done when: 测试覆盖无记录、WAITING/PROCESSING/FAILED、源过期、invalid generation 的选择；ORIGINAL/PARSE_PREVIEW 不复制、GENERATED 上传一次；API/API 与 API/Celery 同文件只有一个 owner，等待方复用；ownership token、TTL、异常释放和最终失败状态。
  - _Requirements: REQ-002, REQ-006, REQ-008_
  - _Acceptance: AC-REQ-002-02..05, AC-REQ-006-02, AC-REQ-006-04, AC-REQ-008-01, AC-REQ-008-02, AC-REQ-008-04_
  - _Verification: V-AC-REQ-002-02..05, V-AC-REQ-006-02, V-AC-REQ-006-04, V-AC-REQ-008-01, V-AC-REQ-008-02, V-AC-REQ-008-04_
  - _Depends: T049_
  - _Boundary: BiSheng PDF Artifact service/repository/worker focused tests only_

- [x] T051 实现共享 processor、按需 generation 与文件级 single-flight
  - Done when: `PdfArtifactProcessor` 从 Celery 外壳提取为 Domain 共享核心；Repository 提供不重复 bump 的按需 generation 语义；API/Celery 共用文件级 Redis ownership lock；等待/生成在 300 秒内返回当前有效引用；不新增 schema、队列、依赖或第二套对象命名；T050 通过。
  - _Requirements: REQ-002, REQ-006, REQ-008_
  - _Acceptance: AC-REQ-002-02..05, AC-REQ-006-02, AC-REQ-006-04, AC-REQ-008-01, AC-REQ-008-02, AC-REQ-008-04_
  - _Verification: T050 tests + existing PDF Artifact worker/service/repository regressions + ruff_
  - _Depends: T050_
  - _Boundary: PDF Artifact Domain service/repository、worker thin adapter、settings/initdb defaults only_

- [x] T052 为下载服务的有效引用、一次修复和分阶段超时编写失败测试
  - Done when: 测试证明有效引用不生成；无引用先生成；对象不存在/空/损坏/SHA 不一致只强制修复一次；修复后继续水印；最终失败无原文件 fallback；PDF 就绪 300 秒和水印 60 秒分别映射 504；用户锁/容量/临时目录全部释放。
  - _Requirements: REQ-002, REQ-003, REQ-006, REQ-007, REQ-010_
  - _Acceptance: AC-REQ-002-01..05, AC-REQ-003-04, AC-REQ-006-02..04, AC-REQ-007-02..03, AC-REQ-010-02_
  - _Verification: V-AC-REQ-002-01..05, V-AC-REQ-003-04, V-AC-REQ-006-02..04, V-AC-REQ-007-02..03, V-AC-REQ-010-02_
  - _Depends: T049_
  - _Boundary: `test_portal_pdf_download_service.py` and narrow endpoint error regressions only_

- [x] T053 将按需 PDF 接入统一下载服务
  - Done when: 下载服务在权限后、个人水印前调用按需服务；本地输入执行 PDF/size/SHA 校验；读失败仅一次强制修复；用户锁 TTL 覆盖 300+60 秒且容量上限覆盖完整准备；dependencies 注入真实实现；T052 通过。
  - _Requirements: REQ-002, REQ-003, REQ-006, REQ-007, REQ-010_
  - _Acceptance: AC-REQ-002-01..05, AC-REQ-003-04, AC-REQ-006-02..04, AC-REQ-007-02..03, AC-REQ-010-02_
  - _Verification: T052 tests + portal/legacy binary endpoint regressions + ruff_
  - _Depends: T051, T052_
  - _Boundary: `portal_pdf_download_service.py`、API dependency、watermark config and focused tests only_

- [x] T054 为 Portal 370 秒代理和两端最终失败提示编写失败测试
  - Done when: Portal settings/client/route 测试定义下载 timeout=370、全局 timeout=30 不变、500/504/409 脱敏文案；Portal 与 BiSheng Client 下载 helper 只在最终非 PDF 响应时抛可展示错误，成功 Blob 行为不变。
  - _Requirements: REQ-006, REQ-007, REQ-010_
  - _Acceptance: AC-REQ-006-01, AC-REQ-006-05, AC-REQ-007-01..02, AC-REQ-010-03..04_
  - _Verification: V-AC-REQ-006-01, V-AC-REQ-006-05, V-AC-REQ-007-01..02, V-AC-REQ-010-03..04_
  - _Depends: T049_
  - _Boundary: Portal BFF/frontend and BiSheng Client focused download tests only_

- [x] T055 实现 Portal 超时和统一最终错误文案
  - Done when: BFF 下载专用 timeout 默认 370 秒；409/500/504 均输出安全中文提示；两端 helper/现有调用方展示最终错误并恢复 pending；不新增轮询、后台任务或原文件 fallback；T054 通过。
  - _Requirements: REQ-006, REQ-007, REQ-010_
  - _Acceptance: AC-REQ-006-01, AC-REQ-006-05, AC-REQ-007-01..02, AC-REQ-010-03..04_
  - _Verification: T054 tests + Portal/BiSheng frontend target tests/builds_
  - _Depends: T053, T054_
  - _Boundary: Portal settings/download error mapping、两端 download helper/error text and focused tests only_

- [x] T056 执行按需 PDF 扩展自动验证并更新 verification
  - Done when: BiSheng Artifact/worker/download/endpoint 目标 pytest+ruff、Portal BFF pytest、两端 frontend download tests/build、配置/部署/source/diff 审计均记录；REQ-002/006/007/008/010 受影响 AC 有 fresh PASS 或 MANUAL_REQUIRED，T030 增补缺失/损坏/同文件并发和 300+60 秒人工验收。
  - _Requirements: REQ-002, REQ-003, REQ-006, REQ-007, REQ-008, REQ-010_
  - _Acceptance: AC-REQ-002-01..05, AC-REQ-003-04, AC-REQ-006-01..05, AC-REQ-007-01..04, AC-REQ-008-01..04, AC-REQ-010-01..04_
  - _Verification: verification.md fresh evidence + source/diff/deployment audit_
  - _Depends: T051, T053, T055_
  - _Boundary: tests, formatting, builds, source scans, verification/tasks status only; no production data mutation_

## 阶段 11：预览水印正文边界回归修复

- [x] T057 记录预览水印越界缺陷与修复设计
  - Done when: REQ-011 新增“只覆盖实际正文 surface”的验收标准；design 记录外层 overlay 根因、Provider/overlay 分离、PDF 按页裁剪和其他格式按正文边界裁剪；范围包含 Portal 与 BiSheng 首页/列表/知识库复用入口。
  - _Requirements: REQ-011_
  - _Acceptance: AC-REQ-011-01, AC-REQ-011-02, AC-REQ-011-03, AC-REQ-011-05, AC-REQ-011-06_
  - _Verification: spec source scan + traceability review_
  - _Depends: T048_
  - _Boundary: F064 requirements.md, design.md, tasks.md planning content only_

- [x] T058 为两端预览水印正文边界编写失败测试
  - Done when: Portal 与 BiSheng 目标测试证明外层 viewer 只提供身份/时间上下文、不直接渲染 overlay；PDF page 与 DOCX/Markdown/HTML/text/spreadsheet/image/chunks 正文 surface 均有 overlay；样式具备容器内绝对定位、裁剪和交互隔离。
  - _Requirements: REQ-011_
  - _Acceptance: AC-REQ-011-01, AC-REQ-011-02, AC-REQ-011-03, AC-REQ-011-05, AC-REQ-011-06_
  - _Verification: V-AC-REQ-011-01..03, V-AC-REQ-011-05, V-AC-REQ-011-06_
  - _Depends: T057_
  - _Boundary: Portal `previewWatermark.test.ts` and BiSheng `KnowledgePreviewWatermark.test.tsx` focused tests only_

- [x] T059 将两端 overlay 下沉到实际文档正文 surface
  - Done when: 两端 Provider 在一次预览中固定同一身份/时间；Portal `DocumentPreview`/`PdfPreview` 与 BiSheng 各格式 Viewer 在实际正文容器内渲染 overlay 并裁剪；完整预览视口、灰色页边和工具栏不再显示水印；富媒体交互不受影响；T058 通过。
  - _Requirements: REQ-011_
  - _Acceptance: AC-REQ-011-01, AC-REQ-011-02, AC-REQ-011-03, AC-REQ-011-05, AC-REQ-011-06_
  - _Verification: T058 tests + focused TypeScript/lint checks_
  - _Depends: T058_
  - _Boundary: 两端预览水印组件/style、文档 Viewer、RichKnowledgePreview and focused tests only_

- [x] T060 执行预览正文边界回归验证并更新 verification
  - Done when: 两端定向测试、静态检查、生产构建、入口/正文 surface 源码扫描和 diff 审计记录；AC-REQ-011-06 有 fresh 自动化结论，并为真实浏览器首页/知识库 PDF、TXT 预览记录人工验收步骤。
  - _Requirements: REQ-011_
  - _Acceptance: AC-REQ-011-01..03, AC-REQ-011-05, AC-REQ-011-06_
  - _Verification: verification.md fresh evidence + build/source/diff audit_
  - _Depends: T059_
  - _Boundary: tests, builds, source scans, verification/tasks status only; no backend or production data mutation_

## 阶段 12：统一三行主部门水印文案

- [x] T061 更新三行水印规格与主部门数据契约
  - Done when: REQ-003/011 明确“主部门-姓名、北京日期、内部资料”三行格式、无主部门只显示姓名、预览与下载同口径；design 覆盖 `/user/info`、Portal auth、client 状态和服务端 repository 边界。
  - _Requirements: REQ-003, REQ-011_
  - _Acceptance: AC-REQ-003-01..03, AC-REQ-011-03_
  - _Verification: spec source scan + traceability review_
  - _Depends: T060_
  - _Boundary: F064 requirements.md, design.md, tasks.md planning content only_

- [x] T062 为用户主部门契约和三行水印编写失败测试
  - Done when: 测试覆盖 `/user/info` 主部门、Portal auth 独立字段、两端预览有/无主部门、下载服务服务端主部门、北京日期、PDF spec 三行约束及旧工号/时间文案消失。
  - _Requirements: REQ-003, REQ-011_
  - _Acceptance: AC-REQ-003-01..03, AC-REQ-011-03_
  - _Verification: V-AC-REQ-003-01..03, V-AC-REQ-011-03_
  - _Depends: T061_
  - _Boundary: focused backend/frontend watermark and auth/user contract tests only_

- [x] T063 实现主部门字段透传与三行水印
  - Done when: `/user/info`、Portal auth、BiSheng client 均使用独立主部门字段；下载从 `UserRepository` 读取主部门；PDF/两端预览统一三行且无部门只显示姓名；T062 通过。
  - _Requirements: REQ-003, REQ-011_
  - _Acceptance: AC-REQ-003-01..03, AC-REQ-011-03_
  - _Verification: T062 tests + focused lint/type checks_
  - _Depends: T062_
  - _Boundary: user info/repository contract、download watermark spec、Portal auth mapping、两端 preview formatter only_

- [x] T064 执行三行水印回归验证并更新 verification
  - Done when: BiSheng backend/client 与 Portal backend/frontend 目标测试、静态检查、构建、旧水印文案扫描及 diff 审计有 fresh evidence；人工步骤更新为三行格式。
  - _Requirements: REQ-003, REQ-011_
  - _Acceptance: AC-REQ-003-01..04, AC-REQ-011-01..03, AC-REQ-011-05..06_
  - _Verification: verification.md fresh evidence + source/diff audit_
  - _Depends: T063_
  - _Boundary: tests, builds, source scans, verification/tasks status only; no production data/config mutation_

## 阶段 13：统一两行身份水印与 PDF 等效预览密度

- [x] T065 更新两行水印与视觉一致性规格
  - Done when: REQ-003/011 明确“主部门-姓名--账号-北京日期 / 首钢股份内部资料，严禁外传，违者必究”两行格式、`external_id` 账号来源、无主部门格式和 PDF/预览等效视觉 token；design 覆盖动态 tile、黑体解析、长字段风险与验证策略。
  - _Requirements: REQ-003, REQ-011_
  - _Acceptance: AC-REQ-003-01..03, AC-REQ-011-03, AC-REQ-011-06..07_
  - _Verification: spec source scan + traceability review_
  - _Depends: T064_
  - _Boundary: F064 requirements.md, design.md, tasks.md planning content only_

- [x] T066 为下载两行身份水印和黑体视觉基准编写失败测试
  - Done when: 后端测试覆盖 `external_id` 优先/遗留回退、主部门存在/缺失、北京时间拼入首行、固定第二行、PDF spec 两行约束、黑体候选和既有 `-35°`/`12pt`/`0.16`/`180pt × 120pt` 参数；旧三行文案失败。
  - _Requirements: REQ-003, REQ-008_
  - _Acceptance: AC-REQ-003-01..04, AC-REQ-008-01_
  - _Verification: V-AC-REQ-003-01..04, V-AC-REQ-008-01_
  - _Depends: T065_
  - _Boundary: `test_pdf_watermark.py`, `test_pdf_watermark_worker.py`, `test_portal_pdf_download_service.py` focused watermark tests only_

- [x] T067 实现下载 PDF 两行身份水印与黑体排版
  - Done when: 下载服务只从当前用户记录和主部门 Repository 构造两行 spec；`PdfWatermarkSpec` 固定两行且黑体 resolver 不优先或静默切换宋体；门户和 BiSheng 共用下载服务输出新文案，T066 通过。
  - _Requirements: REQ-003, REQ-007, REQ-008, REQ-010_
  - _Acceptance: AC-REQ-003-01..04, AC-REQ-007-02, AC-REQ-008-01, AC-REQ-010-03_
  - _Verification: T066 tests + backend ruff/compile_
  - _Depends: T066_
  - _Boundary: `watermark.py`, `portal_pdf_download_service.py` and focused tests only; no API/config/schema change_

- [x] T068 为 Portal 与 BiSheng 两行预览和动态密度编写失败测试
  - Done when: 两端测试覆盖 `externalId` 映射、主部门存在/缺失、两行顺序和固定北京日期；mock `ResizeObserver` 验证初始/resize tile 数随 surface 尺寸变化；样式断言黑体、等效 `16px`、`-35°`、`0.16`、`#737373`、`240px × 160px`，且正文裁剪/交互隔离保持。
  - _Requirements: REQ-003, REQ-011_
  - _Acceptance: AC-REQ-003-01..03, AC-REQ-011-01..03, AC-REQ-011-05..07_
  - _Verification: V-AC-REQ-003-01..03, V-AC-REQ-011-01..03, V-AC-REQ-011-05..07_
  - _Depends: T065_
  - _Boundary: Portal `previewWatermark.test.ts` and BiSheng `KnowledgePreviewWatermark.test.tsx` only_

- [x] T069 实现两端预览两行文案、账号映射和动态密度
  - Done when: Portal 使用既有 `PortalUser.externalId`，BiSheng 将 `/user/info.external_id` 映射为 `TUser.externalId`；两个 Provider 固定两行内容；overlay 移除固定 24 tile/整体旋转/space-around，按 surface 尺寸动态铺设 PDF 等效样式且仍只覆盖正文；T068 通过。
  - _Requirements: REQ-003, REQ-011_
  - _Acceptance: AC-REQ-003-01..03, AC-REQ-011-01..03, AC-REQ-011-05..07_
  - _Verification: T068 tests + target lint/type/import checks_
  - _Depends: T068_
  - _Boundary: Portal/BiSheng preview formatter/component/style、BiSheng current-user mapping/types and focused tests only_

- [x] T070 执行两行水印自动回归、PDF 渲染和安全复核
  - Done when: 后端目标 pytest/ruff、两端预览目标测试/lint/build、旧三行文案和固定 24 tile 扫描、两仓 diff 审计均有 fresh evidence；生成含长中文身份的代表 PDF 并渲染 PNG 目检字体、顺序、密度、重叠和正文可读性；verification 更新，未部署浏览器项保留 MANUAL_REQUIRED。
  - _Requirements: REQ-003, REQ-007, REQ-008, REQ-010, REQ-011_
  - _Acceptance: AC-REQ-003-01..04, AC-REQ-007-02, AC-REQ-008-01..04, AC-REQ-010-03, AC-REQ-011-01..03, AC-REQ-011-05..07_
  - _Verification: verification.md fresh evidence + rendered PNG + security/source/diff audit_
  - _Depends: T067, T069_
  - _Boundary: tests, formatting, builds, temporary `tmp/pdfs/` visual artifacts, verification/tasks status only; no production data/config mutation_

## 阶段 14：自适应错位水印与 SVG pattern

- [x] T071 更新无重叠自适应视觉规格
  - Done when: REQ-003/011 明确 PDF/预览按最长行实际旋转包围盒加留白计算单元、`320pt × 220pt` / `427px × 293px` 最小值、透明度 `0.11`、奇偶行错位 50%、代表 A4 约 6 至 8 组及前端常量级 SVG pattern；design 记录公式、边界、备选和性能取舍。
  - _Requirements: REQ-003, REQ-011_
  - _Acceptance: AC-REQ-003-01..04, AC-REQ-011-01..03, AC-REQ-011-05..07_
  - _Verification: spec source scan + traceability review_
  - _Depends: T070_
  - _Boundary: F064 requirements.md, design.md, tasks.md planning content only_

- [x] T072 为 PDF 自适应错位布局编写失败测试
  - Done when: 测试覆盖普通/长/超长两行字体度量、旋转包围盒公式、最小与自动扩展步长、相邻包围盒不重叠、奇偶行半步错位、A4 代表密度、`0.11` 透明度，以及多页/横向/旋转/正文保持回归；旧固定 `180pt × 120pt` 断言失败。
  - _Requirements: REQ-003_
  - _Acceptance: AC-REQ-003-01..04_
  - _Verification: V-AC-REQ-003-01..04_
  - _Depends: T071_
  - _Boundary: `src/backend/test/knowledge/pdf/test_pdf_watermark.py` only_

- [x] T073 实现 PDF 字体度量、自适应单元和错位锚点
  - Done when: 水印引擎使用最终选择字体测量两行宽度，按统一公式计算旋转包围盒和 `max` 步长；锚点按行错位 50%，不截断或缩小长身份；worker 传输字段与 service 调用契约不变、默认视觉值同步更新且 T072 通过。
  - _Requirements: REQ-003, REQ-007, REQ-008, REQ-010_
  - _Acceptance: AC-REQ-003-01..04, AC-REQ-007-02, AC-REQ-008-01, AC-REQ-010-03_
  - _Verification: T072 tests + backend ruff/format/compile_
  - _Depends: T072_
  - _Boundary: `watermark.py` and focused PDF tests only; no service/API/config/schema change_

- [x] T074 为 Portal 与 BiSheng 自适应 SVG pattern 编写失败测试
  - Done when: 两端测试覆盖普通/长/超长宽度、旋转包围盒、最小与扩展单元、奇偶行 50% 错位、`0.11`、`16px`、`-35°`、`#737373`；组件必须输出单个 SVG/pattern/rect 和常量两组文字，不含 `ResizeObserver`、tile 数组或固定 `240px × 160px`。
  - _Requirements: REQ-003, REQ-011_
  - _Acceptance: AC-REQ-003-01..03, AC-REQ-011-01..03, AC-REQ-011-05..07_
  - _Verification: V-AC-REQ-003-01..03, V-AC-REQ-011-01..03, V-AC-REQ-011-05..07_
  - _Depends: T071_
  - _Boundary: Portal `previewWatermark.test.ts` and BiSheng `KnowledgePreviewWatermark.test.tsx` only_

- [x] T075 实现两端文字度量和常量级错位 SVG pattern
  - Done when: 两端共享同一纯布局公式和等效 token，运行时用 Canvas `measureText` 并在字体 ready 后复算；无 Canvas 时使用保守字符宽度估算；每个 overlay 只渲染一个 SVG pattern、两组两行文字和一个 rect，surface 自动平铺且继续由正文边界裁剪，T074 通过。
  - _Requirements: REQ-003, REQ-011_
  - _Acceptance: AC-REQ-003-01..03, AC-REQ-011-01..03, AC-REQ-011-05..07_
  - _Verification: T074 tests + target lint/type/import checks_
  - _Depends: T074_
  - _Boundary: Portal/BiSheng preview formatter/component/style and focused tests only; no viewer/auth/API change_

- [x] T076 执行无重叠视觉回归、构建和安全复核
  - Done when: 后端目标 pytest/ruff/compile、两端目标测试/lint/build、旧固定步长/ResizeObserver/tile 数组扫描和两仓 diff 审计有 fresh evidence；生成普通及长中文账号代表 PDF，用 Poppler 渲染 PNG 目检约 6 至 8 组、无重叠、错位、正文可读和边界裁剪；verification 更新，T030 保持 MANUAL_REQUIRED。
  - _Requirements: REQ-003, REQ-007, REQ-008, REQ-010, REQ-011_
  - _Acceptance: AC-REQ-003-01..04, AC-REQ-007-02, AC-REQ-008-01..04, AC-REQ-010-03, AC-REQ-011-01..03, AC-REQ-011-05..07_
  - _Verification: verification.md fresh evidence + rendered PNGs + security/source/diff audit_
  - _Depends: T073, T075_
  - _Boundary: tests, formatting, builds, temporary `tmp/pdfs/` artifacts, verification/tasks status only; no production data/config mutation_

## 阶段 15：下载与预览轻度增密

- [x] T077 更新轻度增密规格
  - Done when: REQ-003/011 与 design 将 PDF 最小单元调整为 `288pt × 200pt`、两端预览等效最小单元调整为 `384px × 267px`，代表 A4 目标约 8 至 10 组；字号、角度、透明度、颜色、留白、错位和长文本扩距规则明确保持不变。
  - _Requirements: REQ-003, REQ-011_
  - _Acceptance: AC-REQ-003-01..04, AC-REQ-011-01..03, AC-REQ-011-05..07_
  - _Verification: spec source scan + traceability review_
  - _Depends: T076_
  - _Boundary: F064 requirements.md, design.md, tasks.md planning content only_

- [x] T078 为 PDF 与两端预览轻度增密编写失败测试
  - Done when: 后端测试要求 `288pt × 200pt` 最小步长及普通 A4 约 8 至 10 组；Portal 与 BiSheng 测试要求 `384px × 267px` 最小 pattern，长身份仍按旋转包围盒加留白扩展且不重叠；旧最小值断言产生红灯。
  - _Requirements: REQ-003, REQ-011_
  - _Acceptance: AC-REQ-003-01..04, AC-REQ-011-01..03, AC-REQ-011-05..07_
  - _Verification: V-AC-REQ-003-01..04, V-AC-REQ-011-01..03, V-AC-REQ-011-05..07_
  - _Depends: T077_
  - _Boundary: PDF watermark and Portal/BiSheng preview watermark focused tests only_

- [x] T079 实现下载与预览轻度增密常量
  - Done when: PDF engine/worker 默认最小步长改为 `288pt × 200pt`，Portal/BiSheng 预览最小单元改为 `384px × 267px`；自适应包围盒、留白、错位、文案和视觉 token 不变，T078 通过。
  - _Requirements: REQ-003, REQ-007, REQ-008, REQ-010, REQ-011_
  - _Acceptance: AC-REQ-003-01..04, AC-REQ-007-02, AC-REQ-008-01, AC-REQ-010-03, AC-REQ-011-01..03, AC-REQ-011-05..07_
  - _Verification: T078 tests + target lint/type/import checks_
  - _Depends: T078_
  - _Boundary: `watermark.py`, `watermark_worker.py`, Portal/BiSheng preview layout constants and focused tests only; no API/config/schema/deployment change_

- [x] T080 执行轻度增密回归、构建、渲染与差异审计
  - Done when: 后端目标 pytest/ruff/compile、两端目标测试/lint/build、最小单元源码扫描和两仓 diff 审计有 fresh evidence；普通及长身份 PDF 用 Poppler 渲染，普通 A4 约 8 至 10 组、长身份无重叠；verification 更新且 T030 保持发布环境人工门禁。
  - _Requirements: REQ-003, REQ-007, REQ-008, REQ-010, REQ-011_
  - _Acceptance: AC-REQ-003-01..04, AC-REQ-007-02, AC-REQ-008-01..04, AC-REQ-010-03, AC-REQ-011-01..03, AC-REQ-011-05..07_
  - _Verification: verification.md fresh evidence + rendered PDFs/PNGs + source/diff audit_
  - _Depends: T079_
  - _Boundary: tests, formatting, builds, temporary `tmp/pdfs/` visual artifacts, verification/tasks status only; no production data/config mutation_

## 阶段 16：下载与预览中等增密

- [x] T081 更新中等增密规格
  - Done when: REQ-003/011 与 design 将 PDF 最小单元调整为 `240pt × 180pt`、两端预览等效最小单元调整为 `320px × 240px`，代表 A4 目标约 12 至 14 组；字号、角度、透明度、颜色、留白、错位和长文本扩距规则明确保持不变。
  - _Requirements: REQ-003, REQ-011_
  - _Acceptance: AC-REQ-003-01..04, AC-REQ-011-01..03, AC-REQ-011-05..07_
  - _Verification: spec source scan + traceability review_
  - _Depends: T080_
  - _Boundary: F064 requirements.md, design.md, tasks.md planning content only_

- [x] T082 为 PDF 与两端预览中等增密编写失败测试
  - Done when: 后端测试要求 `240pt × 180pt` 最小步长及普通 A4 约 12 至 14 组；Portal 与 BiSheng 测试要求 `320px × 240px` 最小 pattern，长身份仍按旋转包围盒加留白扩展且不重叠；旧最小值断言产生红灯。
  - _Requirements: REQ-003, REQ-011_
  - _Acceptance: AC-REQ-003-01..04, AC-REQ-011-01..03, AC-REQ-011-05..07_
  - _Verification: V-AC-REQ-003-01..04, V-AC-REQ-011-01..03, V-AC-REQ-011-05..07_
  - _Depends: T081_
  - _Boundary: PDF watermark and Portal/BiSheng preview watermark focused tests only_

- [x] T083 实现下载与预览中等增密常量
  - Done when: PDF engine/worker 默认最小步长改为 `240pt × 180pt`，Portal/BiSheng 预览最小单元改为 `320px × 240px`；自适应包围盒、留白、错位、文案和视觉 token 不变，T082 通过。
  - _Requirements: REQ-003, REQ-007, REQ-008, REQ-010, REQ-011_
  - _Acceptance: AC-REQ-003-01..04, AC-REQ-007-02, AC-REQ-008-01, AC-REQ-010-03, AC-REQ-011-01..03, AC-REQ-011-05..07_
  - _Verification: T082 tests + target lint/type/import checks_
  - _Depends: T082_
  - _Boundary: `watermark.py`, `watermark_worker.py`, Portal/BiSheng preview layout constants and focused tests only; no API/config/schema/deployment change_

- [x] T084 执行中等增密回归、构建、渲染与差异审计
  - Done when: 后端目标 pytest/ruff/compile、两端目标测试/lint/build、最小单元源码扫描和两仓 diff 审计有 fresh evidence；普通及长身份 PDF 用 Poppler 渲染，普通 A4 约 12 至 14 组、长身份无重叠；verification 更新且 T030 保持发布环境人工门禁。
  - _Requirements: REQ-003, REQ-007, REQ-008, REQ-010, REQ-011_
  - _Acceptance: AC-REQ-003-01..04, AC-REQ-007-02, AC-REQ-008-01..04, AC-REQ-010-03, AC-REQ-011-01..03, AC-REQ-011-05..07_
  - _Verification: verification.md fresh evidence + rendered PDFs/PNGs + source/diff audit_
  - _Depends: T083_
  - _Boundary: tests, formatting, builds, temporary `tmp/pdfs/` visual artifacts, verification/tasks status only; no production data/config mutation_

## 阶段 17：缩短间距并统一日期与方向

- [x] T085 更新间距、日期和最终视觉方向规格
  - Done when: REQ-003/011 与 design 明确 PDF 使用 `180pt × 135pt` 最小步长和 `36pt/27pt` 留白，两端预览使用等效 `240px × 180px` 最小单元和 `48px/36px` 留白；日期为 `YYYY/MM/DD`；三端最终视觉方向为左下向右上 `/`；长文字保持字号并自适应扩距。
  - _Requirements: REQ-003, REQ-011_
  - _Acceptance: AC-REQ-003-01..04, AC-REQ-011-01..03, AC-REQ-011-05..07_
  - _Verification: spec source scan + traceability review_
  - _Depends: T084_
  - _Boundary: F064 requirements.md, design.md, tasks.md planning content only_

- [x] T086 为三端新间距、日期和方向编写失败测试
  - Done when: 后端测试要求新最小步长/留白、`YYYY/MM/DD` 和 PDF 最终 `/` 方向；Portal/BiSheng 测试要求新最小单元/留白、斜杠日期和 SVG `/` 方向；长身份仍按旋转包围盒扩展且不重叠，旧实现产生预期红灯。
  - _Requirements: REQ-003, REQ-011_
  - _Acceptance: AC-REQ-003-01..04, AC-REQ-011-01..03, AC-REQ-011-05..07_
  - _Verification: V-AC-REQ-003-01..04, V-AC-REQ-011-01..03, V-AC-REQ-011-05..07_
  - _Depends: T085_
  - _Boundary: PDF watermark/download service and Portal/BiSheng preview focused tests only_

- [x] T087 实现三端间距、日期和方向统一
  - Done when: PDF engine、下载服务与 Portal/BiSheng 预览采用活动视觉 token；PDF 和 SVG 分别校准旋转符号但最终均为 `/`；日期均为 `YYYY/MM/DD`；身份、字号、颜色、透明度、错位和正文边界保持不变，T086 通过。
  - _Requirements: REQ-003, REQ-007, REQ-008, REQ-010, REQ-011_
  - _Acceptance: AC-REQ-003-01..04, AC-REQ-007-02, AC-REQ-008-01, AC-REQ-010-03, AC-REQ-011-01..03, AC-REQ-011-05..07_
  - _Verification: T086 tests + target lint/type/import checks_
  - _Depends: T086_
  - _Boundary: `watermark.py`, `watermark_worker.py`, `portal_pdf_download_service.py`, Portal/BiSheng preview watermark formatter/layout and focused tests only; no API/config/schema/deployment change_

- [x] T088 执行目标回归、构建、渲染与差异审计
  - Done when: 后端目标 pytest/ruff/compile、两端目标测试/lint/build、旧活动 token/旧日期源码扫描和两仓 diff 审计有 fresh evidence；普通及长身份 PDF 渲染确认 `/` 方向、斜杠日期、间距缩短和无重叠；verification 更新且 T030 保持发布环境人工门禁。
  - _Requirements: REQ-003, REQ-007, REQ-008, REQ-010, REQ-011_
  - _Acceptance: AC-REQ-003-01..04, AC-REQ-007-02, AC-REQ-008-01..04, AC-REQ-010-03, AC-REQ-011-01..03, AC-REQ-011-05..07_
  - _Verification: verification.md fresh evidence + rendered PDFs/PNGs + source/diff audit_
  - _Depends: T087_
  - _Boundary: tests, formatting, builds, temporary visual artifacts, verification/tasks status only; no production data/config mutation_

## 阶段 18：修复预览 SVG pattern 切片

- [x] T089 记录错位行被 pattern tile 裁剪的缺陷与全尺寸 SVG 决策
  - Done when: REQ-011 新增回归验收，明确正文内部水印完整、仅真实正文边缘可裁剪；design 记录根因、全尺寸 SVG 逐坐标方案、ResizeObserver 和接受节点增长的取舍。
  - _Requirements: REQ-011_
  - _Acceptance: AC-REQ-011-01..08_
  - _Verification: spec source scan + traceability review_
  - _Depends: T088_
  - _Boundary: F064 requirements.md, design.md, tasks.md planning content only_

- [x] T090 为两端逐坐标全尺寸 SVG 编写失败测试
  - Done when: Portal 与 BiSheng 测试覆盖普通/长文字步长、给定 surface 宽高的行列坐标、奇数行半步错位、尺寸增长增加坐标、ResizeObserver 初始/变更重铺、组件无 `<pattern>` 且每个锚点有完整两行；旧实现产生预期红灯。
  - _Requirements: REQ-011_
  - _Acceptance: AC-REQ-011-01..03, AC-REQ-011-05..08_
  - _Verification: V-AC-REQ-011-01..03, V-AC-REQ-011-05..08_
  - _Depends: T089_
  - _Boundary: Portal `previewWatermark.test.ts`、BiSheng `KnowledgePreviewWatermark.test.tsx` only_

- [x] T091 实现 Portal 与 BiSheng 全尺寸 SVG 逐坐标水印
  - Done when: 两端保留现有身份、日期、视觉 token、文字度量和正文 surface 接线；新增纯坐标生成与 surface 尺寸观察，移除 `<pattern>/<rect>`，在全尺寸 SVG 内为每个锚点绘制独立两行水印；T090 通过。
  - _Requirements: REQ-011_
  - _Acceptance: AC-REQ-011-01..03, AC-REQ-011-05..08_
  - _Verification: T090 focused tests + target lint/type/import checks_
  - _Depends: T090_
  - _Boundary: 两端预览水印组件、纯布局工具和对应样式；不改 viewer 接线、后端、PDF、配置、依赖或数据_

- [x] T092 执行两端回归、构建、浏览器视觉与差异审计
  - Done when: Portal/BiSheng 目标测试、ESLint/import、生产构建和两仓 diff 审计有 fresh evidence；普通/长身份、宽高 resize 与长正文通过真实浏览器截图，正文内部无残缺、仅真实边缘裁剪；verification 更新且 T030 保持发布环境人工门禁。
  - _Requirements: REQ-011_
  - _Acceptance: AC-REQ-011-01..08_
  - _Verification: verification.md fresh evidence + browser screenshots + source/diff audit_
  - _Depends: T091_
  - _Boundary: tests, builds, temporary visual artifacts, verification/tasks status only; no production data/config mutation_

## 阶段 19：登录态问答正文水印

- [x] T093 更新问答水印需求、设计与入口矩阵
  - Done when: 新增 REQ-012 与 AC-REQ-012-01..08，明确 Portal/BiSheng 登录态入口、正文边界、空/加载/生成/错误状态、滚动/resize、guest/share 排除、workflow/URL iframe 单层责任和 `0.11` 视觉口径；design 与 tasks 可追踪一致。
  - _Requirements: REQ-012_
  - _Acceptance: AC-REQ-012-01..08_
  - _Verification: spec source scan + traceability review_
  - _Depends: T092_
  - _Boundary: F064 requirements.md, design.md, tasks.md planning content only_

- [x] T094 为 Portal 问答正文与 iframe 水印责任编写失败测试
  - Done when: 测试覆盖 `SmartQaWorkspace` 登录用户正文 surface、匿名无 overlay、composer/sidebar 排除、第三方 URL iframe 宿主覆盖、workflow iframe 宿主不覆盖、共享 preview formatter/layout 和透明度单一来源；旧实现产生预期红灯。
  - _Requirements: REQ-012_
  - _Acceptance: AC-REQ-012-01, AC-REQ-012-02, AC-REQ-012-05..08_
  - _Verification: V-AC-REQ-012-01, V-AC-REQ-012-02, V-AC-REQ-012-05..08_
  - _Depends: T093_
  - _Boundary: Portal `frontend/tests/chatWatermark.test.ts` and existing preview watermark target tests only_

- [x] T095 为 BiSheng 问答 surface、状态与排除边界编写失败测试
  - Done when: 测试覆盖默认关闭/显式 enabled、AiChatMessages 空/加载/消息 surface、AppChat 登录/guest/readOnly、主问答 shareToken、知识空间、单文档/订阅面板及 workflow 认证入口；旧实现产生预期红灯。
  - _Requirements: REQ-012_
  - _Acceptance: AC-REQ-012-03..08_
  - _Verification: V-AC-REQ-012-03..08_
  - _Depends: T093_
  - _Boundary: BiSheng client focused watermark/chat tests only_

- [x] T096 实现 Portal 本地问答与 URL iframe 宿主水印
  - Done when: Portal Provider 可在不引入知识预览 root 外壳时复用；`SmartQaWorkspace` 只在有当前用户时覆盖 `qaContent`；URL iframe frame wrap 覆盖一层；workflow iframe 不增加宿主 overlay；透明度前端单一来源为 `0.11`；T094 通过。
  - _Requirements: REQ-012_
  - _Acceptance: AC-REQ-012-01, AC-REQ-012-02, AC-REQ-012-05..08_
  - _Verification: T094 focused tests + target ESLint/type check_
  - _Depends: T094_
  - _Boundary: Portal PreviewWatermark/QAPage/AppsPage/styles and focused tests only; no BFF/API/config changes_

- [x] T097 实现 BiSheng 全部登录态问答正文显式水印
  - Done when: 提供默认关闭的当前用户 watermarked surface；AiChatMessages、主问答、AppChat、认证 standalone、KnowledgeAiPanel、AiAssistantPanel 的已确认正文/空状态显式启用；guest/share/readOnly、header/input/history/citation 保持关闭；T095 通过。
  - _Requirements: REQ-012_
  - _Acceptance: AC-REQ-012-03..08_
  - _Verification: T095 focused tests + import/type checks_
  - _Depends: T095_
  - _Boundary: BiSheng client watermark/chat/panel components and focused tests only; no backend/platform/config changes_

- [ ] T098 执行问答水印回归、构建、浏览器视觉与交互审计
  - Done when: 两端目标测试、ESLint/import、生产构建和 diff/source scope 审计有 fresh evidence；桌面/移动、空/长会话、resize、workflow/URL iframe、guest/share 排除通过浏览器视觉与交互验证；verification 更新且 T030 保持发布环境人工门禁。
  - _Requirements: REQ-011, REQ-012_
  - _Acceptance: AC-REQ-011-03, AC-REQ-011-05..08, AC-REQ-012-01..08_
  - _Verification: verification.md fresh evidence + browser screenshots/interaction + source/diff audit_
  - _Depends: T096, T097_
  - _Boundary: tests, builds, temporary browser artifacts, verification/tasks status only; no production data/config mutation_

## 阶段 20：智能写作展示时机与全端样式一致性 Bugfix

- [x] T099 记录复现、期望行为、根因和最小修复边界
  - Done when: requirements 记录智能写作模板初始页误显示、PDF `0.31` 与全端 `0.11` 漂移、期望行为、影响和复现；design 记录根因、等效视觉 token、修复策略、备选与回滚。
  - _Requirements: REQ-003, REQ-011, REQ-012_
  - _Acceptance: AC-REQ-003-01, AC-REQ-011-07, AC-REQ-012-01, AC-REQ-012-05_
  - _Verification: spec traceability review_
  - _Depends: T097_
  - _Boundary: F064 requirements.md, design.md, tasks.md only_

- [x] T100 建立智能写作模板态和 PDF 透明度失败回归
  - Done when: Portal 测试要求智能写作只在 `hasConversation` 会话态渲染 overlay，独立智能问答保持覆盖；后端默认 spec/实际 PDF trace 精确要求 `0.11`；旧实现产生预期红灯。
  - _Requirements: REQ-003, REQ-011, REQ-012_
  - _Acceptance: AC-REQ-003-01, AC-REQ-011-07, AC-REQ-012-01, AC-REQ-012-05_
  - _Verification: Portal chat watermark target test + backend PDF watermark target test_
  - _Depends: T099_
  - _Boundary: Portal chat watermark test and BiSheng PDF watermark test only_

- [x] T101 最小修复展示条件和 PDF 默认透明度
  - Done when: Portal 仅在 `!isSmartAppsMode || hasConversation` 时渲染问答 overlay；`PdfWatermarkSpec.opacity=0.11`；其他入口、视觉 token、接口和数据保持不变；T100 通过。
  - _Requirements: REQ-003, REQ-011, REQ-012_
  - _Acceptance: AC-REQ-003-01, AC-REQ-011-07, AC-REQ-012-01, AC-REQ-012-05_
  - _Verification: T100 focused regression_
  - _Depends: T100_
  - _Boundary: Portal QAPage.tsx and BiSheng watermark.py only_

- [ ] T102 执行相关回归、构建、浏览器与差异审计
  - Done when: backend PDF、Portal、BiSheng preview/chat 目标测试和两端构建通过；浏览器验证智能写作模板态无水印且会话态显示；verification 记录新鲜证据和环境缺口。
  - _Requirements: REQ-003, REQ-011, REQ-012_
  - _Acceptance: AC-REQ-003-01, AC-REQ-011-07, AC-REQ-012-01, AC-REQ-012-05_
  - _Verification: focused tests + builds + browser DOM/visual audit + diff check_
  - _Depends: T101_
  - _Boundary: verification/tasks status and temporary browser artifacts only; no config/data/dependency changes_

## 阶段 21：全端水印透明度调整为 0.31

- [x] T103 更新最新透明度需求与设计
  - Done when: REQ-003/011/012 的当前验收基准为 `0.31`；requirements/design 记录该决定覆盖此前 `0.11`，并明确其他视觉 token、显示时机、接口、配置和数据不变。
  - _Requirements: REQ-003, REQ-011, REQ-012_
  - _Acceptance: AC-REQ-003-01, AC-REQ-011-07, AC-REQ-012-05_
  - _Verification: spec traceability review_
  - _Depends: T101_
  - _Boundary: F064 requirements.md and design.md only_

- [x] T104 用失败回归驱动四端透明度统一
  - Done when: Portal/BiSheng layout、PDF 默认 spec/实际 trace 测试先以旧 `0.11` 失败；Portal、BiSheng、PDF 主进程和 worker 缺省值均为 `0.31`；目标测试转绿。
  - _Requirements: REQ-003, REQ-011, REQ-012_
  - _Acceptance: AC-REQ-003-01, AC-REQ-011-07, AC-REQ-012-05_
  - _Verification: focused frontend/backend watermark tests_
  - _Depends: T103_
  - _Boundary: 四个透明度来源及对应目标测试；不修改其他视觉 token_

- [x] T105 执行关联回归、构建与差异审计
  - Done when: 后端水印/worker/下载关联矩阵、两端预览/问答测试、两端生产构建、静态检查和 diff check 通过；verification 记录红绿证据、告警和人工视觉缺口。
  - _Requirements: REQ-003, REQ-011, REQ-012_
  - _Acceptance: AC-REQ-003-01, AC-REQ-011-07, AC-REQ-012-05_
  - _Verification: focused tests + builds + static checks + diff audit_
  - _Depends: T104_
  - _Boundary: tests/builds/verification/tasks only；不修改配置、依赖或数据_

## 覆盖矩阵 Coverage Matrix

| Requirement | Acceptance Criteria | Tasks | Verification |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..04 | T014, T015, T020..T026, T028..T030 | V-AC-REQ-001-01..04 |
| REQ-002 | AC-REQ-002-01..05 | T001, T010..T013, T029, T030, T049-T053, T056 | V-AC-REQ-002-01..05 |
| REQ-003 | AC-REQ-003-01..04 | T004..T007, T010..T013, T029, T030, T061-T088, T099-T105 | V-AC-REQ-003-01..04 |
| REQ-004 | AC-REQ-004-01..04 | T010, T011, T014, T015, T020, T021, T024, T025, T027, T029, T030 | V-AC-REQ-004-01..04 |
| REQ-005 | AC-REQ-005-01..05 | T008, T009, T011, T014..T017, T020, T021, T025, T027, T029, T030 | V-AC-REQ-005-01..05 |
| REQ-006 | AC-REQ-006-01..05 | T002, T003, T006, T007, T012..T014, T018..T025, T029, T030, T049-T056 | V-AC-REQ-006-01..05 |
| REQ-007 | AC-REQ-007-01..04 | T002, T003, T006..T09, T012..T15, T018..T26, T028..T030, T033-T037, T040, T049, T052-T056, T079-T080, T083-T084, T087-T088 | V-AC-REQ-007-01..04 |
| REQ-008 | AC-REQ-008-01..04 | T001..T003, T005, T015, T028..T030, T033, T035, T037, T040, T049-T051, T056, T079-T080, T083-T084, T087-T088 | V-AC-REQ-008-01..04 |
| REQ-009 | AC-REQ-009-01..04 | T028..T033, T038-T040 | V-AC-REQ-009-01..04 |
| REQ-010 | AC-REQ-010-01..04 | T033-T040, T049, T052-T056, T079-T080, T083-T084, T087-T088 | V-AC-REQ-010-01..04 |
| REQ-011 | AC-REQ-011-01..08 | T041-T048, T057-T092, T099-T105, T030 | V-AC-REQ-011-01..08 |
| REQ-012 | AC-REQ-012-01..08 | T093-T105, T030 | V-AC-REQ-012-01..08 |

## 任务质量门 Task Quality Gate

- [x] Every task references at least one requirement ID.
- [x] Every behavioral task references acceptance criteria.
- [x] Every acceptance criterion is covered by at least one task or verification entry.
- [x] Every task has an observable done condition.
- [x] Dependencies are explicit where ordering is not obvious.
- [x] Boundary annotations prevent unrelated code edits.
- [x] No task implements work outside requirements or design.

## 实现记录 Implementation Notes

- 当前停止点为 T001-T029、T031-T097 已完成；T030/T098 需要发布环境、真实登录态、代表性文件和真实业务入口条件，保持待执行。
- T094/T095 已先确认旧实现红灯；T096/T097 已完成 Portal 本地 QA/URL iframe 与 BiSheng 主问答、App/Agent、workflow、知识空间、单文档及订阅问答正文接线。T098 保留为真实登录态、多入口、桌面/移动和长会话视觉门禁。
- F063 有效引用可能指向 ORIGINAL、PARSE_PREVIEW 或 GENERATED，本 Feature 对三者只读且不改变对象生命周期。
- BFF 分享 session v2 切换会使旧 `portal_share_access` cookie 重新验证，这是已接受的安全行为变化。
- 成功遥测只表示“首个 PDF 文件块已发送”，不表示浏览器完整落盘。
- 历史补齐脚本由用户负责，本 Feature 只消费上线门禁证据。
- 用户随后明确确认完整实施，范围扩展至 T001-T030；历史补齐脚本仍由用户负责。
- T031/T032 的自动化证据记录于 `verification.md`；整文件历史回归仍有与本次无关的既有失败，因此不得将 F064 标记为整体 VERIFIED。
- 2026-07-21 用户重新确认完整实施范围；T001 登记 F064 只读依赖 F063，并记录两个仓库脏工作树与测试基线。
- T002 先以缺少 `KnowledgePdfWatermarkConf` 的导入错误建立红灯；T003 完成后 12 个配置、DTO、入口归一及错误码测试通过。
- T004/T006 分别以缺少水印引擎和 worker 模块建立红灯；T005/T007 完成后 9 个水印、中文字体、旋转页面、损坏/加密输入、stdin 脱敏及 terminate/kill/reap 测试通过。
- T008-T015 按 grant → live recheck → 下载编排 → endpoint 顺序实施；新增安全矩阵、三类 F063 引用、权限/身份、分块读取、并发/Redis ownership、首块遥测、断连清理和真实 HTTP 状态测试均通过。
- T016-T021 完成 Redis v2 分享会话、登录 session 绑定、grant 服务端隔离、70 秒下载专用超时、BFF 非缓冲流式代理、安全 header 与错误映射；旧 `download-event` 保留为无副作用兼容接口。
- T022-T027 完成 Fetch/Blob 统一下载工具、搜索/列表/详情按钮、首页/相关推荐/专家问答/QA 引用来源透传、访客与 view-only 隐藏，以及分享重新验证行为。
- 安全复核补充验证并修复两项真实链路边界：Redis 剩余 TTL 不足一秒时向上取整；分享 grant 的 `exp` 钳制到分享链接到期点，且下载服务可只凭服务端 header grant 还原并实时复核 share token。
- 生命周期复核补充生成任务取消用例；`CancelledError` 现会在继续向上传播前清理临时目录、用户锁和进程容量。
- T028/T029 已完成目标回归、生产构建、静态检查和差异审计；Portal BFF 与 Portal frontend 全量基线仍有既有失败，详见 `verification.md`，目标用例均通过。
- 2026-07-21 用户将范围扩展为独立门户与 BiSheng 门户全部单文件入口；确认隐藏门户文件夹下载、继续下线批量下载，并收口旧 `original_url/preview_url` endpoint。T033-T040 已完成，自动验证证据见 `verification.md`；仅 T030 发布环境人工门禁待执行。
- 2026-07-21 用户确认先以 CSS 覆盖层实现两端全部知识预览水印，并将匿名分享访问收紧为仅元数据/摘要可见；T041 完成规格对齐，T042-T048 进入 Test-First 实施。
- T042-T048 已完成：Portal BFF 三条正文接口匿名 401 且不触发上游；Portal 详情页匿名不请求正文并显示登录提示；两端知识预览基础层已建立 CSS 水印。T061-T064 随后把文案更新为固定挂载时北京日期的三行主部门口径；目标测试、构建、lint/import、入口范围和 diff 审计证据见 `verification.md`；仅 T030 人工门禁待执行。
- 2026-07-21 用户将下载前提从“缺产物严格 409”改为“下载请求同步生成并持久化”；确认当前请求等待、PDF 就绪 300 秒、水印 60 秒、Portal 约 370 秒，以及无记录/非成功/源过期/对象丢失或损坏/SHA 不一致全部触发一次修复，同文件并发共享结果。T049-T056 已按 Test-First 完成实现与验证。
- 2026-07-21 用户反馈首页与知识库文件预览水印越过白色文档区域进入灰色页边；确认 Portal 与 BiSheng 全部知识预览统一修复。根因为 overlay 挂在完整 viewer 外层并以负 inset 扩张，T057 已完成规格对齐，T058-T060 进入 Test-First 实施。
- T058-T060 已完成：两端将固定身份/时间的 Provider 与 overlay 分离；PDF overlay 下沉到单页/画布，其他格式下沉到白色正文或媒体 surface 并由 `overflow:hidden` 裁剪。Portal 3 项、BiSheng 3 项目标测试、目标 ESLint/import check、两端生产构建和源码边界扫描通过；真实浏览器视觉仍由 T030 验收。
- T061-T064 已完成：`/user/info`、Portal auth 和 BiSheng client 增加独立主部门字段；下载通过 `UserRepository` 读取主部门；PDF 与两端预览统一输出“主部门-姓名 / YYYY-MM-DD / 首钢集团内部资料”三行，无主部门时第一行只显示姓名。自动化与构建证据见 `verification.md`。
- 2026-07-22 用户将最终文案调整为“主部门-姓名--用户账号-YYYY-MM-DD / 首钢股份内部资料，严禁外传，违者必究”两行，并要求下载与两端预览统一黑体、等效字号、顺序、角度和密度；T065 已完成规格对齐，T066-T070 按 Test-First 实施。
- T066-T070 已完成：下载服务优先使用当前用户 `external_id`，无值时回退登录账号；PDF spec 固定两行并移除宋体候选；两端预览使用等效 `16px`、`-35°`、`0.16`、`240px × 160px` 视觉 token，按正文 surface 尺寸动态铺设。后端 40 项回归、两端目标测试/静态检查/生产构建和代表 PDF 渲染均通过，仅 T030 发布环境人工门禁待执行。
- 2026-07-22 用户反馈两行身份在当前固定间距下过密重叠，并确认采用推荐的“真实文字度量 + 旋转包围盒 + 奇偶行错位 + SVG pattern”方案；T071 已完成规格更新，T072-T076 按 Test-First 实施。
- T072-T076 已完成：PDF 使用最终黑体的真实宽度计算旋转包围盒，强制 `320pt × 220pt` 最小步长并对长身份自动扩展，奇偶行错位 50%；两端预览使用等效 `427px × 293px` 最小单元、`0.11` 透明度和单个 SVG pattern，不再按正文高度创建 tile 或注册 `ResizeObserver`。后端 `57 passed`、两端目标测试/静态检查/构建、Poppler 普通/长身份 PDF 以及本地 Playwright SVG 正文裁剪目检均通过；T030 保持人工门禁。
- 2026-07-22 用户确认在无重叠方案上采用轻度增密档：PDF 最小单元调整为 `288pt × 200pt`，两端预览等效调整为 `384px × 267px`，普通 A4 目标约 8 至 10 组；T077 已完成规格更新，T078-T080 按 Test-First 实施。
- T078-T080 已完成：三端旧最小值均先建立红灯，再只调整 PDF/worker 和两端预览最小单元常量；后端 `57 passed`、BiSheng `2 passed`、Portal `4 passed`、静态检查、两端生产构建和差异审计通过。Poppler 普通 A4 样本为 10 个锚点，长身份自动扩展为 5 个锚点且无重叠；T030 保持人工门禁。
- 2026-07-22 用户目检下载 PDF 后仍认为分布偏稀疏，确认下载与 Portal/BiSheng 预览同步采用中等增密档：PDF 最小单元 `240pt × 180pt`、预览等效 `320px × 240px`、普通 A4 目标约 12 至 14 组；T081 已完成规格更新，T082-T084 按 Test-First 实施。
- T082-T084 已完成：三端轻度增密常量均先建立红灯，再只调整 PDF/worker 和两端预览最小单元；后端 `57 passed`、BiSheng `2 passed`、Portal `4 passed`、静态检查、两端生产构建和差异审计通过。Poppler 普通 A4 样本为 13 个锚点，长身份自动扩展为 5 个锚点且无重叠；T030 保持人工门禁。
- 2026-07-23 用户确认三端同步将普通水印最小步长和安全留白缩短约 25%，日期改为 `YYYY/MM/DD`，最终视觉方向统一为左下向右上 `/`；长身份保持字号并自适应扩距。T085 已完成规格对齐，T086-T088 按 Test-First 实施。
- T086-T088 已完成：三端旧日期、间距和 PDF 方向先建立红灯；PDF 使用 `+35°` 取得最终 `/` 方向，SVG 保持其坐标系下的 `-35°`，日期统一为 `YYYY/MM/DD`；PDF/预览最小步长和安全留白同步缩短约 25%，长身份继续自适应扩距。后端 `57 passed`、BiSheng `2 passed`、Portal `4 passed`，静态检查和两端构建通过；Poppler 普通 A4 为 13 个锚点，较长身份为 5 个锚点且无重叠，T030 保持人工门禁。
- 2026-07-23 用户确认不考虑性能，Portal 与 BiSheng 预览采用视觉效果优先的全尺寸 SVG 逐坐标方案。根因为 pattern 内第二行横向偏移半格后越过 tile 边界并被周期性裁剪；T089 已完成规格更新，T090-T092 按 Test-First 实施。
- T090-T092 已完成：两端先以缺少 surface 坐标生成函数建立红灯，再通过 `ResizeObserver` 获取正文尺寸，在一个全尺寸 SVG 内按行列坐标绘制独立两行 `<g>/<text>`，彻底移除 `<pattern>/<rect>` 内部裁剪边界。Portal 目标 Node test `4 passed`、ESLint 与 `2234 modules transformed` 构建通过；BiSheng 目标 Jest `2 passed`、import check 与 `6087 modules transformed` 构建通过。本地浏览器普通身份 1500×720 为 15 组、长身份 1500×500 为 5 组，均无 pattern 且每组两行完整，只有真实正文外边缘允许裁剪；T030 保持发布环境人工门禁。
- 2026-07-23 用户确认把水印扩展到 Portal 与 BiSheng 全部登录态问答正文，包括智能问答/写作、智能应用、Agent、workflow/assistant、知识空间、单文档及订阅文章/频道；匿名访客、公开/只读分享和非聊天专家问答排除。水印固定覆盖可见正文，排除 header/sidebar/composer/dialog/citation；workflow iframe 由 BiSheng 子页负责，第三方 URL iframe 由 Portal 宿主覆盖；T093 已完成规格更新，T094-T098 按 Test-First 实施。
