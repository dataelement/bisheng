# 需求说明 Requirements: 专家问答上传资源持久化

## 阅读摘要
- 本文档说明：修复专家问答中提问图片、提问附件、回答图片和回答附件把 `tmp-dir` 预签名 URL 当作永久数据保存的问题。
- 当前状态：`implementation-verified, staging-pending`
- 需要重点确认：所有已发布资源采用“发布/更新时转正式桶、数据库保存 object key、读取时重新签名”；全局 `tmp-dir` 生命周期规则另行治理。
- 本次范围由“回答图片”扩大为“专家问答全部上传资源”，旧 spec 目录已由 `054-qa-answer-image-persistence` 更名。

## 元信息 Metadata
- Feature ID: `054-qa-uploaded-asset-persistence`
- Status: `in-progress`
- Mode: `update-existing`
- Created: `2026-08-11`
- Updated: `2026-08-12`
- Source request: `补充发现提问图片和附件也使用 tmp-dir，需要扩大持久化修复规划`

## 需求入口摘要 Intake Summary
- 问题 Problem: `/api/v1/qa_experts/upload` 默认把所有 QA 上传写入 `tmp-dir` 并返回 7 天预签名 URL；问题和回答服务把上传引用原样保存，读取时也不重新签名。
- 当前状态 Current state: `qa_question.image_url/file_url/attachments` 与 `qa_answer.images_url/attachments` 均可能持有临时引用；创建、更新和历史数据都存在过期风险。
- 目标结果 Target outcome: QA 业务记录只保存正式对象引用；API 输出按需生成访问 URL；旧 URL 与业务附件 ID 在迁移期保持兼容。
- 影响对象 Affected users/systems: 门户提问者、专家、浏览者、QA 上传/问题/回答 API、`qa_question`、`qa_answer`、MinIO。
- 请求停止点 Requested stopping point: `tasks`

## 范围 Scope

### 包含 Includes
- 覆盖 `qa_question.image_url`、`qa_question.file_url`、`qa_question.attachments` 中的 MinIO 引用。
- 覆盖 `qa_answer.images_url`、`qa_answer.attachments` 中的 MinIO 引用。
- 覆盖问题和回答的创建、更新、详情/列表读取。
- 上传接口继续返回 `file_path`，并增加 canonical `relative_path` 和资源标识所需的稳定信息。
- 受信任临时对象在业务记录提交前复制到正式私有 bucket，数据库只保存永久 object key。
- API 读取时只对 object key 动态签名；业务附件 ID 或其他非对象标识保持原值。
- 提供默认 dry-run、支持批次和幂等重跑的双表历史修复脚本。
- 扩展尚未部署的 `f083`，将三个多值资源字段 `qa_question.attachments`、`qa_answer.attachments`、`qa_answer.images_url` 统一扩容，避免永久 key 拼接后再次超过 255 字符。
- 覆盖复制、数据库写入、部分成功、更新混合新旧引用和临时清理失败的补偿策略。
- QA 自上传图片和文件使用正确 MIME、内联签名与门户站内预览交互。

### 不包含 Excludes
- 不处理 `related_docs`，它是知识文档业务 ID，不是上传对象。
- 不修改问题正文中的富文本内嵌资源；若正文实际包含临时 URL，需另做富文本引用扫描 spec。
- 不在本次修改全局 `tmp-dir` Lifecycle `Filter(prefix="*")`，避免未经盘点影响知识库、工作流等共享调用方。
- 不把正式 QA 资源设置为匿名公开。
- 不立即删除更新前或软删除记录关联的正式对象；孤儿资源回收另行设计。
- 不新增资源关系表或 JSON 列，不自动执行生产数据修复、MinIO 操作或 DDL。
- 不借生命周期修复改变附件允许类型或产品大小规则；图片仍按现有三张限制进行安全验证，附件限制需沿用现有网关/产品约束。

## 需求列表 Requirements

### REQ-001: 提问资源在发布后永久可访问
作为门户提问者，我需要问题图片和附件在问题创建或更新后脱离临时桶，以便问题长期查看时资源仍可访问。

