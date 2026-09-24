# 需求说明 Requirements：门户带水印 PDF 下载、知识预览与问答水印

## 阅读摘要

- 本文档定义首钢门户知识文档下载统一切换为“实时生成带当前用户水印的 PDF”，并在独立门户与 BiSheng 的知识预览及登录态问答正文中展示当前用户前端水印的业务范围、权限规则、失败语义和验收方式。
- 当前状态：`partial`，下载、按需统一 PDF 与知识预览水印已完成自动化实施；本次扩展把同一全尺寸 SVG 水印覆盖到两端全部登录态问答正文，并明确 iframe 单层责任、匿名/分享排除和交互边界。
- 核心前提：有效统一 PDF 产物仍是个人水印的唯一输入；产物缺失或不可用时在当前下载请求内同步生成并持久化，最终失败也不回退无水印原文件。
- 门户只提供单文件带水印下载；`/workspace/knowledge-portal` 的文件夹行级下载和文件/文件夹多选批量下载均不再提供，既有非门户批量接口保持兼容。
- 需要重点确认：分享下载采用用户绑定的短期授权；PDF 就绪与个人水印分别使用 300 秒和 60 秒上限；成功埋点以响应首个文件块成功发送为准。

## 元信息 Metadata

- Feature ID: `064-portal-watermarked-pdf-download`
- Status: `partial`
- Mode: `spec-then-implement`
- Created: `2026-07-21`
- Updated: `2026-07-23`
- Version: `v2.6.0`
- Source request: 门户所有单文件知识文档下载统一输出实时加水印 PDF；下载时若统一 PDF 产物缺失或不可用则同步生成、持久化并继续下载，最终失败才提示用户；独立门户与 BiSheng 的全部知识预览入口及登录态智能问答、智能应用、Agent、知识空间问答、单文档问答等对话正文增加当前用户前端水印；下载与前端水印统一显示“主部门-姓名--用户账号-北京日期 / 首钢股份内部资料，严禁外传，违者必究”两行黑体水印；匿名、访客及只读分享对话不显示用户水印。

## 需求入口摘要 Intake Summary

- 问题 Problem: 统一下载当前只消费已有 `SUCCESS` PDF 产物，产物缺失、状态异常、源快照过期或存储对象损坏时会立即失败，即使原始文件仍可转换。
- 当前状态 Current state: 两端下载与预览水印已落地；`PortalPdfDownloadService` 在 F063 accessor 返回空引用时立即返回 409，且不会在下载请求内修复产物。
- 目标结果 Target outcome: 下载请求优先复用有效产物；任何可恢复的产物不可用状态都在当前请求内同步生成并保存，同一文件并发请求共享一次生成结果，只有最终生成、保存、校验或水印失败时前端才展示错误。
- 影响对象 Affected users/systems: 首钢门户前端、门户 BFF、BiSheng 门户知识 API、BiSheng client 门户知识工作台、知识文件权限、分享访问会话、统一 PDF 产物、MinIO、Redis、门户下载遥测。
- 请求停止点 Requested stopping point: 完整实施并验证本次扩展范围。

## 现状证据 Current Evidence

- 独立门户 `SearchPage.tsx`、`ListPage.tsx` 和 `DetailPage.tsx` 已统一调用 BFF 二进制水印接口，并使用 Fetch/Blob 保存 `.pdf`。
- 门户 BFF 已清空预览响应中的原下载字段，下载成功事件由 BiSheng 在首块发送后统一记录。
- BiSheng 现有 `/knowledge/space/{space_id}/files/{file_id}/download` 返回原始/预览 URL，并被文件行、独立预览、门户原地预览和版本历史四类前端入口使用；该契约是本次必须收口的无水印绕过路径。
- F063 的 `get_available_pdf_artifact_reference()` 只返回与当前文件 `tenant_id`、对象名和 MD5 一致的成功产物，并允许该引用复用原始 PDF 或解析预览 PDF。
- BiSheng 已直接依赖 `pymupdf>=1.26.5`，基础镜像已安装 `fonts-wqy-zenhei`。
- 分享验证通过后，门户当前把 `ShareAccessSession` 存入进程内字典；多 Worker 无法共享，也没有可供 BiSheng 下载接口验证的密码/邀请码通过证明。

## 范围 Scope

### 包含 Includes

- 门户搜索结果和知识列表中的下载按钮。
- 门户文档详情页下载按钮，包括首页推荐、相关推荐、收藏、问答引用等最终进入详情页的路径。
- 文档分享页面中的下载；公共分享和部门分享均要求下载人已登录。
- 专家问答中具有明确 `(space_id, file_id)` 的关联知识文档，将其统一导向门户详情下载链路。
- QA/聊天引用中具有明确知识空间 ID 和文件 ID 的知识文档。
- 门户 BFF 统一二进制下载接口及 BiSheng 门户专用带水印 PDF 接口。
- 普通访问的 `download_file` 权限、租户和文件归属校验。
- 分享访问的密码/邀请码证明、部门范围、链接有效期和 `allow_download` 校验。
- 每页平铺水印、同步生成、超时、并发保护、临时文件清理和成功下载遥测。
- 使用现有统一 PDF 产物引用，无论其实际来源为原始 PDF、解析预览 PDF 或 F063 生成对象。
- 下载时按需修复缺失、非成功、源快照过期、对象丢失、PDF 损坏或 SHA 不一致的统一 PDF 产物；转换结果写回现有 Artifact 表并在需要时上传 MinIO。
- 同一租户同一文件的并发按需生成必须 single-flight；等待方复用生成结果，但个人水印仍按当前用户分别生成。
- `/workspace/knowledge-portal` 文件、文件夹或混合多选后的批量操作菜单隐藏“批量下载”；其余批量操作按既有权限继续工作。
- `/workspace/knowledge-portal` 文件行、原地预览、收藏原地预览、独立文件预览和版本历史下载统一输出带水印 PDF。
- BiSheng 旧单文件下载 endpoint 不再返回 `original_url`、`preview_url`、MinIO 对象名或签名 URL；仓库内调用方同步迁移到二进制契约。
- `/workspace/knowledge-portal` 的文件夹卡片、表格行和更多菜单不再展示下载动作。
- 独立门户详情页及由搜索结果、列表结果等打开的预览弹窗统一通过详情预览层显示 CSS 水印，覆盖 PDF、DOCX、表格、Markdown、HTML、文本、图片和 chunks 等既有知识预览模式。
- BiSheng 知识文件独立预览、门户原地预览、收藏原地预览、版本对比和知识引用预览统一显示 CSS 水印，覆盖普通文件与富媒体知识预览；聊天上传、SOP、Artifact 和其他非知识预览不纳入。
- 下载 PDF、独立门户预览和 BiSheng 预览统一采用两行黑体水印、同一字段顺序及等效视觉参数；间距按实际文字旋转包围盒自动扩大，奇偶行水平错位 50%，前端按正文实际尺寸在全尺寸 SVG 中逐坐标绘制独立水印组，不使用 SVG pattern 切片。
- 独立门户匿名用户可继续查看已通过分享校验的文件元数据和摘要，但 `/preview`、`/preview/content`、`/chunks` 必须返回 401；前端匿名态不得发起这些正文请求并显示“登录后预览”。
- Portal 登录态智能问答/智能写作正文、workflow Agent 对话和第三方 URL 智能应用 iframe 可见区域显示当前用户水印；Portal workflow iframe 由 BiSheng 认证子页面负责，Portal 宿主不得重复叠加。
- BiSheng 登录态主智能问答、智能应用、Agent、workflow、assistant、认证独立对话、知识空间问答、单文档问答和订阅文章/频道问答正文显示当前用户水印。
- 问答水印固定覆盖当前可见正文 surface，覆盖空会话、历史消息、生成中、加载和错误状态；水印不随消息总高度增长，消息滚动或 surface resize 后仍覆盖可见区域。

