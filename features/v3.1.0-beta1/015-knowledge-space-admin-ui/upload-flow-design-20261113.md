# Design: 后台四步上传流程恢复

关联：[spec.md](./spec.md) AC-21–AC-26、[当前代码调查](./upload-flow-discovery-20261113.md)。版本：3.1.0-beta1。基线：a3ebe5828c。日期：2026-11-13。

**状态：规格与设计均已由用户确认，进入实施。** 现有已交付 UI 仍见主 design.md；实现后将本文件更新为实际快照。

## 1. 目标与非目标

恢复旧“上传文件 → 分段策略 → 原文对比 → 数据处理”界面，并保留直接上传快捷入口。初值来自当前空间有效默认策略；用户修改只作用于本次上传，预览与正式处理使用同一份规则及已确认的预览修改。

不改 client、模型/索引配置、正式文件身份与版本规则、解析算法或空间默认保存行为。保留当前 SPACE 创建、授权投影、配额、内容安全、文件夹路径及任务派发；不调用旧知识库覆盖/重试接口代替当前业务用例。

## 2. 约束与 Constitution Check

遵循 constitution.md C1–C7 和当前 release-contract.md 的 F118 Owner/INV：知识模块负责上传容器事实，权限模块仍是唯一判定入口。预览是本次未注册文件的输入准备，不扩大已入库文件的 edit 权限。

- 旧预览服务要求根 edit；新流程必须支持仅目标 folder upload_file，不能降低旧接口鉴权来兼容。
- 现有 SPACE files/folders/upload 已接受 overrides，处理管线按实际规则摘要取预览缓存。新增字段仅为可选上传上下文，旧请求结构和默认处理路径保持可用。
- 文件夹最多 1000 个文件、当前六路并发、现有大小/格式和音视频专用规则继续使用原逻辑；预览按当前选中的文件按需运行，不预先并发解析整个批次。
- 新增会话/可编辑预览状态放现有 Redis，TTL 为 24 小时；冻结处理副本保留 7 天，不随页面会话到期失效。不新增 SQL 表或迁移，不改变现有临时对象清理周期。Redis 状态不可确认时停止相关写操作，不回退无归属预览。
- 路由只增加 uploads/previews 路径，不包含 config；前端 HTTP 仍经过 request 包装，状态不放全局 store 调 HTTP。

Constitution Check：不改变 F048 短路顺序、不增加跨租户例外、不直接操作 FGA；接口仅调用业务 Service，临时状态由知识模块 Repository 管理，已有正式文件创建继续走原授权投影链。C2 无数据库变更，C6 不记录临时 URL/文件内容/凭证，C7 不新增库或 store HTTP。无宪法例外。

## 3. 方案选择

| 决策 | 选定 | 被否方案及原因 | 重新考虑条件 |
| --- | --- | --- | --- |
| 四步恢复方式 | 复用旧 StepProgress、DropZone、规则表单、PreviewFile/PreviewParagraph 外观，使用当前 SPACE 上传/注册状态机 | 整页回退旧 filesUpload：会恢复旧知识库 edit、注册与状态查询，丢失当前目录与授权语义 | 统一上传 API 将来完整取代 SPACE/旧知识库两套流程 |
| 默认规则 | upload-settings 的 effective_defaults 只初始化本次草稿一次，确认后发送完整规则快照 | 在前端写系统默认或每次重新读取覆盖草稿：会丢失空间默认、用户修改及零值 | 服务端默认模型版本或可配置字段发生正式变更 |
| 预览接线 | 新 SPACE 上传会话与预览接口；抽取原解析核心，原预览接口保留原鉴权 | 直接复用旧 edit 预览：只有上传权限者不可用；只替换鉴权：临时路径和旧缓存指针没有当前会话隔离 | 后续已有通用临时文件服务可提供相同归属和规则隔离 |
| 最终处理 | 可选上传上下文先冻结预览，再调用当前正式注册/派发；原调用不带上下文时维持原路径 | 选文件就注册，再用重新处理模拟预览：提前创建正式文件，还要求根 edit | 后端正式改为统一持久上传计划，且经过独立设计确认 |

## 4. 当前与拟实施数据流

### 4.1 已确认的当前状态

SpaceFileUploadPanel 立即暂存并注册；upload-settings 已返回有效空间/系统默认；旧 PreviewResult 使用旧 preview API，KnowledgeService.get_preview_file_chunk 按根 edit 校验。旧缓存还有“当前文件预览”的全局别名，不能据此编辑新流程的某个具体预览。

