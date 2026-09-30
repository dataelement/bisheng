# Verification — F062 门户课程管理与播放进度

| 属性 | 值 |
|------|----|
| Feature ID | F062 |
| 验证日期 | 2026-07-19 |
| 结论 | 功能代码、P1 Review、上传错误反馈、课程播放体验增强、目录选中态/信息卡及上传媒体兼容性回归修复均已完成定向自动化；用户提供的 QuickTime/H.264/AAC 样本已通过真实探测，播放器 UI 已完成本地浏览器验证，真实 MySQL/DM8、MinIO 与部署环境端到端验收仍待执行 |

## 1. 已交付范围

- BiSheng 新增独立课程领域模块、4 张租户表、Alembic migration、25001～25009 错误码、媒体探测与持久 MinIO 上传、签名播放地址、进度终态覆盖行、媒体清理 outbox/Celery worker。
- 门户 BFF 新增公开、管理和进度 API；公开读使用服务身份，管理与进度使用当前登录会话；multipart 使用独立长超时并保持流式转发。
- 门户前端新增全部课程页、真实课程详情、自定义真实视频播放器、单/多视频自适应目录、登录进度上报，以及位于“首页 Banner”之后的独立“课程管理”页面。
- 课程详情已恢复旧版播放器与目录视觉：目录支持已学完、正在播放、已暂停、学习中和未播放五态；登录用户显示“已学 X · 未学 Y”，访客显示登录后记录进度提示。
- 目录选中态已与学习/播放状态解耦，任意选中项均有蓝色背景、编号和标题，同时保留状态文案语义颜色；课程信息卡恢复标签、四栏统计、更新日期和分段描述，继续不展示副标题。
- 首页改为读取 `placement=home` 的全部已启用首页课程，不再固定 5 条；访客可直接查看和播放。
- 删除课程 mock 数据源；门户 Nginx `/api/` 已支持 1 GiB 文件加 multipart 开销。
- P1 Review 修复已同步收紧 BiSheng/门户 BFF 部分更新契约，并使数据库提交后的清理任务即时投递在 broker/IO 故障时依赖持久化恢复扫描，不再把已成功的管理操作返回为失败。
- 上传文件或替换上传失败时，后端 `status_message` 现在会在当前上传区或替换弹窗内就近展示，不再只出现在可能滚出视口或被弹窗遮挡的面板顶部。
- 上传媒体校验已采用兼容性宽松矩阵：MP4 与 QuickTime ISO-BMFF 支持 H.264 + AAC/MP3，放宽 major brand 误拒绝并忽略字幕、时间码、data/attachment 和 `attached_pic` 等辅助轨；3GP/3G2、多个主视频轨和 HEVC/ProRes/MPEG-4 Visual 等未确认编码仍以具体安全的 `25005` 拒绝。

## 2. 自动化验证证据

### 2.1 BiSheng

| 命令 | 结果 |
|------|------|
| `.venv/bin/pytest -q test/shougang_portal_course` | 通过：`67 passed`；包含 disposable SQLite migration upgrade/downgrade、媒体边界/codec、宽松 MP4/QuickTime/辅助轨/动态 `25005`、发布约束、进度终态与并发首写重试、清理租约/退避、P1 回归和路由契约 |
| `.venv/bin/ruff check bisheng/shougang_portal_course bisheng/worker/portal_course bisheng/common/errcode/portal_course.py bisheng/core/database/alembic/versions/v2_6_0_f062_add_portal_course_tables.py test/shougang_portal_course` | 通过：`All checks passed!` |
| `.venv/bin/python -m compileall -q ...` | 通过，退出码 0 |
| `.venv/bin/alembic heads` | 通过：唯一 head 为 `f062_add_portal_course_tables` |
| `pytest` F062 + tenant/MinIO/Celery 相关回归 | `60 passed, 1 failed`；唯一失败是既有 `test_tenant_bypass_filter_guard.py` 白名单仍指向 `permission_service.py:997`，实际调用点已漂移到 `:1214`，与 F062 文件无关 |
| `git diff --check` | 通过，未发现空白符错误 |

### 2.2 门户 BFF 与部署契约

