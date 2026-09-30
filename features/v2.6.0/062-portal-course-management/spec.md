# F062：门户课程管理与播放进度

## 状态

- Status: `implemented / live verification pending`
- Date: `2026-07-18`
- Detailed requirements: [requirements.md](./requirements.md)
- Detailed design: [design.md](./design.md)
- Implementation tasks: [tasks.md](./tasks.md)
- Verification: [verification.md](./verification.md)

## 目标

把首钢知识门户首页“专业课程 · 岗位赋能”从前端静态 mock 和模拟播放器升级为可由管理员配置、真实播放、支持多视频目录及登录用户续播的正式功能。课程元数据、视频对象和学习进度以 BiSheng 为事实源，门户只负责管理与播放体验、会话校验和 API 编排。

## Release Contract

- Owner Feature：F062。
- 新增领域对象：`PortalCourse`、`PortalCourseVideo`、`PortalCourseVideoProgress`、`PortalCourseMediaCleanup`。课程标签是 `PortalCourse` 内的有序值对象，不是独立领域实体。
- 错误码模块：`250`（`portal_course`），不得与既有 100～240 模块前缀冲突。
- 依赖：F012 tenant resolver、F017 tenant shared storage、F019 admin tenant scope，以及现有首钢门户会话/BFF 基线。
- 不修改 v2.6.0 现有 INV-1～INV-6；F062 不走 ReBAC 过滤列表，因此 INV-6 cursor 契约不适用。

## 核心契约

1. 所有课程统一为目录模型，不存在额外课程类型字段；公开详情只有 1 个已启用视频时隐藏目录并直接播放，2 个及以上时显示有序目录。
2. 草稿课程可没有视频；启用课程必须至少有一个来源完整的已启用视频。停用课程公开按 404 处理，停用视频不进入公开目录。
3. 课程字段包含名称、标签、讲师、描述、所属单位、启用、首页展示和唯一排序值；明确不包含副标题。标签随课程整体保存，不提供独立标签库或查询接口。
4. 首页显示所有 `enabled && show_on_home` 课程且不固定截断；`/course` 显示全部已启用课程；二者共享 `sort_order ASC, created_at DESC, id ASC`。
5. 视频来源仅为 `upload` 或 `url`。上传文件进入 `bisheng` 持久化 MinIO；外链必须是浏览器可直接播放的绝对 HTTP(S) 媒体 URL。
6. 上传最大 1 GiB，仅接受实际编码为 MP4/H.264/AAC 或 WebM/VP8/VP9/Vorbis/Opus 的浏览器兼容文件；通过 `ffprobe` 校验和取时长，不按扩展名放行、不转码。
7. 课程总时长实时汇总已启用视频时长，不冗余存储。外链时长由管理员填写正整数秒。
8. 访客和登录用户都可浏览、播放；访客从 0 开始且不保存进度。没有真实课程数据时显示空状态，不迁移现有 5 条 mock。
9. 登录进度以 `(tenant_id, user_id, video_id)` 唯一一行覆盖：播放中每 10 秒及暂停/切换/隐藏/离开时上报；向后拖动允许覆盖成较小值。
10. `ended` 立即写完成；完成状态不可逆，服务端忽略后续上报。已完成视频重播从 0 开始、仍显示“已学完”且不再上报。
11. 删除视频/课程同步删除后代进度；停用和普通元数据修改保留进度。替换文件、修改 URL 或切换来源类型清除目标视频全部进度。
12. 新上传先登记 provisional 清理记录，再校验和持久化；数据库提交成功后才清理旧对象。清理 worker 删除前再次确认对象未被有效视频引用，失败持久化重试。
13. 管理 API 在门户和 BiSheng 双层校验管理员；进度身份只取登录上下文；所有表、唯一约束、查询和清理均受租户边界约束。
14. 关系模型和 Alembic migration 同时兼容 MySQL/DM8，不使用单方言 enum/UPSERT/部分索引；进度并发使用锁 + 唯一冲突重试。

## Acceptance Criteria 索引

