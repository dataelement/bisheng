# Tasks — F062 门户课程管理与播放进度

| 属性 | 值 |
|------|----|
| Feature ID | F062 |
| 状态 | Media Compatibility Fix Complete / Deployment E2E Pending |
| 执行模式 | 测试先行，小步提交，完成一项验证一项 |
| 关联规格 | [spec.md](./spec.md) |
| 关联设计 | [design.md](./design.md) |

## 执行约束

- 勾选仅表示已有代码与可观察验证证据；未勾选项是部分覆盖、全量基线失败或依赖真实 MySQL/DM8、MinIO、Celery、浏览器环境的待验收项，详见 [verification.md](./verification.md)。
- 本文件只有在 F062 规格评审并得到实施确认后才能执行。
- 每个任务必须先添加失败测试，再实现最小代码使其通过；不得把全部测试延后到收尾阶段。
- BiSheng 遵守 Router → Endpoint → Service → Repository → DB 分层；新模型必须加入 `tenant_filter.py` 强制导入列表。
- 所有 ORM、migration 和 repository 逻辑必须同时考虑 MySQL/DM8，禁止单方言 UPSERT、enum、部分索引或未封装 raw SQL。
- 门户课程数据不得写入现有聚合配置 JSON；不得修改用户已有的 `celerybeat-schedule.db` 和门户 `docker-compose.yaml` 工作区改动。
- 涉及 migration downgrade、真实课程删除和 MinIO 对象删除时，只能在一次性测试数据/测试 bucket 执行；生产执行需单独风险确认。
- 任一阶段出现无法安全恢复的失败，停止后续任务并按项目中断格式报告。

## 依赖关系

```text
T001 → T002 → T003 → T004
                 ├→ T005 → T006
                 ├→ T007 → T008
                 └→ T009 → T010
T004 + T006 + T008 → T011 → T012 → T013 → T014
T014 → T015 → T016 → T017
T017 → T018 → T019
T017 → T020 → T021
T019 + T021 → T022 → T023
T016 + T023 → T024 → T025
P1 review：T026 → T027
P1 upload feedback：T028 → T029
Playback enhancement：T030 → T031 → T032
UI regression fix：T033 → T034 → T035
Media compatibility fix：T036 → T037 → T038
```

T005/T007/T009 的测试设计彼此独立，可在无共享写冲突时并行；其实现都依赖 T002～T004 的模型/仓储基线。门户公开播放与管理 UI 可在 BFF 契约稳定后分别推进，最终在 T023 合并路由与 mock 移除。

## Phase 1：数据模型与仓储

### T001 — 先写 migration/model 契约测试

- [x] 在 `src/backend/test/shougang_portal_course/` 建立测试包，添加 4 张表、字段、索引、唯一进度键、默认值和 downgrade 顺序测试；断言不存在 `portal_course_tag`。
- [ ] 增加 MySQL 与 DM8 DDL 编译/可用测试，明确禁止数据库 enum、单方言默认值和隐式级联依赖。
- [x] 测试 `portal_course.tags_json` 使用 `LargeText`、非空并能保存有序标签 JSON，不依赖数据库原生 JSON 类型或函数。
- [x] 测试 `portal_course_video_progress` 的 `(tenant_id, user_id, video_id)` 唯一性，以及所有表均包含非空 `tenant_id`。
- 覆盖：AC-005-01、AC-007-04、AC-008-01；验证：V-004、V-006、V-007。
- 完成证据：新增测试在实现前因表/模型不存在而失败，记录失败摘要。

### T002 — 实现模型、Alembic 与租户注册

- [x] 新建 `bisheng/shougang_portal_course/domain/models/portal_course.py`，实现 `PortalCourse`、`PortalCourseVideo`、`PortalCourseVideoProgress`、`PortalCourseMediaCleanup`；`PortalCourse.tags_json` 使用 dialect helper `LargeText`。
- [x] 新建 `v2_6_0_f062_add_portal_course_tables.py`，按父子顺序 upgrade、逆序 downgrade；不写默认课程或 mock 迁移。
- [x] 将 model module 加入 `core/database/tenant_filter.py::_TENANT_AWARE_MODEL_MODULES`，验证 4 张表被自动发现。
- [ ] 运行 T001 测试，并在一次性 MySQL/DM8 环境验证 upgrade/downgrade；若真实 DM8 不可用，保留 DDL 编译证据并在 `verification.md` 标未验证。
- 覆盖：AC-001-01～04、AC-005-01、AC-007-04、AC-008-01、AC-008-06。
- 风险：downgrade 会永久删除 F062 全部数据；仅限 disposable DB。

### T003 — 先写 repository 行为测试

- [ ] 测试课程 admin/public 条件、稳定排序、标签 JSON 往返与数组顺序、视频排序和已启用视频总时长。
- [ ] 测试双租户同 ID/同排序数据不可互见，所有 update/delete/order 均受 tenant 限制。
- [ ] 测试显式删除顺序：视频进度 → 视频 → 课程；标签随课程行删除，停用和普通元数据更新不触碰进度。
- [ ] 测试进度 `SELECT FOR UPDATE`、insert/update 与唯一冲突重试路径，不能使用方言专属 upsert。
- 覆盖：AC-002-06、AC-003-01～04、AC-005-01、AC-006-01～03、AC-007-04；验证：V-003～V-006。