### 4.2 拟实施主链路

1. 上传路由验证当前目标 upload_file，显示原四步页头。按需选择普通/管理 scope，保留 parent_id 和返回 query。
2. 首次读取 upload-settings 并保留有效默认草稿；暂存文件前再次由服务端验证同一容器，返回本次 upload_id 与原 file_path。此时不创建正式文件、权限投影或索引任务。
3. 分段策略使用旧规则编辑布局。文档/表格规则映射为标准 ProcessingOverrides；保留 per-file 表格选择，数字/二进制零值不丢失，来回切换步骤不重置。
4. 预览请求以 upload_id 指定本次临时文件并提交规则快照；服务端验证上传归属、容器权限与有效规则后调用既有解析核心，返回 preview_id，沿用轮询 processing/completed/error 状态。新入口只写自身预览 ID 的缓存命名空间，不写旧文件别名；异步解析捕获并恢复已验证的租户作用域，不从用户原始主租户推断。
5. 预览结果按 upload_id、preview_id 和 revision 绑定；分块编辑/删除只修改这次临时缓存。规则变化后旧预览失效并重新生成，不能用旧结果进入下一步。
6. 确认后将 file_path、parent_id、overrides 和可选 upload_context 一并提交现有正式文件/文件夹接口。服务端校验上下文与本次规则相符，冻结缓存和会话后再调用当前创建与派发链；处理任务获得冻结缓存副本。只按需预览用户选中的文件，不要求先解析整个批次；未预览条目按同一份确认规则正常解析。
7. 返回的实际文件 ID 进入现有精确 ID/目录/游标状态跟踪。旧“直接上传”按钮跳过策略/预览，但仍要求有效默认已读取，携带完整默认规则和上传会话上下文。

### 4.3 字段与状态

- Upload receipt：服务端生成 upload_id，绑定 actor_user_id、已验证的 tenant_id/space_id/parent_id、原 file_path/file_name、文件大小和 expires_at。客户端不能指定 actor/tenant。
- Preview：preview_id、upload_id、规则摘要、解析 generation、revision、状态及缓存 key；仅接受所属上传会话的文件。原文 URL/分块只在归属和当前权限校验后返回。
- upload_context：`{ mode: "previewed" | "direct", items: [{ upload_id, file_path, overrides, preview_id?, expected_revision? }] }`，作为 files/folders/upload 的可选字段。携带时必须完整覆盖本次请求路径，不能重复、借用其他容器或混合其他身份的条目。每文件规则支持旧 UI 的单独表格策略；不携带时旧调用行为不变。previewed 模式已有预览的条目必须携带对应 ID/revision，未预览条目允许省略；direct 模式明确不使用之前的预览修改，以所提交的有效默认规则处理。
- Upload phase：本地 queued/uploading/staged/registering/registered/error/cancelled；server receipt OPEN/COMMITTING/COMMITTED。预览状态独立 processing/completed/error，只有 OPEN 会话可修改预览。
- 规则使用 schema_version=1、document/table 原字段；显式 batch/file 值优先于空间默认和系统默认，音视频等专用规则保持原优先级。最终有效规则摘要与预览规则必须一致。冻结时将稀疏输入补全为当时的全部有效字段，再传给正式注册，避免默认配置在冻结后发生变更。

### 4.4 冻结、并发与失败

- 预览修改由 Redis 原子校验当前 OPEN、preview_id/generation 和 expected_revision 后写入，并递增 revision。不得通过旧“最后一次预览”别名寻找目标。
- 正式提交在创建 SQL 资源前，以当前 expected_revision 冻结会话并复制成不可变处理缓存；旧预览写入在冻结后拒绝。先完成的编辑会改变 revision，使陈旧提交被拒绝；先完成的冻结阻止迟到编辑。
- 新冻结副本使用独立 key 前缀。处理器仅对该前缀要求快照存在；若过期、Redis 丢失或数据不完整，明确处理失败（10952），不能悄悄按原文重新切分而丢失已确认编辑。旧预览 key 的原 cache-miss 行为保持。新增副本 TTL 为 7 天，API 与 Worker 使用同版实现；冻结块按数字索引排序，缺少 text/metadata/index 的数据视为失败。不宣称 Redis 提供永久草稿存储。
- 已确认完全没有创建资源的前置失败可以恢复 OPEN；进入原注册/派发后遇到未知 ACK，保持 COMMITTING 并禁止自动重复注册，沿用原失败保护。正常完成保存返回文件 ID；客户端可读取自己的上传状态恢复已确认结果。Redis 丢失或未知状态不得推断成功或重试写入。
- 前端按完整 scope、空间、父目录和挂载 epoch 隔离；切换目标时 abort 暂存、预览和状态请求，并拒绝迟到回调。表单修改或预览保存未完成时禁用确认；提交锁先于异步状态更新。
- 重复文件继续显示当前 SPACE/版本用例返回的结果，允许在正式提交前从批次移除；不恢复旧 retryKnowledgeFileApi 覆盖路径。文件夹沿用当前相对路径、深度、空目录过滤和全批预检规则。