### 不包含 Excludes

- 不实现历史文件 PDF 产物批量补齐脚本、补偿扫描或运营后台；历史文件在实际下载时按本 Feature 的同步规则处理。
- 不提供 DOCX、XLSX、PPTX、TXT、图片等原文件下载，也不提供无水印回退。
- 不处理没有 `(space_id, file_id)` 的外部 URL、普通图片或普通附件；它们保持现有访问方式。
- 不改变既有预览源、文件解析、渲染器选择和降级策略；仅在已授权知识预览上增加前端 CSS 覆盖层。
- 不实现门户多文件/文件夹带水印 ZIP，不新增门户批量下载接口、目录选择弹窗或批量水印任务。
- 不删除或修改 BiSheng 现有 `batch-download` 后端契约，不移除知识空间详情页及其他非门户客户端的批量下载入口。
- 不扩展 BiSheng 管理端、普通平台知识库及数据集、模型、任务结果等非门户下载产品范围；共享旧单文件 endpoint 的仓库内调用方仅做必要兼容迁移。
- 不生成或保存长期个人水印副本，不在 MinIO 中上传个人水印文件，不建立个人水印缓存。
- 不新增数据库表、Alembic 迁移、Celery 队列、Celery Worker 或异步水印任务。
- 不修改 `docker-compose.yml`、`src/backend/base.Dockerfile` 或现有 PDF Worker 启动方式。
- 不在匿名访客对话、公开/只读分享会话、Portal 专家问答等非聊天业务页展示用户水印。
- 不在问答顶部栏、系统导航、历史侧栏、输入框、弹窗或引用详情侧栏展示水印。
- 不修改问答消息接口、会话数据、服务端存储或导出文件，不实现服务端聊天截图水印。

## 需求列表 Requirements

### REQ-001: 门户下载入口与文件格式统一

作为门户用户，我需要所有知识文档下载入口使用同一下载能力，以便得到一致、安全的 PDF 文件，而不是不同入口返回不同原文件。

#### 验收标准 Acceptance Criteria

- `AC-REQ-001-01`: WHEN 登录用户在门户搜索结果、知识列表或文档详情点击下载 THEN 系统 SHALL 调用同一个门户 BFF 下载接口，并只返回 `application/pdf` 带水印文件。
- `AC-REQ-001-02`: WHEN 文档从首页推荐、相关推荐、收藏、QA/聊天引用或专家问答关联知识文档进入详情页 THEN 详情页 SHALL 使用相同下载接口；WHEN 附件缺少有效 `(space_id, file_id)` THEN 系统 SHALL 保持其现有外部或普通附件行为。
- `AC-REQ-001-03`: WHEN 任意原始扩展名文档下载成功 THEN 浏览器保存文件名 SHALL 为安全处理后的“原文件名去除最后一个扩展名 + `.pdf`”，不得继续使用 DOCX、XLSX、PPTX 等扩展名。
- `AC-REQ-001-04`: WHEN 本 Feature 上线 THEN 门户下载 SHALL 不再读取预览清单的 `download_url`，门户 BFF SHALL 不再向浏览器暴露可作为原文件下载入口的该字段值；登录用户的在线预览内容和既有预览降级能力 SHALL 保持可用。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-001-01 | V-AC-REQ-001-01 | frontend unit + BFF integration | Search/List/Detail 调用统一 API；响应 `Content-Type` 为 PDF |
| AC-REQ-001-02 | V-AC-REQ-001-02 | source contract + route tests | 首页/相关推荐/收藏/引用进入详情；专家问答结构化知识文档改为门户详情；外部附件不变 |
| AC-REQ-001-03 | V-AC-REQ-001-03 | unit + HTTP header test | DOCX/XLSX/PPTX/无扩展名/中文/特殊字符文件名及 RFC 5987 `Content-Disposition` |
| AC-REQ-001-04 | V-AC-REQ-001-04 | source scan + preview regression | 下载工具不引用 preview `downloadUrl`；BFF 返回空下载字段；现有 viewer/chunks 预览测试通过 |

### REQ-002: 下载时按需确保统一 PDF 产物

作为下载链路，我需要在个人水印前取得并验证当前有效的统一 PDF 产物，并在产物可恢复时自动修复，以便用户无需依赖发布前批量补齐也能完成下载。

#### 验收标准 Acceptance Criteria

- `AC-REQ-002-01`: WHEN 下载请求通过身份与权限校验且当前产物为与租户、文件、源对象和源 MD5 匹配的 `SUCCESS` 引用 THEN 系统 SHALL 直接读取并校验对象、PDF 结构、大小和 SHA，校验通过时 SHALL NOT 触发重新生成。
- `AC-REQ-002-02`: IF 当前产物不存在、为 `WAITING/PROCESSING/FAILED`、对象引用缺失或源快照已过期 THEN 系统 SHALL 在当前下载请求内同步取得或生成有效统一 PDF 并持久化，再继续个人水印与下载；系统 SHALL NOT 返回无水印原文件或预览 URL。
- `AC-REQ-002-03`: WHEN 原始文件本身是有效 PDF 或存在与当前源 MD5 匹配的有效解析预览 PDF THEN 生成链路 SHALL 只把该对象登记为统一产物引用，不复制新的基线对象；WHEN 必须执行格式转换 THEN 系统 SHALL 将生成 PDF 上传 MinIO 并登记为 `GENERATED` 当前产物。
- `AC-REQ-002-04`: IF `SUCCESS` 引用的对象丢失、PDF 损坏、大小无效或实际 SHA 与登记值不一致 THEN 系统 SHALL 将该引用视为不可用并在同一请求内强制重新生成一次；重新生成或重新读取仍失败时 SHALL 返回脱敏的最终错误并由前端展示。
- `AC-REQ-002-05`: WHEN 不同用户并发下载同一租户同一文件且需要生成统一 PDF THEN 系统 SHALL 只执行一次转换和持久化；其他请求 SHALL 在 PDF 就绪阶段上限内等待并复用结果，各请求仍 SHALL 生成独立的用户水印。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-002-01 | V-AC-REQ-002-01 | service/storage integration | 当前有效引用读取、PDF/SHA 校验通过且生成器调用为零 |
| AC-REQ-002-02 | V-AC-REQ-002-02 | parameterized service/API test | 无记录、WAITING/PROCESSING/FAILED、引用缺失和源过期均在请求内得到持久化引用后继续下载 |
| AC-REQ-002-03 | V-AC-REQ-002-03 | processor/storage interaction test | ORIGINAL/PARSE_PREVIEW 只登记引用；GENERATED 恰好上传并登记一次 |
| AC-REQ-002-04 | V-AC-REQ-002-04 | corrupt/missing object regression | 对象缺失、损坏、空文件、SHA 不一致触发一次强制生成；最终失败无原文件 fallback 且错误脱敏 |
| AC-REQ-002-05 | V-AC-REQ-002-05 | deterministic concurrency test | 两个不同用户同文件并发只转换/上传一次，等待方复用引用且分别生成个人水印 |

### REQ-003: 每页包含当前下载人的可辨识水印

作为文档管理方，我需要下载 PDF 的每一页都包含当前下载人的主部门、姓名、用户账号和下载日期，以便文档流转后可以追溯来源。

#### 验收标准 Acceptance Criteria