### T004 — 实现 repository 层

- [x] 实现 course/video repository 的管理查询、公开查询、稳定排序、批量 order 和显式后代删除；标签随 course 行保存，不建立 tag repository。
- [x] 实现 progress repository 的课程批量读取、行锁 upsert 支撑、按视频/课程删除。
- [x] 实现 cleanup repository 的 provisional 登记、取消、带租约到期领取、重试/完成和过期租约回收。
- [x] repository 不生成签名 URL、不决定管理员权限、不解析媒体，保持职责边界。
- [ ] 运行 T003 及租户过滤回归测试。
- 覆盖：AC-001-01～05、AC-002-06、AC-003-01～04、AC-005-01～02、AC-006-01～04、AC-007-04。

## Phase 2：媒体、清理与领域服务

### T005 — 先写媒体校验与上传失败测试

- [x] 用 mock `ffprobe` 覆盖合法 MP4/H.264/AAC、合法 WebM/VP8/VP9/Vorbis/Opus、无音轨合法视频。
- [ ] 覆盖伪扩展名、MOV/AVI/MKV、不支持视频/音频 codec、多条不支持媒体流、零/未知时长、探测超时、命令缺失和无效 JSON。
- [x] 覆盖大小 `1 GiB - 1`、`1 GiB`、`1 GiB + 1`，证明超限在 MinIO 写入前停止。
- [ ] 覆盖任意失败后的临时文件清理、日志脱敏和不产生有效视频记录。
- 覆盖：AC-002-01～04、AC-007-05、AC-008-04～05；验证：V-002、V-006、V-007。

### T006 — 实现媒体服务与持久化 MinIO 适配

- [x] 分块落盘并计数，不将 1 GiB 文件整体读入内存；临时路径使用安全随机名并在 `finally` 删除。
- [x] 以无 shell subprocess 执行 `ffprobe`，设置超时，严格解析 container/codec/duration，时长向上取整。
- [x] 生成 `portal-course/{tenant}/{course}/{video}/{uuid}.{ext}` 对象名，上传到 `bisheng` bucket，不使用 `tmp-dir`；按探测结果设置 `video/mp4` 或 `video/webm`，不信任客户端 MIME。
- [x] 读取时生成短期 presigned URL，并复用现有浏览器可达 asset URL 规则；公开 DTO 不暴露对象名。
- [x] 为上传流程提供 provisional cleanup hook，但不在媒体服务内提交课程事务。
- 覆盖：AC-002-01～04、AC-003-05、AC-006-05、AC-007-05、AC-008-05。

### T007 — 先写对象清理与补偿测试

- [ ] 测试 provisional 任务先提交、上传失败/DB 失败后到期清理，以及成功建视频时同事务取消。
- [ ] 测试替换/删除在 DB commit 前不删除旧对象，commit 后进入清理。
- [ ] 测试对象仍被引用时禁止删除、对象不存在视为成功、重复执行幂等。
- [ ] 测试 MinIO 临时错误使用封顶指数退避但持续自动重试；超过阈值输出脱敏告警，processing 租约过期后可被重新领取。
- [ ] 测试全局扫描只获取 `(job_id, tenant_id)`，逐条恢复 tenant context；不得在 bypass 状态删除对象或业务数据。
- 覆盖：AC-006-05～07、AC-007-04～05、AC-008-04；验证：V-005～V-007。

### T008 — 实现清理 outbox/service/worker

- [x] 实现 provisional、replace、delete 三类清理登记及引用复核。
- [x] 数据事务提交后即时投递指定 job；增加单个全局 Celery 恢复扫描任务处理漏投/重试，不按租户创建 beat 任务。
- [x] worker 对每条任务恢复 tenant context，MinIO 删除成功或 not-found 后标 done；临时失败更新 attempt/not_before。
- [x] 将 worker 路由/beat 配置接入现有 Celery 组织方式，并验证不会重复注册或修改本地 schedule 数据库文件。
- [ ] 运行 T007、worker 路由和 tenant context 回归测试。
- 覆盖：AC-006-05～07、AC-007-04、AC-008-04。

### T009 — 先写课程与外链领域服务测试

- [x] 测试草稿无视频可保存、无可播放视频不可启用、启用课程不可停用最后一个可播放视频。
- [ ] 测试标签 JSON 数组顺序、往返序列化、类型 `domain|level|gray` 和字段边界，证明不存在独立标签实体及 subtitle。
- [ ] 测试外链服务端仅接受绝对 HTTP(S)、无 credentials、长度合法；拒绝相对 URL、`javascript:` 和 `data:`，且证明服务端不会为校验主动访问远端。
- [ ] 测试普通元数据/排序不清进度，URL 修改/source 切换清全部目标视频进度。
- [ ] 测试上传替换每一失败点：新文件失败保持旧来源/进度；提交成功后切换来源、清进度、登记旧对象。
- 覆盖：AC-001-01～06、AC-002-04～06、AC-006-02～05、AC-007-06；验证：V-001、V-002、V-005、V-006。