| 命令 | 结果 |
|------|------|
| `.venv/bin/pytest -q tests/test_course_deployment_contract.py tests/test_course_bff.py` | 通过：`18 passed, 1 warning`；覆盖独立上传超时、不可回放流拒绝、敏感字段过滤/签名 URL 同源化、身份字段拒绝、部分更新显式空值拒绝、公开服务身份和 Nginx 大文件配置 |
| `.venv/bin/pytest -q --tb=no` | 基线结果：`361 passed, 13 failed, 5 warnings`；13 个失败均位于既有 admin config、knowledge API 与 favorite 测试，F062 定向测试全部通过 |
| `python -m compileall`（课程 BFF 文件） | 通过，退出码 0 |
| `git diff --check` | 通过，未发现空白符错误 |

门户全量失败明细分类：

- `tests/test_admin_config_api.py`：3 个既有配置状态/默认 Banner 测试失败；
- `tests/test_knowledge_api.py`：6 个既有统计与会话代理测试失败；
- `tests/test_knowledge_service_favorite.py`：4 个异步测试因当前环境缺少有效 `pytest-asyncio` 支持而失败，同时出现未知 `asyncio_mode` 警告。

### 2.3 P1 Review 回归修复

| 阶段 | 命令 / 范围 | 结果 |
|------|-------------|------|
| RED | BiSheng `CourseUpdate`/`VideoUpdate` 12 个字段参数化测试 | 预期失败：`12 failed`；证明显式 `null` 原本会通过 schema |
| RED | BiSheng 清理投递与领域时长防御测试 | 预期结果：broker 降级和空时长防御 `2 failed`，未知 `RuntimeError` 传播 `1 passed` |
| RED | 门户 BFF `CourseUpdate`/`VideoUpdate` 12 个字段参数化测试 | 预期失败：`12 failed, 1 warning` |
| GREEN | BiSheng P1 定向回归 | 通过：`16 passed`；覆盖 `KombuError`、直接 `OSError` 与未知异常传播 |
| GREEN | 门户 BFF P1 定向回归 | 通过：`12 passed, 1 warning` |
| 模块回归 | BiSheng F062 / 门户 BFF 课程测试 | 通过：`53 passed` / `18 passed, 1 warning` |
| 静态检查 | BiSheng 变更文件 Ruff + 两端 `compileall` | 通过；门户后端 `.venv` 未安装 Ruff，未伪造该项结论 |

修复结论：BF-062-01 与 BF-062-02 均已由失败测试复现并转为通过。部分更新仍允许省略任意字段，但显式 `null` 在两层 schema 边界被拒绝；服务层不再把空外链时长转换为 `0`。清理即时投递仅捕获 `KombuError/OSError`，记录 tenant、job IDs 和异常类型后依赖已有持久化扫描重试，未知编程错误仍传播。

### 2.4 门户前端

| 命令 | 结果 |
|------|------|
| 定向编译后执行 `course.test.ts`、`courseUiWiring.test.ts`、`videoProgress.test.ts`、`coursePlayback.test.ts` | 通过：`21 passed` |
| ESLint 定向检查 F062 新增/改动核心 TS/TSX 和测试文件 | 通过，退出码 0 |
| `npm run build` | 通过：TypeScript build 与 Vite production build 完成 |
| `tsc -p tsconfig.tests.json --noEmit` | 基线失败：旧 `adminQaTemplates.test.ts` 缺少新增字段，旧 `portalContentConfig.test.ts` 仍导入已移除的 `fetchHomeContent`；F062 定向编译通过 |
| `npm run lint` | 基线失败：13 errors / 6 warnings，均位于既有非 F062 文件；F062 定向 ESLint 通过 |

构建告警：当前 Node.js 为 `20.13.1`，Vite 8 建议至少 `20.19` 或 `22.12`；本次构建仍成功。现有 bundle 同时有大 chunk 告警，本 Feature 未扩大范围处理全站拆包。

### 2.5 BF-062-03 上传错误反馈修复