- `AC-REQ-003-01`: WHEN 水印 PDF 生成成功 THEN 每一页 SHALL 以倾斜、平铺、半透明方式重复显示固定两行文字：第一行为“用户主部门-姓名--用户账号-YYYY/MM/DD”，第二行为“首钢股份内部资料，严禁外传，违者必究”；姓名与账号之间 SHALL 保留两个 ASCII 连字符 `--`，不得显示字段前缀或时分秒。PDF 默认视觉基准 SHALL 为黑体、`12pt`、绝对倾角 `35°`、最终视觉方向左下向右上 `/`、透明度 `0.31` 和中性灰度 `0.45`；布局 SHALL 使用所选字体测量最长一行，基于旋转后两行包围盒加安全留白计算步长，横向与纵向安全留白 SHALL 分别为 `36pt` 和 `27pt`，最小步长分别为 `180pt` 和 `135pt`；文字更长时 SHALL 自动扩大且 SHALL NOT 缩小字号、截断或重叠。奇偶行 SHALL 水平错位 50%。
- `AC-REQ-003-02`: WHEN 构造水印身份 THEN 姓名 SHALL 取服务端当前认证用户的 `user_name`，用户账号 SHALL 优先取该用户的 `external_id`，为空时 MAY 回退当前认证上下文的账号值；部门 SHALL 取该用户 `is_primary=1` 的主部门名称；WHEN 用户没有主部门 THEN 第一行 SHALL 为“姓名--用户账号-YYYY/MM/DD”，不得包含部门占位文字或行首连字符；不得使用浏览器或 BFF 提交的姓名、部门、账号或日期文本。
- `AC-REQ-003-03`: WHEN 一次下载开始 THEN 系统 SHALL 在 `Asia/Shanghai` 时区采集一次日期并拼入第一行，在全部页面复用，格式严格为 `YYYY/MM/DD`；WHEN 用户跨日期再次点击下载 THEN 系统 SHALL 采集新的日期并生成新的水印文件。
- `AC-REQ-003-04`: WHEN 输入包含多页、横向页、旋转页、中文和复杂原始内容 THEN 输出 SHALL 保留原页数、页面尺寸、方向和可读内容，且 SHALL 是可打开、非加密、页数大于零的合法 PDF；输入对象 SHALL 不被修改。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-003-01 | V-AC-REQ-003-01 | PyMuPDF measurement/layout unit + render/manual QA | 每页提取到两行目标文字且有多个错位实例；普通/长身份步长不小于旋转包围盒加留白，相邻包围盒不重叠；代表 A4 密度、字体和视觉参数符合基准 |
| AC-REQ-003-02 | V-AC-REQ-003-02 | service/repository security test | DB 用户姓名、`external_id` 与主部门生效；伪造请求字段不影响水印；无主部门按确认格式省略部门段 |
| AC-REQ-003-03 | V-AC-REQ-003-03 | fixed-clock unit test | 单次各页北京日期一致、格式严格为 `YYYY/MM/DD`、跨日期请求可变化 |
| AC-REQ-003-04 | V-AC-REQ-003-04 | unit + representative PDF smoke | 页数/MediaBox/rotation/关键文本保持；输出通过 F063 PDF validator；源 SHA256 不变 |

### REQ-004: 普通下载严格执行登录、租户与下载权限

作为知识空间管理者，我需要下载行为执行比预览更严格的权限校验，以便只读用户可以查看但不能取得文件副本。

#### 验收标准 Acceptance Criteria

- `AC-REQ-004-01`: WHEN 任意门户下载请求没有有效门户登录会话或有效 BiSheng 用户身份 THEN 门户 BFF 或 BiSheng SHALL 返回 401，且 SHALL NOT 开始读取 PDF 产物。
- `AC-REQ-004-02`: WHEN 普通下载请求包含 `space_id` 和 `file_id` THEN BiSheng SHALL 校验文件存在、文件属于该空间、当前租户一致且当前用户具有文件级 `download_file` 权限；任一校验失败 SHALL 返回 403 或 404。
- `AC-REQ-004-03`: WHEN 用户只有 `view_file` 而没有 `download_file` THEN 用户 SHALL 仍可按现有规则预览，但搜索/列表/详情 SHALL 不展示可用下载动作，直接调用下载 API SHALL 返回 403。
- `AC-REQ-004-04`: WHEN 请求跨租户、交换空间/文件 ID 或更换登录用户 THEN 系统 SHALL fail closed，不得仅依赖前端 `can_download` 或门户 BFF 的可见空间过滤作为最终授权。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-004-01 | V-AC-REQ-004-01 | BFF + BiSheng API test | 未登录、过期会话、无效上游 JWT 均 401 且 storage mock 未调用 |
| AC-REQ-004-02 | V-AC-REQ-004-02 | permission integration | 正常下载、错误空间、文件不存在、缺少 download_file、租户不一致矩阵 |
| AC-REQ-004-03 | V-AC-REQ-004-03 | frontend contract + API regression | `canDownload=false` 隐藏/禁用动作；预览成功；下载 403 |
| AC-REQ-004-04 | V-AC-REQ-004-04 | authorization regression | 跨租户、IDOR、BFF 参数篡改和换用户请求均拒绝 |

### REQ-005: 分享下载使用用户绑定的短期访问证明

作为分享文档的所有者，我需要分享下载同时遵守分享验证和当前登录用户身份，以便密码、邀请码、部门范围和禁止下载设置不能被绕过。

#### 验收标准 Acceptance Criteria

- `AC-REQ-005-01`: WHEN 用户通过公共或部门分享下载文件 THEN 系统 SHALL 要求有效登录；匿名用户 MAY 继续按现有规则查看公共分享的文件元数据和摘要，但 SHALL NOT 下载或获取预览正文。
- `AC-REQ-005-02`: WHEN 分享密码/邀请码和部门访问验证成功且 `allow_download=true` THEN BiSheng SHALL 签发不超过一小时且不晚于分享链接到期时间的短期下载授权；授权 SHALL 绑定用途、版本、当前用户、租户、分享令牌、空间和文件。
- `AC-REQ-005-03`: WHEN 执行分享下载 THEN BiSheng SHALL 验证授权签名、用途、用户、租户、目标和有效期，并重新读取分享链接检查启用状态、到期时间、`allow_download` 及部门范围；任一条件失效 SHALL 返回 403。
- `AC-REQ-005-04`: WHEN 门户保存分享访问结果 THEN 下载授权 SHALL 只保存在服务端分享会话，不得出现在浏览器 JSON、URL、页面存储或日志；分享会话 SHALL 使用 Redis 在门户 Worker 间共享，开发环境 MAY 使用内存回退。
- `AC-REQ-005-05`: WHEN 下载授权被篡改、跨用户/租户/分享/文件重放，或匿名验证后未以当前登录用户重新验证 THEN 系统 SHALL 拒绝下载；查看授权和下载授权 SHALL NOT 相互替代。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-005-01 | V-AC-REQ-005-01 | BFF integration + frontend flow | 匿名公共分享可查看元数据/摘要，但下载与预览正文 401；登录后可继续验证 |
| AC-REQ-005-02 | V-AC-REQ-005-02 | grant service unit | claims、domain-separated signature、TTL=min(1h, link expiry)、allow_download=false 不签发下载授权 |
| AC-REQ-005-03 | V-AC-REQ-005-03 | share integration | 链接撤销/到期/禁止下载/部门变化在旧授权有效期内仍即时阻断 |
| AC-REQ-005-04 | V-AC-REQ-005-04 | BFF store + response security test | Redis 跨实例读取；公开响应、URL、日志不含 grant；生产无 Redis 启动失败保持现有规则 |
| AC-REQ-005-05 | V-AC-REQ-005-05 | negative security matrix | tamper、cross-user、cross-tenant、cross-file、wrong-purpose、expired、anonymous-to-login replay 全部拒绝 |

### REQ-006: 同步生成具有明确的资源和生命周期边界

作为门户用户和运维人员，我需要下载请求同步返回结果且资源消耗有界，以便用户获得明确反馈，服务不会因大文件或重复点击失控。

#### 验收标准 Acceptance Criteria