### 4.5 模块职责

| 模块 | 负责 | 不负责 |
| --- | --- | --- |
| filesUpload / SpaceFileUploadPanel | 四步容器、返回上下文、阶段切换 | 不自行构造授权或正式文件 ID |
| useSpaceUploadQueue / 上传规则适配 | 复用当前上传并发、取消/重试、延后注册、完整草稿快照 | 不写空间默认配置 |
| 上传预览组件 | 旧原文/分块 UI，绑定当前预览及 revision | 不调用旧知识库分块写接口 |
| 新 uploads endpoint + UploadPreviewService | 容器事实/归属/规则、预览命令、冻结上下文 | Endpoint 不直查数据库，不绕过 PermissionService |
| UploadPreviewRepository | Redis receipt、预览状态和原子 revision/冻结 | 不查询业务授权或修改 FGA |
| KnowledgeService 解析核心 | 原解析算法、规则摘要和临时分块生成 | 无权决定上传者能操作哪个容器 |
| KnowledgeSpaceService 与原上传 application | 正式文件/版本、路径、配额、投影及原任务派发，消费已验证上下文 | 不重新发明另一套文件注册 |

## 5. 已知坑

| 事实 | 不处理的后果 | 处理位置 |
| --- | --- | --- |
| 旧预览是根 edit，上传可只有 folder upload_file | 四步到预览才报无权限 | 新 UploadPreviewService 调当前 require_upload_container |
| 旧表单使用 `value || default` | append_header=0 等有效配置回显为系统值 | 规则适配与 FileUploadStep2 初值改用明确空值判断 |
| 自动切分的默认 separator 可以包含空串 | 旧表单无条件空规则校验阻断下一步，或偷偷换掉有效默认 | 按 split_mode 区分规则编辑校验，保持实际初值 |
| 预览缓存按文件+规则摘要，另有最后一次预览别名 | A/B 预览互相覆盖编辑目标，正式结果与预览不同 | 预览 ID 固定缓存 key；最终规则一致校验及冻结副本 |
| 旧编辑器失焦保存延迟 300ms | 点击确认可能早于最后一次保存 | 上传预览启用 immediateSave，保存同步锁先于确认；其他旧调用保持默认行为 |
| 普通预览 cache miss 会自动使用重新解析的原文 | 新冻结结果丢失后可能静默失去人工修改 | 新 key 前缀强制存在；API/Worker 同版，缺失明确失败 |
| 上传暂存完成不等于创建了正式文件 | 过早显示处理状态或拿本地 ID 查询真实文件 | 阶段分离，只有注册返回的 ID 才轮询当前 children |
| 注册/派发 ACK 可能丢失 | 普通重试可能创建第二次资源 | 复用注册已开始锁，COMMITTING 不自动重发 |

## 6. 对外契约和依赖

### 6.1 新增 SPACE 上传接口（均在 /api/v1/knowledge/space/{space_id}）

| 方法/路径 | 载荷或结果 | 校验 |
| --- | --- | --- |
| POST /uploads | multipart file，query parent_id；返回原暂存字段加 upload_id/expires_at | 目标 upload_file，当前租户与实际文件/配额规则 |
| GET /uploads/{upload_id} | 会话阶段及已确认的注册结果 | 当前 actor、租户、空间、容器及 upload_file |
| POST /uploads/{upload_id}/previews | overrides；返回 preview_id、generation、规则摘要 | 当前会话归属、OPEN、合法有效规则 |
| GET /uploads/{upload_id}/previews/{preview_id} | processing/completed/error、revision、解析结果 | 同一会话、权限和预览绑定 |
| PUT /uploads/{upload_id}/previews/{preview_id}/chunks/{chunk_index} | text、bbox、expected_revision；返回新 revision | 同一当前预览、OPEN、有效 chunk index，包含零值 |
| DELETE 同一 chunks 路径 | expected_revision；返回新 revision | 同上，不能删其他预览的块 |
| 现有 POST /files 和 /folders/upload | 兼容新增可选 upload_context，其他字段与响应保持原义 | 上传上下文完整、规则与预览相符、冻结成功；随后继续原业务校验 |