### T010 — 实现课程、外链与生命周期 service

- [x] 实现课程/视频 CRUD、课程内标签值对象校验与序列化、启停校验、批量顺序、总时长派生和公开读模型。
- [x] 实现 URL schema/service 双层校验，后端不请求远端 URL；外链 duration 为正整数。
- [x] 使用行锁保护发布、停用最后视频、来源替换和删除事务。
- [x] 将进度清理和 cleanup job 登记纳入同一数据库事务，MinIO 操作保持事务外。
- [ ] 对删除/替换输出资源 ID 和 request ID 日志，不记录完整本地路径、令牌或密钥。
- 覆盖：REQ-001、REQ-002、REQ-003、REQ-006、AC-007-05～06、AC-008-04。

### T011 — 先写播放进度 service 并发与终态测试

- [ ] 测试课程一次读取全部本人进度、缺失项为 0 且不预建记录。
- [ ] 测试 10 秒上报载荷的服务端取整/截断、前进覆盖、向后覆盖、视频/课程停用或跨租户 404。
- [x] 测试首次 completed 固化 `completed_at` 和 duration，后续任何上报原样返回，不改变更新时间/完成时间。
- [ ] 模拟两个首次上报并发，最终只有一行；模拟完成和普通进度竞争，完成终态获胜。
- [x] 测试身份只取认证上下文，body 即使含伪造 user/tenant 字段也被 schema 拒绝或忽略。
- 覆盖：AC-005-01～07、AC-007-03～04；验证：V-004、V-006。

### T012 — 实现播放进度 repository/service

- [x] 实现批量读取、合法范围截断、允许倒退覆盖、完成终态和唯一冲突重试。
- [x] 完成更新与普通更新均在当前租户行锁内执行；不使用 `MAX()` 或 MySQL UPSERT。
- [x] 公开课程/视频校验失败统一按不存在处理；访客无 service 调用入口。
- [x] 记录异常写入的结构化日志和资源标识，但不记录认证 token。
- 覆盖：REQ-005、AC-007-03～04、AC-008-04。

## Phase 3：BiSheng API

### T013 — 先写 API 鉴权与错误契约测试

- [x] 覆盖 Catalog 服务身份公开读、Admin `get_admin_user`、Learning `get_user` 三组依赖。
- [ ] 覆盖管理员 CRUD、upload/url 创建与替换、批量排序、进度读写及 tenant context 传递。
- [ ] 覆盖访客/普通用户写管理接口为 401/403，跨租户/停用资源为 404。
- [x] 断言 25001～25009 稳定映射，公开响应不含 `object_name`、内部凭据和管理员专属字段。
- [ ] multipart 测试证明服务端忽略客户端上传 duration，并正确传递文件流。
- 覆盖：AC-001-01～05、AC-002-03～05、AC-003-01～05、AC-005-07、REQ-007、AC-008-03；验证：V-001～V-007。

### T014 — 实现 schemas、错误码、endpoints 与 router

- [x] 新建 `common/errcode/portal_course.py` 并实现 25001～25009；检查全仓无前缀冲突。
- [x] 实现 admin/catalog/learning schemas 和 endpoints，统一 `resp_200`，身份只取依赖上下文。
- [x] 将 module router 接入 `bisheng/api/router.py`；保持 Endpoint 只做解析/依赖/响应映射。
- [x] 对创建、更新、批量排序、删除和上传使用设计约定路径，补齐 OpenAPI schema。
- [x] 运行 T013、全仓错误码唯一性和 API router import 测试。
- 覆盖：REQ-001～REQ-008（BiSheng API 部分）。

## Phase 4：门户 BFF

### T015 — 先写 `BishengClient` 大文件转发测试并实现

- [x] 先测试 multipart 单请求可设置独立 connect/write/read/pool timeout，其他请求继续使用默认 timeout。
- [x] 测试认证刷新后文件流可安全 rewind；不可 rewind 时返回明确错误，不发送截断文件。
- [x] 测试转发不调用 `await file.read()` 整体读取，并保留上游 250xx payload。
- [x] 最小修改 `backend/app/clients/bisheng.py`，为课程上传增加 per-request timeout 参数和必要的 delete 方法；不改变现有调用默认行为。
- 覆盖：AC-002-02、AC-008-02～03；验证：V-002、V-007、V-008。

### T016 — 先写门户课程 BFF API 测试

- [x] 公开 `/api/v1/courses` 与详情不要求 session，固定使用服务身份和门户 tenant；测试 home/all 参数校验。
- [ ] Admin routes 使用 `require_admin_session` 且下游为当前管理员 token client；访客/普通用户拒绝。
- [ ] Progress routes 要求登录，使用当前 session token，body 不含 user/tenant；切换用户不会复用旧 client 身份。
- [x] 测试签名 MinIO URL 转为浏览器可达同源路径且保留签名 query，外链 URL 不被错误重写。
- [ ] 测试 multipart 流、1 GiB 客户端 header 预检、250xx 中文错误映射和上游超时。
- 覆盖：AC-002-03、AC-003-01～05、AC-005-02、AC-005-07、AC-007-01～03、AC-008-02～04；验证：V-003、V-004、V-006～V-008。