- `AC-REQ-006-01`: WHEN 用户点击下载 THEN 当前请求 SHALL 等待水印 PDF 准备完成后直接开始下载；按钮 SHALL 展示 loading 并阻止同一按钮重复提交，成功或失败后恢复。
- `AC-REQ-006-02`: WHEN 下载请求需要等待或生成统一 PDF THEN PDF 就绪阶段默认硬限时 SHALL 为 300 秒；WHEN 有效 PDF 就绪并进入个人水印、读取和输出校验阶段 THEN 水印阶段默认硬限时 SHALL 为 60 秒；文件响应传输时间不计入两个生成限时，任一阶段超时 SHALL 返回 504 且不得记录成功下载。
- `AC-REQ-006-03`: WHEN 请求成功、生成异常、超时或客户端断开 THEN 系统 SHALL 删除该请求的隔离临时目录和其中全部文件；个人水印文件 SHALL NOT 上传 MinIO 或留作缓存。
- `AC-REQ-006-04`: WHEN 单个 BiSheng API 进程处理按需 PDF 与个人水印请求 THEN 默认最大准备并发 SHALL 为 2，且同一用户同一时刻 SHALL 最多有一个在途下载；容量已满或同用户重复请求 SHALL 返回 429，同文件生成 SHALL 使用跨 Worker ownership lock 协调，不得创建无界后台任务。
- `AC-REQ-006-05`: WHEN 门户 BFF 代理下载 THEN BFF SHALL 使用仅对下载请求生效、默认约 370 秒的上游超时并流式转发响应；BFF SHALL NOT 完整缓冲 PDF，断连时 SHALL 主动关闭上游响应。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-006-01 | V-AC-REQ-006-01 | frontend unit/contract | loading、disabled、成功下载、错误恢复、Blob URL revoke |
| AC-REQ-006-02 | V-AC-REQ-006-02 | deterministic timeout test | PDF 就绪 300 秒与水印 60 秒分阶段边界分别返回 504；短测试时钟；无成功事件 |
| AC-REQ-006-03 | V-AC-REQ-006-03 | lifecycle test | success/error/timeout/disconnect 后临时目录不存在，MinIO 仅发生读取 |
| AC-REQ-006-04 | V-AC-REQ-006-04 | concurrency integration | 第 3 个进程内请求和同用户重复请求 429；同文件 single-flight；两类锁 token 所有权释放和 TTL 恢复 |
| AC-REQ-006-05 | V-AC-REQ-006-05 | BFF streaming/client test | 下载专用 timeout=370；chunked 转发；取消请求触发 upstream `aclose()`；全局 30 秒配置不变 |

### REQ-007: 下载 API、错误与遥测口径统一

作为门户运营和客户端开发者，我需要下载接口具有稳定契约和单一成功事件，以便页面错误可解释、统计不重复且敏感信息不泄漏。

#### 验收标准 Acceptance Criteria

- `AC-REQ-007-01`: WHEN 下载成功 THEN BiSheng 门户专用接口、BiSheng 收口后的单文件接口和门户 BFF SHALL 返回 PDF 二进制、兼容中文文件名的 `Content-Disposition`、`Cache-Control: private, no-store` 和 `X-Content-Type-Options: nosniff`，不得返回 MinIO 对象名或签名 URL。
- `AC-REQ-007-02`: WHEN 下载失败 THEN BFF 和 BiSheng Client SHALL 保留 401/403/404/409/429/503/504 语义并向前端返回可展示的中文错误；内部异常 SHALL 使用通用 500 文案，不得暴露堆栈、对象名、临时路径、授权或完整水印身份。
- `AC-REQ-007-03`: WHEN 水印 PDF 已成功生成且响应首个文件块已成功发送 THEN 系统 SHALL 在 BiSheng 记录恰好一次 `portal_document_download` 成功事件；生成失败、响应开始前断连或权限失败 SHALL NOT 记录成功，前端 SHALL 不再单独上报成功下载。
- `AC-REQ-007-04`: WHEN 记录下载事件 THEN `entry_point` SHALL 使用服务端允许集合 `search`、`knowledge_list`、`detail`、`home_recommendation`、`favorite`、`share`、`expert_qa`、`qa_citation`、`bisheng_knowledge_list`、`bisheng_preview`、`bisheng_favorite`、`bisheng_version_history` 或 `other`，非法客户端值 SHALL 归一为 `other`。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-007-01 | V-AC-REQ-007-01 | endpoint/BFF integration | 二进制 body、安全响应头、中文文件名；响应和日志无对象名/URL |
| AC-REQ-007-02 | V-AC-REQ-007-02 | error mapping matrix + log capture | 各状态码与中文提示；500 脱敏；grant、临时路径、身份不进入日志 |
| AC-REQ-007-03 | V-AC-REQ-007-03 | streaming telemetry test | 首块后恰好一次；生成失败/首块前断连为零；前端无 `download-event` 调用 |
| AC-REQ-007-04 | V-AC-REQ-007-04 | schema/service test | 13 个合法入口保留；未知、空值归一为 other |

### REQ-008: 保持既有架构和部署兼容

作为系统维护者，我需要本功能建立在现有运行环境和 F063 能力上，以便上线不要求额外 Worker、镜像或数据结构变更。

#### 验收标准 Acceptance Criteria

- `AC-REQ-008-01`: WHEN 实现本 Feature THEN 系统 SHALL 复用 PyMuPDF、现有中文字体、MinIO、Redis 和 F063 accessor，不新增 Python/Node 运行时依赖或 lockfile 变更。
- `AC-REQ-008-02`: WHEN 部署本 Feature THEN `docker-compose.yml`、`src/backend/base.Dockerfile`、Celery 队列、Celery Worker 和数据库 schema SHALL 保持不变；按需 PDF 与水印逻辑在现有 BiSheng API 请求内同步执行，并与现有 PDF Worker 复用同一转换核心。
- `AC-REQ-008-03`: WHEN 实施旧单文件接口收口 THEN 该 endpoint 的 JSON URL 契约 SHALL 明确替换为水印 PDF 二进制契约，仓库内全部调用方 SHALL 同批迁移；既有 `batch-download`、开放接口和非知识文档下载契约 SHALL 保持不变。
- `AC-REQ-008-04`: WHEN 规格进入实现前 THEN v2.6.0 release contract SHALL 登记 F064 依赖 F063；按需生成 MAY 通过 F063 既有 Repository 更新 `KnowledgeFilePdfArtifact`，但 SHALL NOT 新增表、改变 schema 或建立第二套产物状态；实现 SHALL 避让当前工作树中的无关改动。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-008-01 | V-AC-REQ-008-01 | dependency/diff review | `pyproject.toml`、`uv.lock`、frontend lockfile 无依赖变化；字体 smoke 通过 |
| AC-REQ-008-02 | V-AC-REQ-008-02 | deployment contract + diff review | Compose/Dockerfile/entrypoint/Celery/迁移目录无本 Feature 改动 |
| AC-REQ-008-03 | V-AC-REQ-008-03 | contract migration + regression | 旧单文件 route 只返回 PDF；仓库内无 JSON URL 调用；批量 ZIP、开放接口和非知识下载保持 |
| AC-REQ-008-04 | V-AC-REQ-008-04 | contract review + git diff | release-contract 依赖登记；只复用 F063 模型/Repository；无 schema/无关脏文件覆盖 |

### REQ-009: 门户知识工作台下线不支持的批量与文件夹下载入口

作为门户用户，我需要文件和文件夹多选后的批量操作只展示仍受支持的动作，以免误以为门户可以生成批量带水印 ZIP。

#### 验收标准 Acceptance Criteria