| 阶段 | 命令 / 范围 | 结果 |
|------|-------------|------|
| RED | 定向编译后执行 `course.test.ts`、`courseUiWiring.test.ts` | 预期失败：`11 passed, 1 failed`；`25005` 文案解析测试通过，就近提示 wiring 测试因缺少 `uploadError` 状态失败 |
| GREEN | `node --test .test-dist/tests/course.test.js .test-dist/tests/courseUiWiring.test.js` | 通过：`12 passed`；覆盖 `25005` 安全业务文案/错误码、普通上传区和替换弹窗内两个 `role="alert"` 提示 |
| 定向静态检查 | `eslint src/pages/admin/CourseManagementPanel.tsx tests/course.test.ts tests/courseUiWiring.test.ts` | 通过，退出码 0 |
| 生产构建 | `npm run build` | 通过：TypeScript build 与 Vite production build 完成；保留既有 Node 版本与大 chunk 告警 |
| 全量测试编译 | `tsc -p tsconfig.tests.json` | 基线失败：既有 `adminQaTemplates.test.ts` 缺少 `home_icon/homeIcon/description`，既有 `portalContentConfig.test.ts` 导入已移除的 `fetchHomeContent`；与 BF-062-03 无关 |
| 全量 ESLint | `npm run lint` | 基线失败：`13 errors, 6 warnings`，均位于本次未修改的既有文件；本次变更文件定向检查通过 |

修复结论：BF-062-03 的根因是错误展示位置，不是 API 错误解析。上传 API 原本已保留 `status_message`；本次新增独立上传错误状态，并分别在普通上传区域和替换弹窗内展示，仍不暴露 `data.exception`，未修改 BFF、后端错误码或上传协议。

### 2.6 BF-062-04 课程目录与真实自定义播放器增强

| 阶段 | 命令 / 范围 | 结果 |
|------|-------------|------|
| RED | 定向编译 `coursePlayback.test.ts` 与 `courseUiWiring.test.ts` | 预期失败：播放状态纯函数模块不存在；已有 UI wiring 中独立播放器文件和目录状态接线断言失败 |
| 浏览器发现项 RED/GREEN | `courseUiWiring.test.ts` 全屏能力降级断言 | 先复现 `6 passed, 1 failed`，证明无 Fullscreen API 时会静默无反应；增加能力检测与可见提示后 `7 passed` |
| GREEN | 定向编译后执行课程 DTO、播放进度、播放状态与 UI wiring 共 4 个测试文件 | 通过：`21 passed`；覆盖五态、完成重播优先级、已学/未学统计、控制边界和媒体事件接线 |
| 定向静态检查 | `eslint src/components/course/CourseVideoPlayer.tsx src/pages/CoursePage.tsx src/utils/coursePlayback.ts tests/coursePlayback.test.ts tests/courseUiWiring.test.ts` | 通过，退出码 0 |
| 生产构建 | `npm run build` | 通过：TypeScript build 与 Vite production build 完成；保留既有 Node 版本与大 chunk 告警 |
| 全量测试编译 | `tsc -p tsconfig.tests.json --noEmit` | 基线失败：既有 `adminQaTemplates.test.ts` 缺少 `home_icon/homeIcon/description`，既有 `portalContentConfig.test.ts` 导入已移除的 `fetchHomeContent`；本次 4 个定向测试文件编译通过 |
| 全量 ESLint | `npm run lint` | 基线失败：`13 errors, 6 warnings`，均位于本次未修改的既有文件；本次变更文件定向检查通过 |
| 范围与空白符 | 两仓 `git status --short`、`git diff --check` | 通过：本轮生产改动仅位于门户课程详情前端；BiSheng 后端、BFF、数据表、配置和上传链路无本轮改动；用户原有 dirty 文件保持不变 |

本地浏览器验收使用服务身份/进度接口模拟与支持 Range 的 WebM 媒体完成，结果如下：

- 登录多视频课程首屏同时显示“已学 1 · 未学 2”，并正确呈现已学完、学习中和未播放；播放与暂停由真实媒体事件切换为“正在播放”和“已暂停”。
- 视频自然结束后目录恢复“已学完”，统计更新为“已学 2 · 未学 1”；已完成视频重播时可临时显示播放/暂停，切换视频后恢复已学完且统计不变。
- 自定义控制实测播放/暂停、前后 10 秒边界、倍速切换、静音/取消静音、进度显示及进入/退出全屏；真实 `<video>` 未设置原生 `controls`，浏览器控制台无 error/warn。
- 访客单视频课程隐藏目录，播放器区域明确显示“登录后可记录学习进度”；`390×844` 窄屏下播放器控制栏可换行使用。
- 自动化浏览器已实际进入播放器全屏并恢复；对不支持 Fullscreen API 的浏览器同时提供明确可见错误提示。