旧知识库 preview、旧暂存和未传 upload_context 的现有调用保持原协议与权限。内部仅提取解析计算函数，两个入口在各自鉴权后调用；不增加 skip_auth 一类逃生参数。

错误沿用现有 envelope：403 为权限拒绝；18083 为预览任务/会话不存在或不可访问；18087 为规则、预览或 revision 已变化；18088 为仍可确认归属的已过期确认；10952 为解析失败；10998 为无法匹配已冻结提交或状态不可确认。无权对象不披露他人任务是否存在。字段不合法仍使用现有请求校验，不新增模块号或明文底层错误。

### 6.2 依赖与风险

| 依赖 | 使用方式 | 变化风险 |
| --- | --- | --- |
| upload-settings effective_defaults | 前端完整草稿初值 | 字段新增、零值及规则版本必须同步适配与校验 |
| SPACE 正式注册与处理快照 | overrides 及可选冻结上下文 | per-file 规则与专用媒体优先级不能被 batch 覆盖 |
| Redis 与既有预览缓存 | 临时归属、revision 原子性、冻结副本 | Redis 不可用时 fail closed；若未来启用 Redis Cluster，需重新评审跨 key 原子操作 |
| API/Worker 同版本 | 新冻结前缀的强制读取行为 | 旧 Worker 会把快照缺失当普通缓存未命中，因此新四步入口启用须配套更新 Worker |
| 现有 MinIO/解析管线、Office/PDF/媒体依赖 | 继续原文件格式解析和原文展示 | 不新增二进制；不把本地模拟结果作为真实解析验收 |
| 原 StepProgress/规则表单/PreviewFile/PreviewParagraph | 保持旧四步视觉和编辑器 | 兼容适配不改变旧 KB/调整模式调用；React 退役回调不能借用新目标 |

## 7. 验证策略

- 前端：规则初值/映射、步骤往返、默认和手动规则、单独表格规则、预览/提交一致、直接上传、范围切换、取消/重试、ACK 未确认；复跑原文件夹/上传/规则/预览回归。
- 后端：容器 upload_file 允许/拒绝配对、根 edit 不作为前置、跨账号/租户/空间/父目录拒绝、旧 API 权限保持、revision/规则变化与冻结竞态、注册前失败和未知 ACK；无真实中间件时标明模拟边界。
- E2E：按 e2e-test 使用隔离测试数据和已登录角色，完整走默认、改规则、预览分块修改及最终处理；记录环境、账号权限和最终 chunks。浏览器检查四步外观、默认回显、1024px 及详情返回上下文。
- 手工入口：platform 的 /filelib/upload/{space_id}?parent_id={folder_id}&view=admin；普通用户省略 view；分别使用测试租户管理员和仅该文件夹 upload_file 用户。测试环境及造数方式在设计确认后的八列表格用例中补齐，不写真实账号凭证。
- 验证报告区分定向单测、浏览器模拟、真实写入 E2E 和部署；日志仅记录安全 ID、阶段、规则摘要和失败码。

## 8. 不实施的扩展

不重写解析器、版本覆盖或任务调度，不迁移历史文件，不引入独立上传微服务、SQL 会话表或新队列。新会话只服务于当前四步上传。若后续需要跨端长期续传、多人协同预览或跨天恢复未知提交，再评审持久任务及升级兼容方案。

## 修订历史

| 日期 | 改动 | 触发原因 |
| --- | --- | --- |
| 2026-11-13 | 初版待设计确认；规格已经用户确认 | 恢复旧四步 UI，并补齐现有 SPACE 上传资格与预览、规则一致性 |

| 2026-11-13 | 按已确认设计实现：复用四步 UI、上传会话及预览 CAS、规则补全与冻结、原注册链衔接；不新增数据库表 | 用户明确回复“按此设计实施” |

实现补充：前端仅请求当前选择文件的预览；已完成的同规则预览用于下一步，不重复解析；正在处理的预览可接续轮询。预览规则/generation 改变时重建对应编辑实例，防止旧编辑结果被标记为新规则。取消或切换目标时中止本地请求，已开始的服务端解析可完成，但只能写回原会话，不能修改冻结会话或新目标。