- `AC-REQ-009-01`: WHEN 用户在 `/workspace/knowledge-portal` 多选文件、文件夹或二者混合 THEN 批量操作菜单 SHALL NOT 展示“批量下载”，且该页面 SHALL NOT 通过多选操作调用 `batchDownloadApi`。
- `AC-REQ-009-02`: WHEN 所选内容仍满足批量重试、批量删除或其他既有批量动作条件 THEN 这些动作 SHALL 按原权限继续展示和执行；WHEN 没有任何剩余可用批量动作 THEN 系统 SHALL NOT 展示空的批量操作菜单。
- `AC-REQ-009-03`: WHEN 用户进入非门户的 BiSheng 知识空间详情页或客户端直接调用既有批量下载 API THEN 现有批量下载入口、请求和响应契约 SHALL 保持不变。
- `AC-REQ-009-04`: WHEN 用户浏览 `/workspace/knowledge-portal` 的文件夹卡片、表格行或更多菜单 THEN 系统 SHALL NOT 展示文件夹下载动作；单文件下载动作 SHALL 保留并使用带水印 PDF 契约。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-009-01 | V-AC-REQ-009-01 | frontend behavior + source contract | 文件/文件夹/混合多选无批量下载项；门户 host 不接线 `batchDownloadApi` |
| AC-REQ-009-02 | V-AC-REQ-009-02 | frontend permission regression | 管理员批量重试/删除保持；只具下载权限时无空菜单 |
| AC-REQ-009-03 | V-AC-REQ-009-03 | client API + source regression | `batchDownloadApi`、知识空间详情接线和后端 endpoint 均保留 |
| AC-REQ-009-04 | V-AC-REQ-009-04 | focused behavior regression | 门户文件夹无行级下载；单文件仍有下载且进入水印 helper；共享组件非门户默认不变 |

### REQ-010: BiSheng 门户单文件下载入口统一与旧契约收口

作为首钢门户用户，我需要 BiSheng 门户工作台内所有单文件下载入口与独立门户一致，以便任何页面都只能取得当前用户的带水印 PDF。

#### 验收标准 Acceptance Criteria

- `AC-REQ-010-01`: WHEN 登录用户在 `/workspace/knowledge-portal` 的文件行、原地预览或收藏原地预览点击下载，或在 `/workspace/knowledge/file/{file_id}` 点击下载 THEN 系统 SHALL 使用文件实际所属 `space_id` 和 `file_id` 请求水印 PDF 二进制接口。
- `AC-REQ-010-02`: WHEN 用户在版本历史点击下载 THEN 系统 SHALL 使用该版本对应的 `knowledge_file_id`；IF 该历史版本的统一 PDF 产物不可用但源文件仍可读取和转换 THEN 系统 SHALL 按 REQ-002 同步生成、持久化并继续个人水印下载；最终失败 SHALL 提示用户且不得回退无水印原文件。
- `AC-REQ-010-03`: WHEN 任意仓库内调用方请求旧 `/knowledge/space/{space_id}/files/{file_id}/download` 路径 THEN 响应 SHALL 为带水印 `application/pdf` 或稳定错误，SHALL NOT 返回包含 `original_url`、`preview_url` 的 JSON。
- `AC-REQ-010-04`: WHEN BiSheng Client 下载正在处理 THEN 触发按钮 SHALL 防止重复提交并在成功或失败后恢复；成功文件名 SHALL 使用响应 `Content-Disposition` 或安全的“原文件名 stem + `.pdf`”回退，Blob URL SHALL 在触发后释放。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-010-01 | V-AC-REQ-010-01 | frontend behavior + API contract | 文件行、门户预览、收藏源空间、独立预览均调用 Blob helper，并携带对应 entry point |
| AC-REQ-010-02 | V-AC-REQ-010-02 | version behavior + backend artifact test | 使用版本 `knowledge_file_id`；缺产物按需生成；最终失败可展示且无 URL fallback |
| AC-REQ-010-03 | V-AC-REQ-010-03 | endpoint integration + source scan | 旧路径返回 PDF/真实状态；body/header 无原始 URL；仓库无旧 DTO 解析 |
| AC-REQ-010-04 | V-AC-REQ-010-04 | frontend unit/behavior | loading/disabled、Blob 错误解析、中文文件名、fallback、URL revoke 和错误恢复 |

### REQ-011: 知识预览显示当前用户前端水印并限制匿名正文

作为知识文档管理方，我需要登录用户在独立门户和 BiSheng 的全部知识预览正文上看到本人身份水印，并阻断匿名预览正文，以便降低截图和屏幕转发时无法追溯的风险。

#### 验收标准 Acceptance Criteria

- `AC-REQ-011-01`: WHEN 独立门户登录用户打开详情预览，或从搜索、列表等入口打开复用详情页的预览弹窗 THEN PDF、DOCX、表格、Markdown、HTML、文本、图片和 chunks 等已支持知识预览 SHALL 显示平铺、倾斜、半透明的全尺寸 SVG 矢量水印。
- `AC-REQ-011-02`: WHEN BiSheng 登录用户打开知识文件独立预览、门户原地预览、收藏原地预览、版本对比或知识引用预览 THEN 普通知识文件和富媒体知识预览 SHALL 显示同一口径全尺寸 SVG 矢量水印；聊天上传、SOP、Artifact 和非知识预览 SHALL 保持不变。
- `AC-REQ-011-03`: WHEN 水印展示 THEN 每个平铺单元 SHALL 与下载使用相同两行口径：第一行为“用户主部门-姓名--用户账号-YYYY/MM/DD”，第二行为“首钢股份内部资料，严禁外传，违者必究”；WHEN 用户没有主部门 THEN 第一行 SHALL 为“姓名--用户账号-YYYY/MM/DD”。Portal 与 BiSheng SHALL 从当前认证用户契约取得独立主部门、姓名和 `external_id`，账号为空时 MAY 回退当前登录账号；时间在单次预览组件挂载时按 `Asia/Shanghai` 固定，新开预览重新取值；覆盖层 SHALL `pointer-events:none`、`aria-hidden=true` 且不可选择文本。
- `AC-REQ-011-04`: WHEN 独立门户用户未登录但已通过分享访问校验 THEN 文件详情元数据和摘要 MAY 显示，前端 SHALL 不请求 `/preview`、`/preview/content` 或 `/chunks` 并展示“登录后预览”；直接调用三个接口 SHALL 返回 401，且 SHALL NOT 请求 BiSheng 预览正文。
- `AC-REQ-011-05`: WHEN 前端水印启用 THEN 既有预览源、解析、渲染、降级和下载契约 SHALL 保持不变；前端 SVG 水印仅提供可见追溯提示，系统 SHALL NOT 宣称其能够阻止开发者工具、禁用样式、删除 DOM、截图裁剪或直接保存已授权响应。
- `AC-REQ-011-06`: WHEN 任意受支持知识文档显示 CSS 水印 THEN 水印 SHALL 仅覆盖实际文档正文表面；PDF SHALL 按单页边界裁剪，DOCX、Markdown、HTML、文本、表格、图片和 chunks SHALL 按各自白色正文或媒体内容边界裁剪；水印 SHALL NOT 出现在文档外侧灰色留白、滚动视口空白或工具栏区域。首页、搜索/列表弹窗和知识库文件预览 SHALL 保持同一行为。
- `AC-REQ-011-07`: WHEN 预览水印渲染、字体就绪或正文 surface 尺寸变化 THEN Portal 与 BiSheng SHALL 以下载 PDF 为视觉基准，采用黑体、等效 `16px` 字号、绝对倾角 `35°`、最终视觉方向左下向右上 `/`、透明度 `0.31` 和 `#737373`；浏览器 SHALL 测量最长一行并以旋转后两行包围盒加等效安全留白计算坐标步长，横向与纵向安全留白 SHALL 分别为 `48px` 和 `36px`，最小步长 SHALL 分别为 `240px` 和 `180px`；文字更长时自动扩大且字号不变。奇偶行 SHALL 水平错位 50%，相邻水印不得重叠。
- `AC-REQ-011-08`: WHEN Portal 或 BiSheng 在任意正文 surface 绘制预览水印 THEN 覆盖层 SHALL 使用与 surface 等宽高的 SVG，根据实际宽高逐行逐列生成独立 `<g>/<text>` 水印；SHALL NOT 使用 `<pattern>`、背景切片或其他虚拟 tile 裁剪文字。除与真实正文边缘相交的水印外，正文内部每个水印的两行文字 SHALL 完整可见；surface 首次挂载、宽高变化或字体就绪后 SHALL 重新计算坐标。为优先保证与 PDF 一致的视觉完整性，水印节点数量 MAY 随 surface 面积增长。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-011-01 | V-AC-REQ-011-01 | Portal frontend unit/source contract + build | 详情页唯一预览层覆盖全部渲染模式；搜索/列表弹窗继续复用详情页；水印层存在 |
| AC-REQ-011-02 | V-AC-REQ-011-02 | BiSheng client component/usage tests + build | `FilePreview` 与富媒体预览覆盖五类知识入口；非知识预览无接线 |
| AC-REQ-011-03 | V-AC-REQ-011-03 | user contract + deterministic formatter/component tests + stylesheet audit | 两端主部门/姓名/账号字段、无部门与账号回退、Asia/Shanghai 固定日期、两行文本、旧文案消失、`pointer-events:none`、`aria-hidden`、不可选择 |
| AC-REQ-011-04 | V-AC-REQ-011-04 | Portal BFF integration + frontend behavior | 匿名详情/摘要可用；三个正文接口 401 且无上游调用；前端无正文请求并显示登录提示 |
| AC-REQ-011-05 | V-AC-REQ-011-05 | regression + scope source scan + manual security review | viewer/download 回归通过；非知识入口无改动；文档明确 CSS 绕过边界 |
| AC-REQ-011-06 | V-AC-REQ-011-06 | component/source contract + production build + visual regression | 水印 provider 只固定身份/时间；overlay 下沉到各正文 surface；PDF 每页裁剪；两端外层 viewer 不再直接渲染 overlay |
| AC-REQ-011-07 | V-AC-REQ-011-07 | pure layout/component/SVG source tests + stylesheet audit + visual comparison | 两端普通/长文本步长随测量宽度增长且不小于包围盒加留白；独立 SVG 水印奇偶行错位、surface 任意尺寸覆盖且与 PDF 等效 |
| AC-REQ-011-08 | V-AC-REQ-011-08 | pure position/component tests + ResizeObserver regression + browser screenshot comparison | 两端按 surface 宽高生成独立坐标；无 `<pattern>`；内部水印完整、只在真实正文边缘裁剪；resize 后重新铺设 |