增强结论：本轮只替换课程详情的播放器表现层并增加状态推导纯函数，复用原有 `useVideoProgress` 的 10 秒上报、暂停/离页/完成逻辑；未创建第二套上报器，也未修改任何课程 API 或存储结构。

### 2.7 BF-062-05 目录选中态与信息卡样式回归

| 阶段 | 命令 / 范围 | 结果 |
|------|-------------|------|
| RED：日期 | 定向编译 `course.test.ts`、`courseUiWiring.test.ts` | 预期失败：TypeScript `TS2724`，`formatCourseDate` 尚未导出 |
| RED：UI wiring | 单独编译并执行 `courseUiWiring.test.ts` | 预期失败：`7 passed, 2 failed`；缺少 `aria-current` 独立样式和旧版四栏信息卡结构 |
| GREEN | 定向编译后执行 `course.test.ts`、`coursePlayback.test.ts`、`courseUiWiring.test.ts`、`videoProgress.test.ts` | 通过：`24 passed`；覆盖日期回退、目录五态/选中态、信息卡 wiring、播放器和 10 秒进度上报回归 |
| 定向静态检查 | `eslint src/pages/CoursePage.tsx src/types/course.ts tests/course.test.ts tests/courseUiWiring.test.ts` | 通过，退出码 0 |
| 生产构建 | `npm run build` | 通过：TypeScript build 与 Vite production build 完成；保留既有 Node 版本与大 chunk 告警 |
| 全量测试编译 | `tsc -p tsconfig.tests.json --noEmit` | 基线失败：既有 `adminQaTemplates.test.ts` 缺少 `home_icon/homeIcon/description`，既有 `portalContentConfig.test.ts` 导入已移除的 `fetchHomeContent`；本次定向编译通过 |
| 全量 ESLint | `npm run lint` | 基线失败：`13 errors, 6 warnings`，均位于本次未修改的既有文件；本次变更文件定向检查通过 |
| 空白符 | 门户 `git diff --check` | 通过，未发现空白符错误 |

本地浏览器使用登录用户、三种学习状态和支持 Range 的 WebM mock 完成验收：

- 已完成项选中后行背景为蓝色浅底、编号为蓝底白字、标题为蓝色 `font-weight: 600`，状态文案仍为绿色；学习中和未播放项选中后同样保持蓝色选中外观，状态文案分别保持黄色和灰色。切换后 `data-state` 分别仍为 `completed/learning/unplayed`，未伪造播放状态。
- 点击真实播放器后目录状态进入“正在播放”，暂停后进入“已暂停”，证明本次 CSS 变更未破坏媒体事件状态机。
- 桌面信息卡显示 domain 蓝、level 黄、gray 中性标签，以及课程时长、主讲、所属单位、更新日期 `2026-04-12` 和两段描述；页面未出现副标题。
- `390×844` 下四栏按两列排列，每栏宽度一致，描述正常换行；课程 `main` 的 `scrollWidth` 与 `clientWidth` 均为 `375`，没有课程内容横向溢出。全站既有 Header 在该宽度仍超过视口并产生页面级横向滚动，定位到 Header 导航/用户区，未在本次 F062 范围内修改。
- 单视频课程隐藏目录，但继续显示相同四栏信息卡和更新日期；多视频课程显示目录与同一信息卡。浏览器控制台 `error/warn` 为空。

修复结论：BF-062-05 只修改门户课程详情页面、课程日期纯函数和相关测试。`aria-current` 负责选择维度，`data-state` 继续负责学习/播放语义；未修改课程 DTO、BFF、BiSheng、数据库、上传链路、播放器状态机或进度上报逻辑。

### 2.8 BF-062-06 上传媒体兼容性宽松修复