以下标准的完整输入、行为、边界与验证方式以 [requirements.md](./requirements.md) 为准：

| Requirement | Acceptance Criteria | 结果摘要 |
|-------------|---------------------|----------|
| REQ-001 | AC-001-01～AC-001-06 | 课程、标签、视频 CRUD/启停/排序及破坏性确认 |
| REQ-002 | AC-002-01～AC-002-06 | 浏览器兼容格式、1 GiB、MinIO、URL 与派生时长 |
| REQ-003 | AC-003-01～AC-003-06 | 首页、全部课程、公开可见性、访客与空状态 |
| REQ-004 | AC-004-01～AC-004-04 | 真实播放器、统一目录和学习状态展示 |
| REQ-005 | AC-005-01～AC-005-07 | 唯一覆盖进度、10 秒事件、完成终态与访客边界 |
| REQ-006 | AC-006-01～AC-006-07 | 删除、替换、补偿和幂等媒体清理 |
| REQ-007 | AC-007-01～AC-007-06 | 双层鉴权、用户身份、租户隔离和输入安全 |
| REQ-008 | AC-008-01～AC-008-06 | 双数据库、大文件链路、错误、日志与发布回滚 |

## API 与数据摘要

- 门户公开：`GET /api/v1/courses`、`GET /api/v1/courses/{course_id}`；
- 门户学习：`GET /api/v1/courses/{course_id}/progress`、`PUT /api/v1/course-videos/{video_id}/progress`；
- 门户管理：`/api/v1/admin/courses`、课程视频 upload/url、来源替换、删除和批量排序资源；
- BiSheng：对应拆分为 `course-catalog`、`course-admin`、`course-learning` 三组路由；
- 新表：`portal_course`、`portal_course_video`、`portal_course_video_progress`、`portal_course_media_cleanup`；标签以有序 JSON 值对象保存于 `portal_course.tags_json`；
- 文件事实：MinIO `bisheng` bucket 内的 `portal-course/{tenant}/{course}/{video}/...` 对象；API 只返回签名播放地址，不公开对象名。

## 错误契约

F062 使用 250xx：

- `25001` 课程不存在；
- `25002` 视频不存在；
- `25003` 课程不可发布；
- `25004` 媒体超过 1 GiB；
- `25005` 媒体格式/编码不支持；
- `25006` 外链无效；
- `25007` 视频来源字段无效；
- `25008` 媒体探测失败；
- `25009` 来源替换失败。

## 交付边界

- BiSheng：DDD 模块、4 张表、Alembic、250xx、MinIO 媒体服务、进度服务和清理 worker；
- 门户 BFF：公开/管理/进度代理、会话身份路由、multipart 长超时和错误映射；
- 门户前端：首页/课程列表/详情播放器、后台课程管理和进度状态机；
- 部署：门户 Nginx `/api/` 大文件请求与超时配置；
- 删除所有课程 mock 引用后才删除 `frontend/src/data/courseMock.ts`；
- 不修改用户现有的无关 `docker-compose.yaml` 或 BiSheng `celerybeat-schedule.db` 工作区变更。

## 非目标

- 副标题、字幕、封面、分类树、搜索/筛选、附件、考试、证书、评论、转码、访客进度；
- 现有 mock 数据迁移；
- 逐课程 OpenFGA/ReBAC；
- 播放事件历史、学习时长防刷和外链媒体长期可用性保障。

## 验收摘要

- F062 定向自动化、Ruff、前端定向 ESLint 和 production build 已通过；
- disposable SQLite migration 已实际升降级，真实 MySQL/DM8 migration 仍待预发布环境验证；
- 门户 BFF/前端全量基线存在与 F062 无关的既有失败，课程定向用例均通过；
- 真实 MinIO/Celery 与浏览器人工端到端仍待部署环境执行；
- 具体命令、证据、限制和未验证项见 [verification.md](./verification.md)。

## Review Gate

本规格已完成需求/设计评审并获得实施确认；功能实现已落地，真实环境验收完成度与证据以 [verification.md](./verification.md) 为准。
