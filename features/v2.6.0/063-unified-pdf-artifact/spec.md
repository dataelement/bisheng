# Feature：知识文件统一 PDF 产物

**Feature ID**: `063-unified-pdf-artifact`

**Status**: Implemented / Deployment Verification Pending

**Mode**: Feature / Infrastructure Baseline

**Created**: 2026-07-20

**Updated**: 2026-07-21

**优先级**: P0

**所属版本**: v2.6.0

## 1. 概述与用户故事

作为后续水印下载链路，
我希望所有门户当前支持格式的新建或重新处理知识文件都有独立状态、可验证且来源可追踪的 PDF Artifact 引用，
以便后续下载加水印时只处理一种稳定输入，同时对合格的原始 PDF 和当前解析预览避免重复存储。

详细需求与设计见：

- [requirements.md](./requirements.md)
- [design.md](./design.md)
- [verification.md](./verification.md)

## 2. 当前问题

- 现有 Word/PPT PDF 由部分 Loader 在知识解析过程中尽力生成，覆盖路径不完整，但来源匹配且通过统一校验时可作为 Artifact 候选。
- Excel、文本、HTML、图片及分层 Word 没有统一 PDF 产物。
- `pdf_preview_object_name` 是可选预览元数据，没有独立状态、自动重试和版本一致性。
- `KnowledgeFile.status` 表示知识解析状态，不能承担 PDF 生成状态。
- 当前单文件和批量下载仍读取原始文件；在历史文件尚未补齐时不能直接切换 PDF 下载。

## 3. 目标

- 覆盖门户当前允许上传的 14 种扩展名。
- 每个范围内物理知识文件维护独立 PDF Artifact 状态和经过校验的当前对象引用。
- 合格原始 PDF 直接登记为 `ORIGINAL`；来源匹配且合格的当前解析预览登记为 `PARSE_PREVIEW`；其他情况回退生成 `GENERATED`。
- PDF 失败不改变知识解析、搜索、预览或下载结果。
- 有解析任务的上传、覆盖、重解析和 Web 链接重导入在解析尝试最终状态落库后触发；无解析任务的上传、复制和迁移在文件持久化后直接触发。
- 默认自动重试 3 次，耗尽后独立进入 `FAILED`。
- 使用 generation 防止旧任务覆盖新产物。
- 使用独立低并发 PDF Worker 隔离 LibreOffice/Chromium 资源消耗。
- 将 `txt/md/html` 统一规范化为受控 HTML，并通过 F063 专用、受限的 Playwright Chromium 渲染器生成 PDF。
- 将上传文件按不可信内容处理，限制脚本、宏、外链、子进程环境、网络和资源。

## 4. 非目标

- 不批量补齐历史文件。
- 不实现水印、加密、签章或下载切换。
- 不提供 PDF 状态 API、页面、专用人工重试或定时扫描。
- 不替换现有预览或 legacy PDF。
- 不扩展到 WPS/ET/DPS、BMP、音频和视频。
- 不修改门户前端、下载 API 契约或权限逻辑。

## 5. 核心验收摘要

| ID | 场景 | 预期结果 |
|---|---|---|
| AC-01 | 任一门户支持格式进入统一 PDF 处理 | 成功后保存有效、非加密、页数大于零且来源可追踪的 PDF 引用 |
| AC-02 | PDF 转换或上传失败 | 自动重试，最终仅 PDF Artifact 为 `FAILED`，知识解析状态不变 |
| AC-03 | 覆盖或重解析期间旧任务晚到 | generation 条件阻止旧状态和对象覆盖当前代次 |
| AC-04 | 文件复制或空间迁移 | 目标物理文件持久化后直接触发 PDF，不继承源文件的 Artifact 或预览引用 |
| AC-05 | 部署数据库迁移 | 只创建空表，不扫描或写入历史知识文件 |
| AC-06 | 用户执行现有预览和下载 | 返回路径、内容、响应结构和权限行为保持不变 |
| AC-07 | 渲染 HTML/Markdown | JavaScript、外部网络和非预期本地文件访问均被阻断 |
| AC-08 | 多租户并发处理 | Artifact、原文件和 PDF 对象不串租户 |
| AC-09 | 部署 PDF Worker | 使用独立服务与低并发，转换子进程不继承应用密钥并受网络/资源限制；本 Feature 不新增镜像用户 |
| AC-10 | 原始文件是合格 PDF | Artifact 直接引用当前原始对象并记录 `ORIGINAL` 与内容摘要，不复制相同字节 |
| AC-11 | 当前源存在解析 PDF 预览 | provenance 匹配且校验通过时直接引用为 `PARSE_PREVIEW`；缺失、过期或无效时从原始对象回退生成 |
| AC-12 | 有解析任务的文件解析结束 | 成功、失败、超时或违规状态与预览 provenance 落库后都投递 PDF 任务 |