### REQ-012: 登录态问答正文显示当前用户前端水印

作为问答内容管理方，我需要登录用户在 Portal 与 BiSheng 的全部交互式问答正文中持续看到本人身份水印，以便问答内容被截图或转发时保留可见追溯信息。

#### 验收标准 Acceptance Criteria

- `AC-REQ-012-01`: WHEN Portal 登录用户进入智能写作模板选择/初始页且尚未进入会话态 THEN 页面 SHALL NOT 显示水印；WHEN 智能写作进入现有 `hasConversation` 会话态，或 Portal 智能问答查看空会话、历史消息、实时生成、加载或错误重试状态 THEN 仅对话正文 surface SHALL 显示当前用户水印；顶部标签、模板列表、历史侧栏、输入框、弹窗和引用详情 SHALL NOT 显示水印。
- `AC-REQ-012-02`: WHEN Portal 登录用户打开 workflow Agent THEN BiSheng 认证 iframe 子页面 SHALL 在其对话正文显示一层水印，Portal 宿主 SHALL NOT 再叠加；WHEN 登录用户打开第三方 URL 智能应用 iframe THEN Portal 宿主 SHALL 在 iframe 可见区域叠加一层当前用户水印，且 SHALL NOT 访问或修改跨域 iframe DOM。
- `AC-REQ-012-03`: WHEN BiSheng 登录用户进入主智能问答、智能应用、Agent、workflow、assistant 或认证独立对话 THEN 空会话与消息正文 surface SHALL 显示当前用户水印；输入区、对话标题栏、历史侧栏和引用侧栏 SHALL NOT 显示水印。
- `AC-REQ-012-04`: WHEN BiSheng 登录用户进入知识空间问答、单文档问答、Portal 知识工作台 AI 对话、订阅文章或频道问答 THEN 欢迎空状态、加载状态和消息正文 SHALL 显示当前用户水印；对应标题、输入框、历史抽屉和引用面板 SHALL 保持无水印。
- `AC-REQ-012-05`: WHEN 问答水印展示 THEN 文案、身份回退、`Asia/Shanghai` 日期、黑体、`16px`、最终 `/` 方向、`#737373`、透明度 `0.31`、间距、自适应长文字和全尺寸 SVG 逐坐标规则 SHALL 复用 REQ-011；一次 surface 挂载 SHALL 固定同一身份和日期。
- `AC-REQ-012-06`: WHEN 对话消息滚动、流式内容增长、视口横竖屏切换或 surface resize THEN 水印 SHALL 固定覆盖当前可见正文区域并重新铺设，节点数量 SHALL 只由可见 surface 面积决定，SHALL NOT 随历史消息总高度线性增长。
- `AC-REQ-012-07`: WHEN 用户滚动、选择/复制消息、点击链接或引用、发送/停止生成、操作欢迎页按钮或与第三方 iframe 交互 THEN 水印 SHALL NOT 阻断鼠标、触控、键盘或辅助技术；覆盖层 SHALL `pointer-events:none`、`user-select:none`、`aria-hidden=true`。
- `AC-REQ-012-08`: WHEN 对话为匿名访客、未登录 Portal 智能问答、公开/只读分享或其他无当前登录用户身份的页面 THEN 系统 SHALL NOT 显示用户水印；问答接口、匿名可用能力及分享行为 SHALL 保持不变。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-012-01 | V-AC-REQ-012-01 | Portal component/source contract + browser regression | 智能写作模板初始页不渲染 overlay；`hasConversation` 会话态及智能问答正文显式覆盖空/历史/生成/错误状态，composer/sidebar/reference 无覆盖 |
| AC-REQ-012-02 | V-AC-REQ-012-02 | iframe responsibility source tests + browser regression | workflow iframe 仅子页面一层；URL iframe 仅宿主一层；跨域内容可操作 |
| AC-REQ-012-03 | V-AC-REQ-012-03 | BiSheng component/route usage tests | `/c`、`/app`、workflow/assistant、认证 standalone 的正文/空状态启用；标题/输入/侧栏排除 |
| AC-REQ-012-04 | V-AC-REQ-012-04 | shared panel component tests + entry source scan | `KnowledgeAiPanel`、`AiAssistantPanel` 及全部登录态调用入口覆盖欢迎/加载/消息 |
| AC-REQ-012-05 | V-AC-REQ-012-05 | shared formatter/layout tests + stylesheet/source audit | 问答与预览共享身份/日期/layout/position，透明度单一来源为 `0.31` |
| AC-REQ-012-06 | V-AC-REQ-012-06 | ResizeObserver/component regression + browser long-chat test | resize 重铺；滚动时 overlay 固定；节点数不依赖消息数量 |
| AC-REQ-012-07 | V-AC-REQ-012-07 | accessibility/source contract + interaction smoke | pointer/user-select/aria 契约；滚动、复制、链接、发送、停止及 iframe 点击正常 |
| AC-REQ-012-08 | V-AC-REQ-012-08 | guest/share negative tests + route source scan | 无用户、guest、share/readOnly 不渲染 overlay；接口和页面行为不变 |

## Bugfix 记录：智能写作展示时机与全端样式一致性

- Current behavior:
  - Portal `SmartQaWorkspace.qaContent` 无条件挂载 `PreviewWatermarkOverlay`，导致智能写作模板选择/初始页在尚未进入对话时也显示水印。
  - Portal 与 BiSheng 前端、PDF worker 解析默认值和既有测试均使用透明度 `0.11`，但 `PdfWatermarkSpec` 当前默认透明度为 `0.31`，动态下载 PDF 与页面水印视觉不一致。