### T017 — 实现门户 schemas、service 与 routes

- [x] 新建 `schemas/course.py`、`services/course_service.py`、公开/管理 routes，并注册到 `api/router.py`。
- [x] 公开读使用运行时服务 client，管理员和进度使用 `create_bisheng_client(session)`；不得让浏览器直接获得 BiSheng token。
- [x] 流式转发 multipart，保留业务错误码；输出 DTO 过滤对象名和敏感字段。
- [x] Progress PUT 同时支持普通 JSON 请求和离开页面 `fetch(..., { method: 'PUT', keepalive: true })` 小载荷。
- [ ] 运行门户 backend 全量 pytest，确认现有 auth/config/knowledge API 无回归。
- 覆盖：REQ-001～REQ-008（BFF 部分）。

## Phase 5：门户前端

### T018 — 先写课程 DTO、排序与管理校验测试

- [x] 新增 `types/course.ts` 及纯函数测试，覆盖 public/admin DTO 映射、总时长格式化、标签类型和稳定顺序。
- [x] 测试公开详情视图判定：1 个已启用视频为单视频模式并隐藏目录，2 个及以上为目录模式；判定不得依赖课程类型字段。
- [x] 测试 home 不固定 5 条、all 不筛首页字段、停用数据防御性过滤和空列表。
- [ ] 测试草稿/发布校验、外链 URL/duration、浏览器媒体预检状态、上传大小预检、来源替换影响提示。
- [x] 新增 `api/courses.ts`、`api/adminCourses.ts` 的请求构造测试，覆盖路径、method、multipart 和错误映射。
- 覆盖：AC-001-01～06、AC-002-02、AC-002-04～06、AC-003-01～06；验证：V-001～V-003。

### T019 — 实现公开列表、详情目录与真实播放器

- [x] 新建 `/course` 列表页，移除搜索/筛选/分类 UI；无数据显示空状态。
- [x] 将 `/course/:courseId` 映射到真实详情页：1 个已启用视频时隐藏目录并自动选择唯一视频，2 个及以上时显示目录并默认选择首个视频；两者共用同一 `videos[]` 数据结构。
- [x] 使用真实 `<video>` 与独立自定义控制实现播放、切换和错误状态，不保留模拟计时器或浏览器原生 `controls`；登录用户的单视频学习状态显示在播放器区域，多视频学习状态显示在目录项。
- [x] 首页课程区调用 `placement=home`，移除点击课程的访客登录拦截和固定条数截断。
- [x] 不提供 subtitle/cover 的新数据字段；缺少自定义封面时使用现有通用课程视觉资产。
- 覆盖：REQ-003、REQ-004、AC-005-02、AC-005-06；验证：V-003、V-004。

### T020 — 先写前端进度状态机测试

- [x] 使用可控时钟测试只有 playing 状态每 10 秒上报，pause 后停止 interval。
- [x] 测试 pause、视频切换、hidden、pagehide/unmount 的单次上报与 interval 清理，避免重复 handler。
- [ ] 测试未完成视频 loadedmetadata 后续播、向后拖动上报较小值、服务端 clamp 回写。
- [x] 测试 ended 立即完成并停止后续上报；completed 重播从 0 开始且不调用 PUT。
- [ ] 测试 guest 永不读写进度、session 用户变化清理旧状态。
- 覆盖：AC-005-02～07、AC-007-03；验证：V-004、V-006。

### T021 — 实现 `useVideoProgress` 与播放器接线

- [x] 课程加载后一次读取全部视频进度，以 `video_id` 建 map；登录失败不降级为伪造完成状态。
- [x] 实现 playing interval、pause/switch/visibility/pagehide/ended 事件；离开使用 PUT + `keepalive` 尽力发送。
- [x] completed 状态本地立即固化，服务端回包校准；组件/用户/视频变化时清理 timer 和 listener。
- [x] 将目录“已学秒数/已学完”和播放器续播接入 T019 组件。
- 覆盖：REQ-005、AC-004-04、AC-007-03。

### T022 — 实现独立课程管理面板

- [x] 新建 `CourseManagementPanel` 及样式，`AdminPage.tsx` 只负责入口和最小状态编排。
- [x] 实现课程基础字段、标签编辑、视频目录、upload/url 创建、来源替换、启停和排序。
- [x] 外链保存前通过浏览器 `<video>` 的 `loadedmetadata`/错误事件完成可播放预检；预检失败不得提交。
- [x] 对课程/视频删除和来源替换展示二次确认；替换明确提示清除该视频全部用户进度。
- [x] 展示上传进度、取消、格式/大小错误及 MinIO/探测错误；客户端预检不替代服务端结果。
- [x] 课程发布前展示至少一个可播放视频的校验提示，并正确呈现 25001～25009。
- 覆盖：REQ-001、REQ-002、REQ-006、AC-007-01、AC-008-03；验证：V-001、V-002、V-005～V-007。