#### 验收标准 Acceptance Criteria
- `AC-REQ-001-01`: GIVEN 新问题包含受信任的临时 `image_url`、`file_url` 或 `attachments` 对象引用 WHEN 创建成功 THEN 系统 SHALL 将这些对象复制到正式 bucket，并只保存永久 object key。
- `AC-REQ-001-02`: GIVEN 问题更新同时包含既有永久引用和新临时引用 WHEN 更新成功 THEN 系统 SHALL 保留既有引用、仅转正新引用，并原子替换数据库字段。
- `AC-REQ-001-03`: GIVEN 上传时的 URL 已过期但正式对象仍存在 WHEN 查询问题列表或详情 THEN 系统 SHALL 返回新生成的有效访问 URL。
- `AC-REQ-001-04`: GIVEN 问题资源字段为空或 `attachments` 仅包含业务附件 ID WHEN 创建、更新或读取 THEN 系统 SHALL 不执行无关对象存储写操作且保持原语义。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-001-01 | V-AC-REQ-001-01 | question service/API test | 三类字段的 `tmp -> permanent -> DB key` 断言 |
| AC-REQ-001-02 | V-AC-REQ-001-02 | update service test | 既有 key、新 tmp URL、移除项的差异更新与失败回滚 |
| AC-REQ-001-03 | V-AC-REQ-001-03 | list/detail response test | DB key 每次读取生成新签名，旧签名不回写 |
| AC-REQ-001-04 | V-AC-REQ-001-04 | parameterized no-op test | 空值和 opaque attachment ID 零 copy/sign |

### REQ-002: 回答资源在发布后永久可访问
作为门户专家，我需要回答图片和附件在发布或更新后转为正式对象，以便回答资源不会因临时桶或原始签名过期而失效。

#### 验收标准 Acceptance Criteria
- `AC-REQ-002-01`: GIVEN 回答包含受信任的临时 `images_url` 或 `attachments` 对象引用 WHEN发布成功 THEN 系统 SHALL 转正所有对象并只保存永久 object key。
- `AC-REQ-002-02`: GIVEN 回答更新包含新临时引用 WHEN 更新成功 THEN 系统 SHALL 转正新引用；更新接口不得继续忽略请求中的 `images_url`。
- `AC-REQ-002-03`: WHEN 创建、按问题列表或按专家读取回答 THEN 系统 SHALL 把永久 object key 转换为新的访问 URL，并在响应 schema 中显式包含资源字段。
- `AC-REQ-002-04`: GIVEN 回答没有上传资源或附件仅为业务 ID WHEN 创建、更新或读取 THEN 系统 SHALL 保持现有行为，不执行无关对象存储写操作。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-002-01 | V-AC-REQ-002-01 | answer service/API test | 图片和附件的 copy、DB key 与响应 URL 断言 |
| AC-REQ-002-02 | V-AC-REQ-002-02 | update endpoint/service test | `images_url` 被纳入更新并完成新引用转正 |
| AC-REQ-002-03 | V-AC-REQ-002-03 | schema/read path test | create/get/list/by-expert 全部 resolve，schema 字段完整 |
| AC-REQ-002-04 | V-AC-REQ-002-04 | parameterized no-op test | 无资源/业务 ID 路径零 copy/sign |

### REQ-003: 保持现有门户和历史数据兼容
作为门户调用方，我需要后端兼容现有字段与完整预签名 URL，以便前后端无需强制同时切换。