- Expected behavior:
  - 智能写作仅在现有 `hasConversation` 为真时显示水印；模板选择/初始页不显示。
  - 下载 PDF、Portal 预览/问答和 BiSheng 预览/问答统一使用：两行文案、`YYYY/MM/DD`、等效黑体、`12pt = 16px`、最终 `/` 方向、等效 `#737373`、透明度 `0.11`、等效步长与留白。
- Impact:
  - 只改变智能写作模板初始页的水印可见性，以及后续动态生成下载 PDF 的透明度；不改变接口、权限、身份来源、文案、日期、布局、对象存储或历史数据。
- Reproduction:
  - 登录 Portal 打开 `/apps` 的智能写作模板页，在未发送消息时可看到覆盖模板卡片和背景的水印。
  - 构造默认 `PdfWatermarkSpec`，实际得到 `opacity=0.31`，与现有前端 layout/worker/test 的 `0.11` 不一致。

## 需求变更记录：全端水印透明度调整为 0.31

- Current behavior:
  - 上一轮为消除 PDF 与前端漂移，将下载 PDF、Portal 和 BiSheng 的透明度统一为 `0.11`。
- Expected behavior:
  - 下载 PDF、PDF worker、Portal 预览/问答和 BiSheng 预览/问答 SHALL 全部统一使用透明度 `0.31`。
  - 智能写作模板初始页仍不显示水印，进入会话后才显示；其他字号、颜色、方向、密度、文案和日期规则保持不变。
- Impact:
  - 新生成 PDF 和所有前端水印视觉加深；历史已生成的个人下载文件不回写。
  - 不改变接口、权限、身份来源、数据结构、部署配置或依赖。

## 非功能需求 Non-Functional Requirements

- `NFR-001 Security`: 下载身份必须来源于 BiSheng 当前认证上下文；下载授权和存储对象标识不对浏览器暴露。
- `NFR-002 Reliability`: 所有个人水印临时文件都有请求级所有者，并在全部终止路径清理。
- `NFR-003 Performance`: 默认每进程同时准备 2 个、每用户 1 个；同文件跨 Worker 只生成一次；PDF 就绪 300 秒、水印 60 秒为客户端可观察分阶段硬限时。
- `NFR-004 Privacy`: 日志和遥测只记录必要用户/文件 ID，不记录完整水印文本、签名授权或临时文件内容。
- `NFR-005 Preview visual priority`: 预览水印 SHALL 优先保证正文内部文字完整和与 PDF 的逐坐标布局一致；水印 DOM 数量 MAY 随正文面积增长，性能不作为本次缺陷修复的阻断验收项。
- `NFR-005 Compatibility`: 支持 MySQL/DM8 现有部署；本 Feature 不新增数据库访问结构或迁移。
- `NFR-006 Accessibility`: 下载按钮在 pending 状态提供 `disabled`/`aria-busy`，失败后有可读错误信息；预览水印不得拦截鼠标、触控、键盘或辅助技术，匿名预览提示必须可读。
- `NFR-007 Scope isolation`: 门户批量与文件夹入口下线必须通过显式 host 能力控制实现，共享组件的非门户文件夹默认行为保持不变；预览水印只接入知识预览基础层。
- `NFR-008 Privacy`: 前端水印只使用当前认证上下文已有的主部门、姓名与用户账号，不新增持久化、遥测、请求参数或日志记录。
- `NFR-009 Chat scope isolation`: 问答公共组件的水印能力 SHALL 默认关闭并由登录态交互入口显式启用；guest、share/readOnly 和非对话区域不得因公共组件复用而被误覆盖。

## 澄清记录 Clarifications

### Session 2026-07-21

- Q: 下载是否保留原始文件格式？ -> A: 否，门户所有知识文档下载只输出去除原后缀后的 `.pdf`。
- Q: 哪些门户入口纳入？ -> A: 搜索、列表、详情、首页经详情、分享、专家问答关联文档、QA/聊天引用全部统一；缺少知识文件二元标识的外部附件不纳入。
- Q: 公共分享是否允许匿名下载？ -> A: 不允许，分享下载必须登录并使用当前登录用户水印。
- Q: 分享下载如何判断？ -> A: 必须完成有效分享访问验证且 `allow_download=true`，并在下载时重新检查链接状态。
- Q: 历史文件没有 PDF 产物怎么办？ -> A: 最新确认改为下载时同步生成并持久化；补齐脚本仍不属于本 Feature，最终失败不回退无水印原文件。
- Q: 水印内容和样式？ -> A: 每页倾斜、平铺、半透明，三行显示“用户主部门-姓名”、北京日期 `YYYY-MM-DD` 和“首钢集团内部资料”；无主部门时第一行只显示姓名。
- Q: 生成方式？ -> A: 统一 PDF 缺失或不可用时同步生成并保存，PDF 就绪阶段最多 300 秒；每次点击仍实时生成且不保存个人水印副本，水印阶段最多 60 秒。
- Q: 是否新增 Celery 或部署服务？ -> A: 否，不新增队列/Worker，不修改 Compose 和基础镜像。
- Q: 门户是否支持多文件或文件夹批量水印下载？ -> A: 不支持，取消该规划，不生成带水印 ZIP。
- Q: 哪个现有入口下线？ -> A: 仅 `/workspace/knowledge-portal` 文件/文件夹多选后的“批量下载”；知识空间详情页和后端接口保留。
- Q: 其他批量操作如何处理？ -> A: 批量重试、批量删除等继续按现有权限展示；没有剩余动作时不显示空菜单。
- Q: 单个文件夹下载是否下线？ -> A: 初始决定保留；本次范围更新后改为下线 `/workspace/knowledge-portal` 文件夹行级下载，不实现水印 ZIP。
- Q: BiSheng 端包含哪些下载入口？ -> A: 首钢门户相关的文件行、原地预览、收藏、独立文件预览和版本历史；不扩展管理端及非知识文档下载。
- Q: 旧 URL 下载 endpoint 是否保留？ -> A: 不保留原 JSON URL 行为；收口为水印 PDF 二进制契约并同步迁移仓库内调用方，阻断 `original_url/preview_url` 绕过。
- Q: 预览水印先采用什么方式？ -> A: 通过前端 CSS 平铺覆盖层实现，不改写 PDF/图片/富媒体字节，不新增依赖。
- Q: 哪些预览入口纳入？ -> A: 独立门户详情及复用详情页的搜索/列表弹窗；BiSheng 知识文件独立预览、门户原地预览、收藏、版本对比和知识引用预览。聊天上传、SOP、Artifact 和非知识预览不纳入。
- Q: 预览与下载水印内容？ -> A: 统一为三行：“用户主部门-姓名”、北京日期 `YYYY-MM-DD`、“首钢集团内部资料”；无主部门时第一行只显示姓名；不显示字段前缀、工号/账号和时分秒。
- Q: 匿名分享预览如何处理？ -> A: 匿名仍可看已授权文件元数据和摘要，但不能获取正文；BFF 三个预览正文接口返回 401，前端显示“登录后预览”且不发请求。
- Q: 哪些产物异常触发下载时生成？ -> A: 无记录、WAITING/PROCESSING/FAILED、引用缺失、源快照过期、对象丢失、PDF 损坏、大小无效和 SHA 不一致均纳入；最终失败才由前端提示。
- Q: 同文件并发如何处理？ -> A: 不同用户共享一次统一 PDF 生成和持久化结果，个人水印仍分别生成；不新增 Celery 队列或服务。

### Session 2026-07-22