### T023 — 路由整合、移除 mock 与前端回归

- [x] 更新 `App.tsx`，确保 `/course` 与 `/course/:courseId` 分别加载列表/详情。
- [x] 使用 `rg` 确认 `courseMock`、模拟播放 timer 和访客课程登录拦截均无引用后，删除 `frontend/src/data/courseMock.ts`。
- [ ] 运行 `npm test`、`npm run lint`、`npm run build`，修复本 Feature 引入的问题，不顺手重构无关页面。
- [ ] 验证现有首页布局在 0、1、5、超过 5 条课程时可用，并保持移动端/窄屏可访问。
- 覆盖：AC-003-01～06、REQ-004、AC-005-03～06；验证：V-003、V-004、V-008。
- 风险：删除 mock 后新后端无数据会显示空状态，这是已确认行为；删除前必须以引用搜索和 build 证明可逆替代路径已完成。

## Phase 6：部署与总验证

### T024 — 大文件代理配置与部署契约

- [x] 先添加/更新 Nginx 配置测试，断言门户 `/api/` 为 `client_max_body_size 1100m`、`proxy_request_buffering off`、`proxy_send_timeout 600s`、`proxy_read_timeout 600s`。
- [x] 只修改 `deploy/nginx/default.conf.template`；核对 BiSheng 前置代理对课程上传路径也允许 1 GiB + multipart 开销。
- [ ] 用小型流式夹具和可控超限流验证 BFF/代理行为；真实 1 GiB 文件测试作为可选慢速/手工项，不提交大文件到仓库。
- [x] 核对发布顺序、环境变量和 Celery worker/beat 注册；不改用户现有门户 `docker-compose.yaml` dirty 变更。
- 覆盖：AC-002-02、AC-008-02、AC-008-05～06；验证：V-002、V-007、V-008。

### T025 — 全链路验证与 `verification.md`

- [ ] BiSheng：运行 F062 定向 pytest、相关 tenant/MinIO/worker 回归、Ruff 和 Python 编译；在可用环境运行 MySQL/DM8 migration upgrade/downgrade。
- [ ] 门户 BFF：运行全量 pytest；前端运行 `npm test`、`npm run lint`、`npm run build`。
- [ ] 手工端到端：单视频隐藏目录并直接播放、多视频显示目录并可切换、访客播放、登录续播、倒退覆盖、完成后停止上报、首页顺序/不限条数、停用 404。
- [ ] 失败注入：不支持 codec、1 GiB+1、ffprobe 缺失、MinIO 删除失败、替换 DB 失败、清理重试；证明旧来源/进度和补偿语义。
- [ ] 检查数据库每用户/视频唯一一行、课程/视频删除后的进度、MinIO 对象最终清理和双租户不可见。
- [x] 创建 `verification.md`，逐项记录命令、退出码/摘要、环境、截图或查询证据、未验证项和原因；不得以代码阅读替代运行证据。
- 覆盖：REQ-001～REQ-008；验证：V-001～V-008。

## Phase 7：P1 Review 回归修复

### T026 — 建立 P1 回归测试与 RED 证据

_Requirements: REQ-001、REQ-002、REQ-006_

_Acceptance: AC-001-07、AC-002-04、AC-006-08_

_Verification: V-001、V-005_

_Boundary: 只增加 BiSheng 与门户 BFF 的参数校验、领域防御和 broker 投递失败测试；不处理 SDD Review 中的 P2。_

- [x] 参数化验证两端 `CourseUpdate`、`VideoUpdate` 对所有显式 `null` 字段返回校验错误，空 payload 仍合法。
- [x] 验证领域 Service 不会把构造出的空外链时长转换并持久化为 `0`。
- [x] 验证 `KombuError/OSError` 不影响提交后主流程，且日志包含 tenant/job/error type；未知编程异常仍传播。
- [x] 先运行新增测试并记录预期失败的 RED 证据。

### T027 — 实现最小 P1 修复并完成验证

_Requirements: REQ-001、REQ-002、REQ-006、REQ-008_

_Acceptance: AC-001-07、AC-002-04、AC-006-08、AC-008-04_

_Verification: V-001、V-005、V-007_

_Depends: T026_

_Boundary: 仅修改两端 course schema、BiSheng course service 和 admin 清理投递 helper；不新增 migration、不修改 worker 状态机、不处理 P2。_

- [x] 两端 update schema 拒绝显式空值，字段省略仍保持部分更新。
- [x] Service 移除空时长到 `0` 的转换，并保留领域防御。
- [x] 即时清理投递对明确 broker/IO 故障降级为带上下文日志，依赖持久化任务恢复。
- [x] 运行定向 pytest、F062 pytest、Ruff、compileall，并更新 `verification.md`。

## Phase 8：P1 上传错误反馈修复

### T028 — 建立上传错误反馈回归测试与 RED 证据