稳定追踪 ID、完整验收标准和验证方法以 [requirements.md](./requirements.md) 为准。

## 6. 架构决策摘要

| ID | 决策 | 结论 |
|---|---|---|
| AD-01 | PDF 状态存放位置 | 新建 `KnowledgeFilePdfArtifact`，不扩展 `knowledgefile` PDF 状态字段 |
| AD-02 | 产物来源 | 采用验证后复用：原始 PDF 直引，当前合格预览优先引用，其他情况回退生成 |
| AD-03 | Worker 队列 | 新增独立 `knowledge_pdf_celery` 服务，默认并发 2 |
| AD-04 | 转换策略 | PDF、Office、Text/Web、Image 四类转换器注册表 |
| AD-05 | 并发一致性 | `GENERATED` 使用 generation/attempt 级候选路径和 first-success-wins；共享引用保留现有对象路径 |
| AD-06 | 第一阶段恢复能力 | 仅 Celery retry、数据库状态和日志，不建设扫描/人工入口 |
| AD-07 | Text/Web 转换引擎 | `txt/md/html` 规范化为受控 HTML，使用 F063 专用 Playwright 渲染器；不直接调用现有未加固浏览器入口 |

## 7. 数据与状态摘要

新表 `knowledge_file_pdf_artifact` 为每个物理 `knowledge_file_id` 保存一个当前状态记录，成功时记录 `artifact_origin`、`artifact_sha256`、源快照和 PDF 元数据，并通过 `ON DELETE CASCADE` 保证数据库记录不成为孤儿；MinIO 对象由业务删除链路在删除父记录前取得快照后按所有者显式清理：

```text
WAITING → PROCESSING → SUCCESS
                    ↘ WAITING（自动重试）
                    ↘ FAILED（重试耗尽）
```

每次显式重新处理递增 `generation`；Celery retry 和 redelivery 不递增。只有当前 generation、状态为 `SUCCESS`、来源为 `ORIGINAL/PARSE_PREVIEW/GENERATED` 且摘要完整的 `object_name` 才能被后续功能视为统一 PDF。`GENERATED` 由 Artifact 生命周期拥有，`ORIGINAL/PARSE_PREVIEW` 仅是共享引用，不得被 Artifact 普通清理删除。

历史文件没有 Artifact 行，表示未进入本阶段处理，不表示失败。

## 8. 转换矩阵摘要

| 格式 | 转换引擎 |
|---|---|
| `pdf` | PyMuPDF 统一校验后直接引用原始对象，登记 `ORIGINAL` |
| `doc/docx/ppt/pptx/xls/xlsx/csv` | 当前合格 PDF 预览优先；否则 LibreOffice Headless 回退生成 |
| `txt/md/html` | F063 `TextWebPdfConverter`：HTML 转义/Markdown 解析/HTML 清洗 + 受限 Playwright Chromium 打印 |
| `png/jpg/jpeg` | Pillow 方向处理 + PyMuPDF 页面封装 |

所有候选 PDF 均经 PyMuPDF 统一校验并计算内容摘要；只有新转换的 `GENERATED` 对象需要上传 MinIO，`ORIGINAL/PARSE_PREVIEW` 校验合格后直接登记引用。

Text/Web 复用现有 `md_to_pdf.py` 的 sanitizer、Markdown 解析和可适用打印样式；专用转换器必须强制清洗原始 HTML、禁用 JavaScript，并阻断 HTTP(S)、`file://` 和其他非预期资源请求。TXT 使用保留换行且允许长行折行的 `<pre>` 模板，Markdown 与 HTML 使用固定受控模板。

## 9. 影响范围

- 新增 Knowledge 领域 Artifact 模型、Repository、Service、迁移和测试，并注册到租户模型预加载清单。
- 新增 PDF 转换器、Validator、Celery task 和专用队列。
- 修改文件上传、Web 导入、覆盖/重解析、复制/迁移的解析后/无解析调度接线，并在解析附加元数据中保存 PDF 预览的源 provenance。
- 修改删除清理，按 `artifact_origin` 判断所有者、纳入 Word PDF preview 并对相同对象路径去重。
- 修改后端 Worker 启动配置，提供独立 `entrypoint.sh pdf` 模式；项目 Docker Compose 与 `base.Dockerfile` 保持不变，资源、网络和非 root 加固由实际部署方案另行配置。
- 不修改门户仓库、前端、API schema、下载服务和现有 Loader 业务逻辑。
- 不修改 Milvus、Elasticsearch、Embedding、Redis key 或知识解析状态机。