- Q: 下载与预览的最终水印文案是什么？ -> A: 固定两行；第一行为“主部门-姓名--用户账号-YYYY-MM-DD”，第二行为“首钢股份内部资料，严禁外传，违者必究”，双连字符按字面保留。
- Q: 用户账号取什么字段？ -> A: 使用系统登录账号字段 `external_id`；遗留空值回退当前认证上下文账号，浏览器不得提交或覆盖。
- Q: 预览密度和样式以哪端为准？ -> A: 以当前下载 PDF 及用户提供截图为基准；两端预览统一黑体、等效字号、角度、透明度、颜色和间距，并根据正文 surface 动态铺设。
- Q: 无主部门如何拼接？ -> A: 省略部门段及行首分隔符，输出“姓名--用户账号-YYYY-MM-DD”。
- Q: 水印重叠如何处理？ -> A: 保持两行文案、黑体、字号和 `-35°`，透明度当前为 `0.31`；PDF 与预览都按最长一行的实际旋转包围盒自动扩大间距，当前最小等效单元为 `240pt × 180pt` / `320px × 240px`，奇偶行错位 50%。
- Q: 预览如何避免长文档产生大量节点？ -> A: Portal 与 BiSheng 都改为单个内联 SVG pattern 自动平铺，不再用 `ResizeObserver` 根据正文高度增删 tile。
- Q: 无重叠方案落地后是否继续提高密度？ -> A: 是，采用轻度增密档：PDF 最小单元调整为 `288pt × 200pt`，预览等效调整为 `384px × 267px`，代表 A4 目标约 8 至 10 组；长文案仍由旋转包围盒公式自动扩大单元，不以重叠换取密度。
- Q: 下载 PDF 仍显稀疏时采用哪一档密度？ -> A: 采用中等增密档并同时同步两端预览：PDF 最小单元调整为 `240pt × 180pt`，预览等效调整为 `320px × 240px`，代表 A4 目标约 12 至 14 组；留白和长文案扩距规则保持不变。

### Session 2026-07-23

- Q: 当前相邻水印块间距仍偏宽时如何调整？ -> A: Portal、BiSheng 和下载 PDF 同步将普通水印的横纵最小步长及旋转包围盒安全留白缩短约 25%；PDF 使用 `180pt × 135pt` 最小步长和 `36pt/27pt` 留白，预览使用等效 `240px × 180px` 最小单元和 `48px/36px` 留白。
- Q: 长部门或长账号与固定密度冲突时如何处理？ -> A: 优先保证文字完整和不重叠；保持字号，由现有旋转包围盒算法自适应扩大步长，因此极端长文字不要求达到普通文字的密度。
- Q: 日期格式如何统一？ -> A: 下载与两端预览均使用 `Asia/Shanghai` 日期，格式严格为 `YYYY/MM/DD`。
- Q: 预览与下载方向不一致时以哪种方向为准？ -> A: 以最终视觉方向为准，三端均为左下向右上 `/`；SVG 与 PyMuPDF 可使用不同符号的旋转参数。
- Q: SVG pattern 错位行被 tile 边界裁剪时采用哪种修复？ -> A: 不考虑性能，Portal 与 BiSheng 均改为全尺寸 SVG 逐坐标绘制独立水印组，布局方式对齐 PDF；允许节点数随正文面积增长，不再使用 SVG pattern。
- Q: 问答水印覆盖哪些入口？ -> A: Portal 与 BiSheng 全部登录态交互式问答，包括智能问答/写作、智能应用、Agent、workflow/assistant、知识空间、单文档及订阅文章/频道问答；第三方 URL iframe 由 Portal 宿主覆盖。匿名访客、公开/只读分享和非聊天专家问答不纳入。
- Q: 问答水印覆盖什么区域？ -> A: 只覆盖当前可见对话正文及其空/加载/生成/错误状态，不覆盖顶部栏、系统导航、历史侧栏、输入框、弹窗或引用详情侧栏。
- Q: 问答水印如何滚动及采用什么样式？ -> A: 固定覆盖可见正文，消息滚动时不随内容滚走；复用知识预览的两行身份、日期、方向、密度和实际 `0.31` 透明度。
- Q: 最终统一透明度是多少？ -> A: 按最新确认，下载 PDF、PDF worker、Portal 预览/问答和 BiSheng 预览/问答统一为 `0.31`；该决定覆盖此前 `0.11` 的视觉基准。

## 假设 Assumptions

- F063 已完成部署，其转换器、校验器、模型和 Repository 可作为下载按需生成的唯一实现基础。
- 当前普通知识文件上传上限约 50 MB，可作为浏览器 Blob 下载和性能验收的代表上限；若后续放宽上限，需要重新评估前端内存、300 秒 PDF 就绪和 60 秒水印限时。
- 主部门以 `user_department.is_primary=1` 的关联部门为准；无主部门时不推断附属部门，不显示部门占位文字。
- 登录账号以 `user.external_id` 为事实源；仅对遗留空值使用当前认证上下文已有账号回退，不新增账号查询或客户端输入。
- 生产门户已经要求 Redis 可用；新分享下载会话复用该 Redis，不新增中间件。

## 风险 Risks

- 实时水印会增加 BiSheng API 进程 CPU 和临时磁盘负载；并发上限、用户锁、子进程硬终止和临时目录清理是上线必要条件。
- 浏览器 Fetch/Blob 会短暂占用接近 PDF 大小的内存；当前 50 MB 上限可接受，但必须执行代表性大文件验证。
- 将分享访问会话从进程内存迁移到 Redis 后，切换时旧 `portal_share_access` cookie 可能需要重新验证分享密码或邀请码；不影响分享链接本身。
- HTTP 服务无法证明浏览器已经写入本地磁盘，因此成功遥测定义为“PDF 已生成且首个响应文件块已成功发送”，不得解读为客户端完整落盘。
- 只具备下载权限的门户用户在取消批量下载后可能没有任何可用批量动作；此时隐藏整个批量操作菜单是已确认的产品行为。
- 旧单文件接口从 JSON 改为 PDF 是不向后兼容的契约变化；必须在同一发布单元迁移仓库内调用方并对外公告潜在调用方。
- 历史版本下载会在对应 `knowledge_file_id` 上按需生成统一 PDF；源文件丢失、格式不支持或转换失败时仍会最终失败并提示用户。
- 当前仓库存在与本 Feature 无关的未提交改动；实现和验证必须按文件避让并在最终 diff 中证明未覆盖。
- CSS 水印可被熟悉浏览器工具的用户隐藏，也不能阻止截图裁剪或已授权资源保存；本阶段将其定位为可见追溯和安全提醒，不作为内容防泄漏强控制，下载 PDF 的服务端水印保持不变。
- 新第一行比旧水印更长，在窄页面或超长部门/账号下可能与相邻 tile 交叠；实施必须使用长字段代表样本同时检查 PDF 和预览，若调整间距必须三端同步，不能单独降低某一端密度。
- 全尺寸 SVG 会按正文面积生成独立水印节点，超长正文和频繁 resize 会增加浏览器 DOM、布局与重绘成本；这是为保证文字完整和视觉对齐而明确接受的取舍。
- Portal workflow iframe 与 BiSheng 认证子页面同时具备渲染能力，若宿主重复覆盖会产生双层水印；实现必须按入口保持唯一责任。
- BiSheng 公共消息组件同时服务登录、guest 和 share/readOnly 页面；水印能力若默认开启会泄露错误身份或改变公开页面，必须默认关闭并显式接入。

## 需求质量门 Requirements Quality Gate

- [x] Every requirement has a stable `REQ-*` ID.
- [x] Every requirement has at least one `AC-*` acceptance criterion.
- [x] Every acceptance criterion has a stable `AC-*` ID.
- [x] Every acceptance criterion has at least one `V-*` verification ID.
- [x] Every acceptance criterion has a verification method.
- [x] No orphan `AC-*` or `V-*` entries exist.
- [x] Scope includes and excludes are explicit.
- [x] No critical ambiguity remains.
- [x] Requirements avoid implementation details unless explicitly required by confirmed constraints.