_Requirements: REQ-002、REQ-008_

_Acceptance: AC-002-07、AC-008-03_

_Verification: V-002、V-007_

_Boundary: 仅补充课程 API 错误解析与管理端上传区域 wiring 测试，不修改生产实现。_

- [x] 验证 `status_code=25005` 时保留上游安全业务文案与错误码，不展示内部异常字段。
- [x] 验证普通上传区与替换弹窗都存在就近的 `role="alert"` 错误提示。
- [x] 先运行新增测试并记录预期失败的 RED 证据。

### T029 — 实现上传错误就近展示并完成验证

_Requirements: REQ-002、REQ-008_

_Acceptance: AC-002-07、AC-008-03_

_Verification: V-002、V-008_

_Depends: T028_

_Boundary: 仅修改 `CourseManagementPanel`、对应样式与测试，不修改 BFF、后端错误码或上传协议。_

- [x] 增加独立上传错误状态，普通上传失败时在普通上传区内展示。
- [x] 替换上传失败时在替换弹窗内展示，并在新操作开始时清理陈旧提示。
- [x] 运行定向前端测试、ESLint 与生产构建，并更新 `verification.md`。

## Phase 9：课程目录与真实自定义播放器增强

### T030 — 建立目录五态与自定义播放器 RED 证据

_Requirements: REQ-004、REQ-005_

_Acceptance: AC-004-03～AC-004-06、AC-005-02～AC-005-06_

_Verification: V-003、V-004_

_Boundary: 只增加目录呈现纯函数、播放器控制纯函数和组件 wiring 测试；不修改生产实现，不恢复 mock 数据或模拟播放 timer。_

- [x] 覆盖登录/访客统计、完成/播放/暂停/学习中/未播放五态及完成视频重播优先级。
- [x] 覆盖前后 10 秒边界、倍速循环、进度百分比和时间格式等自定义控制纯函数。
- [x] 验证页面使用独立真实播放器组件、自定义控制和媒体事件转发，不保留原生 `controls`。
- [x] 运行新增测试并记录预期失败的 RED 证据。

### T031 — 实现真实自定义播放器与目录五态

_Requirements: REQ-004、REQ-005_

_Acceptance: AC-004-01～AC-004-06、AC-005-02～AC-005-06_

_Verification: V-003、V-004、V-008_

_Depends: T030_

_Boundary: 仅修改门户课程详情前端、课程播放纯函数、播放器组件及对应样式；不修改 BFF、BiSheng、数据库、上报频率、完成终态或单视频隐藏目录规则。_

- [x] 基于真实 `<video>` 实现播放/暂停、前后 10 秒、时间/缓冲/拖动、倍速、音量/静音和全屏控制，并提供可见失败反馈。
- [x] 保留现有续播和进度上报 hook，只转发原生媒体事件，不创建第二套上报器。
- [x] 实现目录五态、登录用户“已学 X · 未学 Y”、访客提示和完成视频重播视觉覆盖。
- [x] 恢复旧版播放器/目录视觉并完成桌面与窄屏响应式样式。

### T032 — 完成前端验证、浏览器验收与范围审计

_Requirements: REQ-004、REQ-005、REQ-008_

_Acceptance: AC-004-01～AC-004-06、AC-005-02～AC-005-07、AC-008-06_

_Verification: V-003、V-004、V-008_

_Depends: T031_

_Boundary: 只验证本次课程播放增强并记录基线失败；不得顺手修复非 F062 的 lint/test 问题，不触碰用户已有工作区改动。_

- [x] 运行定向前端测试、变更文件 ESLint、生产构建和 `git diff --check`。
- [x] 浏览器验收播放器控制、目录五态/统计、访客与登录状态、单/多视频响应式布局；环境不可用项必须如实记录。
- [x] 更新 `verification.md` 并审计无 BFF、后端、数据表、配置和上传链路改动。

## Phase 10：课程目录选中态与信息卡样式回归

### T033 — 建立选中态、日期回退与信息卡 wiring RED 证据

_Requirements: REQ-004_

_Acceptance: AC-004-07～AC-004-08_

_Verification: V-003、V-008_

_Boundary: 只增加日期纯函数和课程详情组件/CSS wiring 测试；不修改生产实现，不调整 API、播放器或进度上报。_

- [x] 覆盖 `updatedAt → createdAt → —` 的日期优先级、格式化和无效日期。
- [x] 覆盖 `aria-current` 独立选中样式、状态语义颜色、四栏字段、旧版信息卡类名和副标题持续缺失。
- [x] 运行新增测试并记录预期失败的 RED 证据。

### T034 — 实施目录独立选中态与旧版信息卡最小修复

_Requirements: REQ-004_

_Acceptance: AC-004-07～AC-004-08_

_Verification: V-003、V-008_

_Depends: T033_

_Boundary: 仅修改门户 `CoursePage`、课程类型纯函数和对应 CSS；不修改 BFF、BiSheng、DTO、播放器状态机或进度上报。_