| 阶段 | 命令 / 范围 | 结果 |
|------|-------------|------|
| RED：BiSheng media | `.venv/bin/pytest -q test/shougang_portal_course/test_media_service.py` | 预期失败：`12 failed, 15 passed`；分别复现非旧白名单 MP4 brand、H.264 + MP3、辅助轨误拒绝和 `25005` 文案过于泛化 |
| RED 基线：跨层契约 | 门户 BFF `test_course_bff.py`；前端定向编译并执行 `course.test.ts`、`courseUiWiring.test.ts` | 通过：`18 passed, 1 warning` / `16 passed`；证明 BFF 已透传动态 `status_message`，前端已忽略 `data.exception` 并在两个上传区域就近展示，无需修改门户生产代码 |
| GREEN：BiSheng media | `.venv/bin/pytest -q test/shougang_portal_course/test_media_service.py` | 通过：`28 passed`；覆盖宽松 brand、AAC/MP3、WebM、辅助轨/封面、MOV/3GP/3G2、伪容器、无/多个主视频轨、HEVC/ProRes/MPEG-4 Visual、非法音频和安全具体文案 |
| BiSheng 模块回归 | `.venv/bin/pytest -q test/shougang_portal_course` | 通过：`65 passed` |
| BiSheng 静态检查 | `.venv/bin/ruff check ...media_service.py ...test_media_service.py`；定向 `compileall` | 通过：`All checks passed!`，编译退出码 0 |
| 门户 BFF 回归 | `.venv/bin/pytest -q tests/test_course_bff.py`；定向 `compileall` | 通过：`18 passed, 1 warning`；警告为既有 Python 3.14 环境无法识别 `asyncio_mode` 配置 |
| 门户前端回归 | 定向编译后执行课程 DTO、播放器、UI wiring、进度测试；`eslint tests/course.test.ts` | 通过：`24 passed`，ESLint 退出码 0 |
| 生产构建 | `npm run build` | 通过；保留既有 Node `20.13.1` 低于 Vite 建议版本和大 chunk 告警 |
| 真实媒体冒烟 | 临时目录中用 FFmpeg 8.0 生成 1 秒 H.264 + MP3 MP4，再由真实 `PortalCourseMediaService.probe()`/`ffprobe` 探测 | 通过：`{"extension": "mp4", "content_type": "video/mp4", "duration_seconds": 1}`；媒体随后从临时目录移除，未写入仓库或 MinIO |
| 范围与空白符 | 两仓 `git status --short`、`git diff --check`；F062 spec 尾随空白扫描 | 通过；本轮生产代码仅修改 BiSheng `media_service.py`，门户只修改 BFF/前端测试，用户既有 dirty 文件保持不变 |

BF-062-06 当时结论：`ftyp` 仍是 MP4 候选的文件签名门槛，但不再要求 major brand 命中有限白名单；当时仍明确拒绝 QuickTime/3GP/3G2。媒体流按唯一主视频、音频和可忽略辅助轨分类，MP4 音频扩展为 AAC/MP3，WebM 矩阵不变。QuickTime 边界随后由 BF-062-07 再次放宽。

### 2.9 BF-062-07 QuickTime/H.264 兼容性再次放宽

| 阶段 | 命令 / 范围 | 结果 |
|------|-------------|------|
| 样本调查 | `file`、文件头十六进制与真实 `ffprobe` 探测 `/Users/wenruli/Desktop/downloadVideo_8.mp4` | 文件签名为 `ftypqt  `、`major_brand=qt  `，唯一主视频为 H.264 High/yuv420p，音频为 AAC-LC，时长 `15.996680` 秒；旧校验返回 `25005 检测到 MOV 容器` |
| RED：BiSheng media | `.venv/bin/pytest -q test/shougang_portal_course/test_media_service.py` | 预期失败：`4 failed, 26 passed`；兼容 QuickTime AAC/MP3 被提前拒绝，不兼容 QuickTime HEVC/FLAC 也无法进入具体 codec 错误分支 |
| GREEN：BiSheng media | 同一命令 | 通过：`30 passed`；QuickTime H.264 + AAC/MP3 允许，QuickTime HEVC/FLAC、3GP/3G2、伪容器及其他既有非法组合仍拒绝 |
| 用户真实样本 | 真实 `PortalCourseMediaService.probe()` 只读探测 `downloadVideo_8.mp4` | 通过：`{"extension": "mp4", "content_type": "video/mp4", "duration_seconds": 16}`；未修改样本、未写入 MinIO |
| BiSheng 模块回归 | `.venv/bin/pytest -q test/shougang_portal_course` | 通过：`67 passed` |
| 静态检查 | 定向 Ruff 与 `compileall` | 通过：`All checks passed!`，编译退出码 0 |
| 范围与空白符 | `git diff --check`、`git status --short` | 通过；生产代码仅修改 `media_service.py`，新增对应 media 测试和 F062 文档；用户已有 portal config、Celery schedule 与脚本改动保持不变 |