#### 验收标准 Acceptance Criteria
- `AC-REQ-003-01`: WHEN 调用现有 QA 上传接口 THEN 响应 SHALL 保留 `file_path`，并额外返回不含 host/query 的 `relative_path`。
- `AC-REQ-003-02`: GIVEN 资源字段是分号分隔完整 URL、无 host 相对 URL、canonical key 或 opaque 业务 ID WHEN 后端处理 THEN 系统 SHALL 按字段策略正确分类，不把业务 ID 当作 MinIO 对象。
- `AC-REQ-003-03`: WHEN API 返回问题或回答 THEN 对外字段名称和分隔格式 SHALL 保持兼容，MinIO key 转为 URL，业务 ID 保持原值。
- `AC-REQ-003-04`: GIVEN 同一记录包含旧 URL、新 key 和业务 ID WHEN 读取 THEN 单个坏的历史资源引用 SHALL 被脱敏报告，不得导致整个问题/回答列表 500。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-003-01 | V-AC-REQ-003-01 | upload API test | `file_path + relative_path` 兼容响应 |
| AC-REQ-003-02 | V-AC-REQ-003-02 | codec parameterized test | URL/relative/key/ID 分类矩阵 |
| AC-REQ-003-03 | V-AC-REQ-003-03 | API contract test | 问题/回答创建、更新、列表、详情响应字段 |
| AC-REQ-003-04 | V-AC-REQ-003-04 | mixed legacy read test | 可用项返回、坏项隔离、整页成功 |

### REQ-004: 跨对象存储与数据库写入保持一致
作为系统运维人员，我需要创建和更新失败时具备补偿，以便不会产生引用缺失对象的业务记录或无限孤儿对象。

#### 验收标准 Acceptance Criteria
- `AC-REQ-004-01`: IF 任一来源对象不存在、host/bucket/key 不可信或图片内容校验失败 THEN 系统 SHALL 拒绝相应创建/更新，且不得修改业务记录。
- `AC-REQ-004-02`: IF 多对象复制部分失败 THEN 系统 SHALL 删除本次已创建的目标对象并保留所有来源对象。
- `AC-REQ-004-03`: IF 复制完成但问题/回答数据库提交失败 THEN 系统 SHALL 删除本次新建目标对象，原业务记录保持不变。
- `AC-REQ-004-04`: GIVEN 同一临时引用被重试 WHEN 目标对象已存在 THEN 转正 SHALL 幂等复用确定性 object key，不误删预先存在的目标。
- `AC-REQ-004-05`: WHEN DB 已成功提交 THEN 临时对象删除失败 SHALL 只记录脱敏告警，不反向删除业务记录所引用的永久对象。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-004-01 | V-AC-REQ-004-01 | failure/adversarial test | 非可信或缺失资源时 Repository create/update 未调用 |
| AC-REQ-004-02 | V-AC-REQ-004-02 | partial-copy test | 只补偿本次创建目标，来源不删 |
| AC-REQ-004-03 | V-AC-REQ-004-03 | DB failure injection | create/update 失败后的目标补偿与原行不变 |
| AC-REQ-004-04 | V-AC-REQ-004-04 | idempotency test | 相同来源映射同一 key，预存目标不进补偿清单 |
| AC-REQ-004-05 | V-AC-REQ-004-05 | cleanup/log test | commit 后 remove 失败仍成功且日志脱敏 |

### REQ-005: 双表历史资源可审计修复
作为部署运维人员，我需要扫描并修复问题和回答中的旧临时引用，以便尽可能抢救仍存在的对象并明确不可恢复项。

#### 验收标准 Acceptance Criteria
- `AC-REQ-005-01`: WHEN 修复脚本默认运行 THEN脚本 SHALL 只读扫描 `qa_question` 和 `qa_answer` 目标字段，输出可迁移、已迁移、业务 ID、对象缺失、非法引用和失败计数。
- `AC-REQ-005-02`: GIVEN 旧临时对象存在 WHEN 使用 `--apply` THEN 脚本 SHALL 先复制后按 batch 更新对应字段，保留 opaque 业务 ID。
- `AC-REQ-005-03`: IF 来源缺失或处理失败 THEN 脚本 SHALL 保留整条原值，记录表名、记录 ID、字段名和脱敏原因后继续。
- `AC-REQ-005-04`: WHEN 脚本重复执行 THEN 已是永久 key 或纯业务 ID 的项目 SHALL 安全跳过，不重复复制或改写。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-005-01 | V-AC-REQ-005-01 | script dry-run test | 双表扫描、分类计数、零写入 |
| AC-REQ-005-02 | V-AC-REQ-005-02 | script apply contract | copy-before-update、batch commit、ID 保留 |
| AC-REQ-005-03 | V-AC-REQ-005-03 | script failure test | 失败字段整值不变、报告后继续 |
| AC-REQ-005-04 | V-AC-REQ-005-04 | script idempotency test | 二次执行零 copy/update |