- [x] 增加日期回退与格式化纯函数，不改变公开 DTO。
- [x] 以 `aria-current` 实现独立蓝色选中态，并保留 `data-state` 的状态语义颜色。
- [x] 恢复标签、标题、四栏统计、更新日期和描述信息卡，不恢复副标题。
- [x] 完成桌面四栏与 `720px` 以下两列响应式布局。

### T035 — 完成回归验证、浏览器验收与范围审计

_Requirements: REQ-004、REQ-008_

_Acceptance: AC-004-07～AC-004-08、AC-008-06_

_Verification: V-003、V-008_

_Depends: T034_

_Boundary: 只验证本次 UI 回归修复并记录既有基线失败；不得扩大到 BFF、后端、数据结构、上传链路或其他前端基线问题。_

- [x] 运行定向测试、变更文件 ESLint、生产构建和 `git diff --check`。
- [x] 浏览器验收已完成/学习中/未播放选中态、播放/暂停状态、单/多视频信息卡及桌面/窄屏布局。
- [x] 更新 `verification.md`，并审计无 BFF、BiSheng、数据库、上传链路和用户已有工作区改动。

## Phase 11：上传媒体兼容性宽松修复

### T036 — 建立媒体误拒绝与动态错误 RED 证据

_Requirements: REQ-002、REQ-008_

_Acceptance: AC-002-01、AC-002-07～AC-002-08、AC-008-03～AC-008-05_

_Verification: V-002、V-007、V-008_

_Boundary: 只更新 F062 规格并增加 BiSheng media、门户 BFF、前端错误解析/接线回归测试；本任务不修改生产代码。_

- [x] 覆盖非旧白名单 MP4 brand、H.264 + MP3、字幕/data/attachment/`attached_pic` 辅助轨均可通过。
- [x] 覆盖 MOV/3GP/3G2、伪容器、无/多个主视频轨、HEVC/ProRes/MPEG-4 Visual 和非法音频仍返回 `25005`。
- [x] 覆盖动态安全 `status_message` 经 BiSheng、门户 BFF 和前端解析后保持具体文案，并继续在普通上传区/替换弹窗内展示。
- [x] 运行新增测试并记录旧实现的预期 RED 失败证据：BiSheng media `12 failed, 15 passed`；门户 BFF `18 passed, 1 warning`、前端课程/接线 `16 passed`，证明跨层透传已有生产接线无需改动。

### T037 — 实施宽松媒体探测与安全错误文案

_Requirements: REQ-002、REQ-008_

_Acceptance: AC-002-01～AC-002-04、AC-002-07～AC-002-08、AC-008-03～AC-008-05_

_Verification: V-002、V-007_

_Depends: T036_

_Boundary: 仅修改 BiSheng `media_service.py`；保持 `25005`、上传 API、1 GiB 限制、临时文件/MinIO 生命周期、数据库、对象名和转码边界不变。_

- [x] 放宽 MP4 major brand 识别，同时明确拒绝 QuickTime MOV、3GP/3G2 与非 `ftyp` 伪容器。
- [x] 区分唯一主视频轨、音轨和可忽略辅助轨，MP4 音频允许 AAC/MP3，WebM 矩阵保持不变。
- [x] 为容器、主视频数量和不支持 codec 返回有限模板生成的安全具体 `25005` 文案。
- [x] 运行 T036 测试并取得 GREEN 证据：`test_media_service.py` 为 `28 passed`，变更文件 Ruff 为 `All checks passed!`。

### T038 — 完成跨层回归、真实探测冒烟与范围审计

_Requirements: REQ-002、REQ-008_

_Acceptance: AC-002-01～AC-002-08、AC-008-03～AC-008-06_

_Verification: V-002、V-007、V-008_

_Depends: T037_

_Boundary: 只验证媒体校验与错误透传；除非 RED 证明现有接线失效，否则不修改门户 BFF/前端生产代码，不修改配置、数据库、MinIO 数据或播放进度。_

- [x] 运行 BiSheng F062 测试、变更文件 Ruff/compileall、门户 BFF 课程测试、前端定向测试/ESLint/build 和 `git diff --check`。
- [x] 使用临时目录和真实 `ffmpeg/ffprobe` 生成小型 H.264 + MP3 MP4，验证真实探测通过且临时测试媒体不进入仓库。
- [x] 更新 `verification.md`，记录 RED/GREEN、基线失败、真实 MinIO/部署环境未验证项及用户工作区改动审计。

## Phase 12：QuickTime/H.264 兼容性再次放宽

### T039 — 建立 QuickTime 品牌误拒绝 RED 证据

_Requirements: REQ-002、REQ-008_

_Acceptance: AC-002-01～AC-002-02、AC-002-07～AC-002-08、AC-008-03～AC-008-05_

_Verification: V-002、V-007_

_Boundary: 只更新 F062 规格和 BiSheng media 回归测试；本任务不修改生产代码，不把用户桌面样本复制进仓库。_