修复结论：`qt  ` 不再在文件头阶段被无条件拒绝，而是作为 ISO-BMFF/MP4 候选进入原有唯一主视频轨、H.264 与 AAC/MP3 校验。通过后继续保存为 `.mp4`/`video/mp4`，不转码、不重新封装。3GP/3G2 与所有不兼容轨道组合保持原拒绝行为，上传 API、BFF、前端、数据库、MinIO 路径和播放进度均未修改。

## 3. 安全与边界核对

- 管理接口在门户 `require_admin_session` 与 BiSheng `get_admin_user` 双层鉴权；进度中的租户和用户仅从认证上下文读取，schema 拒绝伪造身份字段。
- 课程、视频、进度和清理表均包含非空 `tenant_id`；repository 的业务查询和写入均携带租户条件，清理扫描只在领取引用时跨租户，并逐任务恢复租户上下文。
- 外链只接受不含 credentials 的绝对 HTTP(S) URL，服务端不主动访问远端；浏览器提交前执行 `<video>` metadata 预检。
- 上传按流计数并在超过 1 GiB 时于 MinIO 写入前终止；实际容器与主播放 codec 由文件头和无 shell 的 `ffprobe` 双重校验，字幕/data/attachment/封面等辅助轨只被忽略而不会绕过主轨校验。
- 对外 DTO 删除 `object_name`、access/secret/token 等字段；存储和探测异常映射为稳定 250xx，日志只记录资源 ID、尝试次数和异常类型，不记录 token、签名 URL 或本地临时路径。
- 课程与视频部分更新区分“字段省略”和“显式 `null`”，避免把空值写入非空领域字段或破坏已发布课程的正时长约束。
- 数据库提交后的即时清理投递只降级明确的 broker/IO 异常；持久化 cleanup job 仍由全局扫描恢复，其他异常不会被静默吞掉。

## 4. 尚未验证项

以下项目需要可用的部署环境或破坏性测试授权，本次未伪造通过结论：

1. 真实 MySQL 与 DM8 上执行 migration upgrade/downgrade；当前仅完成 MySQL/通用 SQLAlchemy DDL 编译及 disposable SQLite 实际升降级。`downgrade` 会永久删除 F062 四张表，只能在一次性数据库或完成备份后执行。
2. 真实 BiSheng MinIO 上传 MP4/QuickTime/WebM、浏览器 Range 播放、签名地址反向代理、1 GiB 边界文件和 1 GiB + 1 byte 拒绝；自动化已用小型流式夹具覆盖相同控制分支，并以用户真实 QuickTime/H.264/AAC 样本验证探测通过，但未写入真实 MinIO。
3. 真实 Celery broker/worker/beat 下的删除、替换、失败重试和最终对象清理；自动化已覆盖引用复核、租约领取和封顶指数退避。
4. 部署环境浏览器端到端：真实 MinIO 签名地址 Range 播放（含本轮 QuickTime 样本）、10 秒上报网络请求、倒退覆盖后刷新续播、系统全屏、首页超过 5 条、后台上传取消与二次确认，以及动态 `25005` 在普通上传区/替换弹窗内的视觉验收。本地浏览器已覆盖访客/登录、单/多视频、目录五态、统计、播放/暂停/完成与窄屏布局；用户已确认本轮样本可由其浏览器直接播放，但尚未验证 MinIO/Nginx 响应链路和其他浏览器/操作系统组合。
5. 双租户真实数据库查询核对，以及删除课程/视频后进度行与 MinIO 对象的最终一致性查询。

## 5. 建议发布与回滚顺序

1. 在预发布 MySQL/DM8 备份后执行 F062 migration，并核对 4 张表、唯一约束和索引。
2. 发布 BiSheng API 与 Celery worker/beat，确认 `ffprobe`、MinIO 和 `knowledge_celery` 队列可用。
3. 发布门户 BFF、Nginx 与前端，再由管理员创建草稿课程完成小文件冒烟。
4. 依次验证公开列表/详情、登录进度和删除清理，再开放正式课程。

应用回滚可先回退门户前端/BFF，再回退 BiSheng 服务。数据库 downgrade 具有数据破坏性：存在正式课程、进度或未完成清理任务时不得直接执行，应先导出数据并完成对象清理评估。