### REQ-006: 上传资源访问安全
作为平台管理员，我需要只转正受信任的 QA 上传资源，以便避免任意 URL、路径穿越、签名泄露和公开权限扩大。

#### 验收标准 Acceptance Criteria
- `AC-REQ-006-01`: WHEN 解析资源 THEN系统 SHALL 只接受配置的 MinIO share host、`tmp_bucket` 和允许 key，不发起外部 HTTP 请求。
- `AC-REQ-006-02`: WHEN 处理回答/提问图片 THEN系统 SHALL 限制现有图片数量，下载内容前检查 object size，并验证 JPEG/PNG/WEBP 真实格式；附件生命周期修复不得擅自改变现有业务格式策略。
- `AC-REQ-006-03`: WHEN 返回正式对象 THEN系统 SHALL 使用私有 bucket 短期签名，不新增匿名读取 policy。
- `AC-REQ-006-04`: WHEN 记录日志或修复报告 THEN系统 SHALL 不输出 `X-Amz-*` 查询、Access Key 或完整签名 URL。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-006-01 | V-AC-REQ-006-01 | adversarial codec test | 外部 host/错误 bucket/编码穿越拒绝且无 HTTP client |
| AC-REQ-006-02 | V-AC-REQ-006-02 | image/attachment policy test | 图片格式/size/数量矩阵，附件格式行为保持 |
| AC-REQ-006-03 | V-AC-REQ-006-03 | storage contract test | permanent bucket + get_share_link，无 policy write |
| AC-REQ-006-04 | V-AC-REQ-006-04 | log capture test | 日志/报告无签名 query 和凭证 |

### REQ-007: QA 图片与附件点击进入预览
作为门户用户，我需要在专家问答详情中点击图片或自上传文件后进入站内预览，而不是因为对象 MIME 错误或直接跳转对象链接而触发浏览器下载。知识库关联文档继续复用现有知识文档详情预览。

#### 验收标准 Acceptance Criteria
- `AC-REQ-007-01`: WHEN QA 上传图片或文件 THEN 系统 SHALL 把可信的实际/扩展名 MIME 写入临时对象；转正时 SHALL 保留或修正为可识别 MIME。
- `AC-REQ-007-02`: GIVEN 新旧正式对象的原始 metadata 是 `application/octet-stream` WHEN API 返回短期签名 URL THEN URL SHALL 使用受控扩展名推断覆盖响应 MIME，并声明 `inline`，不得默认声明 `attachment`。
- `AC-REQ-007-03`: WHEN 用户点击问题或回答图片 THEN 门户 SHALL 在当前页面打开图片预览弹窗，不直接导航到对象 URL。
- `AC-REQ-007-04`: WHEN 用户点击 QA 自上传文件 THEN 门户 SHALL 对 PDF、DOCX、表格、Markdown、HTML、文本和图片复用现有阅读器；不支持的格式 SHALL 显示明确提示并提供显式下载入口。知识库关联文档 SHALL 保持进入现有知识详情预览。
- `AC-REQ-007-05`: GIVEN 已登录用户打开 QA 图片或文件预览 WHEN 阅读器展示可预览内容 THEN 门户 SHALL 复用系统现有预览水印，展示当前用户、部门、日期和后台配置文案，并覆盖图片、PDF、DOCX、表格、Markdown、HTML 与文本预览表面。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-007-01 | V-AC-REQ-007-01 | upload/promotion contract test | 上传携带 MIME；旧 octet-stream 图片按真实内容校验并以正确 MIME copy |
| AC-REQ-007-02 | V-AC-REQ-007-02 | signing contract test | 预签名调用包含 `response-content-type` 与 `response-content-disposition=inline` |
| AC-REQ-007-03 | V-AC-REQ-007-03 | frontend contract test + build | 问题/回答图片点击绑定 preview state，不再使用直跳对象 anchor |
| AC-REQ-007-04 | V-AC-REQ-007-04 | preview mode unit test + build + staging smoke | 支持格式映射现有 reader；不支持格式提示/下载；知识文档链接不变 |
| AC-REQ-007-05 | V-AC-REQ-007-05 | watermark wiring contract + existing watermark regression + build | QA 弹窗提供当前用户水印上下文；各 reader 表面继续使用现有 overlay |