- [x] 将 `ftypqt  ` + H.264 + AAC/MP3 纳入允许组合，并保留不兼容 codec、3GP/3G2 与伪容器拒绝断言。
- [x] 使用合成夹具运行定向测试并记录旧实现 RED：`4 failed, 26 passed`；使用用户真实样本只读复测相同 `25005`。

### T040 — 最小放宽 QuickTime 容器候选识别

_Requirements: REQ-002、REQ-008_

_Acceptance: AC-002-01～AC-002-04、AC-002-07～AC-002-08、AC-008-03～AC-008-05_

_Verification: V-002、V-007_

_Depends: T039_

_Boundary: 仅修改 BiSheng `media_service.py`；保持上传 API、`25005`、1 GiB 限制、MinIO 生命周期、对象名结构、数据库、BFF、前端和无转码/重新封装边界不变。_

- [x] `qt  ` 作为 ISO-BMFF/MP4 候选进入既有轨道与 codec 校验，通过后统一映射为 `.mp4`/`video/mp4`。
- [x] 保留 3GP/3G2、伪容器、非 H.264 主视频、非法音频和多主视频轨拒绝行为。
- [x] 运行媒体定向测试并取得 GREEN 证据：`30 passed`。

### T041 — 完成真实样本与模块回归验证

_Requirements: REQ-002、REQ-008_

_Acceptance: AC-002-01～AC-002-08、AC-008-03～AC-008-06_

_Verification: V-002、V-007、V-008_

_Depends: T040_

_Boundary: 只验证媒体校验和现有上传契约；不写入真实 MinIO，不修改用户样本、配置、数据库、BFF、前端或播放进度。_

- [x] 使用真实 `downloadVideo_8.mp4` 只读调用 `PortalCourseMediaService.probe()`，确认返回 `.mp4`、`video/mp4` 和 `16` 秒。
- [x] 运行 F062 后端回归、Ruff、定向编译和 `git diff --check`：`67 passed`、`All checks passed!`、编译与空白检查退出码 0；用户已有工作区改动保持不变。
- [x] 更新 `verification.md`，记录 RED/GREEN、真实样本证据、兼容性风险和未执行的真实 MinIO/部署浏览器验收。

## Acceptance Criteria → Task 映射

| AC | Tasks |
|----|-------|
| AC-001-01～AC-001-06 | T002、T003、T009、T010、T013、T014、T018、T022 |
| AC-001-07 | T026、T027 |
| AC-002-01 | T005、T006、T013、T015～T017、T024、T036～T041 |
| AC-002-02～AC-002-03 | T005、T006、T013、T015～T017、T024、T036～T041 |
| AC-002-04 | T005、T006、T009、T010、T018、T037～T041 |
| AC-002-05～AC-002-06 | T005、T006、T009、T010、T018、T038 |
| AC-002-07 | T028、T029、T036～T041 |
| AC-002-08 | T036～T041 |
| AC-003-01～AC-003-06 | T003、T004、T013、T016～T019、T023 |
| AC-004-01～AC-004-02 | T019、T021、T023、T031、T032 |
| AC-004-03～AC-004-06 | T019、T021、T023、T030～T032 |
| AC-004-07～AC-004-08 | T033～T035 |
| AC-005-01～AC-005-02 | T001～T004、T011、T012、T016、T019、T021 |
| AC-005-03～AC-005-07 | T011、T012、T016、T020、T021、T023、T030～T032 |
| AC-006-01～AC-006-04 | T003、T004、T009、T010、T022 |
| AC-006-05～AC-006-07 | T005～T010、T022、T025 |
| AC-006-08 | T026、T027 |
| AC-007-01～AC-007-03 | T011～T017、T020～T022 |
| AC-007-04～AC-007-06 | T001～T014、T016～T018 |
| AC-008-01 | T001、T002、T004、T012、T025 |
| AC-008-02 | T015、T016、T017、T024、T025 |
| AC-008-03～AC-008-05 | T005～T017、T022、T024、T025、T036～T041 |
| AC-008-06 | T002、T023～T025、T032、T035、T038、T041 |

## Definition of Done

- T001～T025 全部勾选且各自有测试先失败、实现后通过的可观察证据；
- `requirements.md` 的 AC-001-01～AC-008-06 无遗漏、无超范围实现；
- release contract、250xx、4 个领域对象、4 张表、migration 和 router 注册一致；
- 生产代码中不存在课程 mock 或模拟播放逻辑；
- 本次增量 T030～T032 全部勾选，并具有 RED、GREEN、静态检查、构建和浏览器/手工验收证据；
- 本次 UI 回归增量 T033～T035 全部勾选，并具有 RED、GREEN、静态检查、构建和浏览器验收证据；
- 本次媒体兼容性增量 T036～T038 全部勾选，并具有 RED、GREEN、动态错误跨层契约、真实 `ffprobe` 冒烟和范围审计证据；
- 本次 QuickTime 兼容性增量 T039～T041 全部勾选，并具有真实样本 RED/GREEN、编码边界回归、静态检查和范围审计证据；
- `verification.md` 如实区分已验证、受环境限制未验证和失败项；
- 已知风险、破坏性操作及真实环境执行授权均有记录。