## 10. 发布与回滚

发布顺序：

1. 创建空 Artifact 表。
2. 部署并启动 `knowledge_pdf_celery` Worker。
3. 验证 LibreOffice、Chromium、字体、MinIO 和数据库前置条件。
4. 开启上传/重处理入口调度。
5. 灰度观察时长、失败率、重试、资源占用、三种来源分布、预览回退率和避免的重复存储。

回滚时先设置 `knowledge.pdf_artifact.enabled=false` 并停止新调度，再停止 PDF Worker、回滚应用代码。生产默认保留新表和已有对象，不自动执行破坏性清理或 Alembic downgrade。

## 11. 已知限制

- 缺少 Microsoft 专有字体时，Office 版式可能发生字体替换和分页偏差。
- 第一阶段没有定时恢复扫描；极端消息丢失可能留下长期 `WAITING/PROCESSING`，需通过数据库和日志发现。
- Worker 在候选对象上传后硬退出可能留下未引用的 generation/attempt 对象；第一阶段不提供后台自动回收。
- 历史解析预览如果缺少与当前源内容绑定的 provenance，不会自动复用，而是回退生成新 PDF。
- `original/{file_id}.*` 和 `preview/{file_id}.pdf` 为固定路径；覆盖前必须先提交新 generation 使旧 Artifact 失效，否则旧 `SUCCESS` 可能读取尚未校验的新字节。
- 共享原始/预览引用带来多所有者清理约束；Artifact 只能删除自己拥有的 `GENERATED` 对象。
- LibreOffice/Chromium 等解析器仍存在上游未知漏洞风险；生产环境必须通过独立服务、最小子进程环境和网络/资源策略降低影响面。
- 历史文件在后续独立回填完成前仍不保证统一 PDF。
- 水印下载必须在历史补齐和下载链路完成后另行设计、评审和上线。

## 12. 当前状态

- Spec Discovery：已完成，多轮澄清结果已写入 `requirements.md`。
- Spec Update（2026-07-20）：已确认 `txt/md/html` 统一采用受限 Playwright；补充专用转换器、现有实现复用边界、格式质量验收与 `AD-07`，不改变 Feature 范围或用户可见行为。
- Spec Update（2026-07-20）：已将 Artifact 定义为经过校验的逻辑 PDF 引用；原始 PDF 直接引用，当前解析预览在 provenance 匹配且校验通过时复用，其他情况回退生成；同步补充解析后投递、无解析直投、固定路径失效顺序和按所有者清理。
- Spec Update（2026-07-20）：实施前检索确认普通文件覆盖必须传递并持久化新内容 MD5，且 `pdf_artifact` 默认配置需进入 `initdb_config.yaml`；已同步更新设计。
- Scope Update（2026-07-21）：用户确认不修改 `docker/docker-compose.yml`；已撤销 Compose 服务/网络改动，保留独立队列、entrypoint 和镜像运行基线。
- Scope Update（2026-07-21）：用户确认不修改 `src/backend/base.Dockerfile`；已撤销 PDF Worker 用户和 Chromium 全局目录改动，直接复用现有镜像转换依赖。
- Bugfix（2026-07-21）：`sh entrypoint.sh` 会在 Bash 专属 `pipefail`/数组语法处启动失败；已在脚本首部增加原参数 Bash 重执行，并加入 Dash 运行时回归测试，Dockerfile 与 Compose 保持不变。
- `requirements.md`：已确认，状态为 `approved`。
- `design.md`：已确认，状态为 `approved`。
- `tasks.md`：T001-T017 已完成；T017 修复 `sh entrypoint.sh` 解析 Bash 语法失败的问题。
- 生产代码与迁移脚本：已实现；尚未在真实 MySQL/DM8 或生产数据库执行迁移。
- 验证状态：T017 Dash/Bash 启动回归通过；完整 F063 套件发现当前 `HEAD` 已存在的 Worker 聚合行为与部署契约测试不一致，整体状态暂为 `NOT_VERIFIED`，详见 `verification.md`。

## 相关文档

- [v2.6.0 Release Contract](../release-contract.md)
- [Requirements](./requirements.md)
- [Design](./design.md)
- [Verification](./verification.md)