## 非功能需求 Non-Functional Requirements
- `NFR-001`: 所有 MinIO 同步 I/O 必须通过现有 async 包装，不阻塞事件循环。
- `NFR-002`: 不新增第三方依赖；图片验证复用 Pillow。
- `NFR-003`: object key 包含 `tenant_id`、资源归属类型、业务记录 ID/临时稳定标识和不可预测 UUID。
- `NFR-004`: mixed-reader 必须先于或与新 writer 同版部署，历史脚本不要求停机。
- `NFR-005`: 上传资源字段解析、签名和历史修复使用同一 codec，防止不同链路语义漂移。

## 澄清记录 Clarifications

### Session 2026-08-11
- Q: 是否只影响回答图片？ -> A: 否。代码确认提问 `image_url/file_url/attachments`、回答 `images_url/attachments` 均可能原样保存共享上传接口返回的 `tmp-dir` URL。
- Q: 本轮是否实现？ -> A: 用户确认按当前计划快速实施；本地实现和自动化验证已完成，staging 门禁待执行。
- Q: `attachments` 是否全部是 MinIO URL？ -> A: 现有文档把它描述为业务文件 ID，但运行 schema 使用字符串且共享上传接口返回 URL；设计按“可识别 MinIO 引用转正，opaque ID 原样保留”兼容两种语义。
- Q: 为什么详情页点击图片/附件会直接下载？ -> A: QA 上传没有传 MIME，MinIO 对象被写成 `application/octet-stream`；门户详情又直接打开对象链接。用户要求图片和自上传文件改为站内预览，知识库关联文档维持原预览链路。
- Q: QA 站内预览是否需要水印？ -> A: 是，用户要求复用当前系统水印实现；仅补齐 QA 弹窗的当前用户 Provider，不新建水印样式或文案规则。

## 假设 Assumptions
- 当前门户可能继续提交完整预签名 URL，因此后端不能要求前端同步升级。
- spec 053 最初只要求扩容 `qa_answer.images_url`；由于 `f083` 尚未部署，本 spec 直接扩展同一 migration，同时扩容 `qa_question.attachments`、`qa_answer.attachments` 与 `qa_answer.images_url`，不额外占用 revision。
- 问题/回答删除均采用业务软删除或状态更新，资源物理回收不属于本次紧急修复。

## 风险 Risks
- `attachments` 存在 URL、object key、业务 ID 多种历史形态，错误分类可能破坏业务附件；必须参数化测试并默认保留未知 opaque 值。
- 对象存储与 DB 无共享事务；创建与更新都必须记录 promotion journal 并补偿。
- 已被临时生命周期删除的对象无法恢复，只能报告或从备份找回。
- 问题正文可能内嵌上传 URL，但当前代码没有结构化字段证据；已明确列为需另查的非目标。
- 全局 lifecycle 修复具有跨模块删除风险，不能夹带在本 spec 中。

## 需求质量门 Requirements Quality Gate
- [x] Every requirement has a stable `REQ-*` ID.
- [x] Every requirement has at least one `AC-*` acceptance criterion.
- [x] Every acceptance criterion has a stable `AC-*` ID.
- [x] Every acceptance criterion has at least one `V-*` verification ID.
- [x] Every acceptance criterion has a verification method.
- [x] Acceptance criteria sharing one behavior reuse an evidence target instead of duplicating commands.
- [x] No orphan `AC-*` or `V-*` entries exist.
- [x] Scope includes and excludes are explicit.
- [x] No critical ambiguity remains.
- [x] Requirements avoid implementation details unless explicitly required.
