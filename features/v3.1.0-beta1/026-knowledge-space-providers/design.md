# F026 技术设计：知识空间多后端与 WeKnora

版本 v3.1.0-beta1（CNNC）；2026-11-24。**规格与技术设计均已由用户确认（2026-11-24）；下文“拟”表示尚未实施。本次确认进入 QA 用例和任务拆解，不代表运行验收通过。** [规格 AC-01～37](./spec.md)决定产品结果；[集成实现方案](./WeKnora集成实现方案.md)仍是公共契约与厂商规则的单一实施入口，本文记录本Feature的接手决策、消费者及验证门槛。

## 1. 目标与非目标

让同一套毕昇个人/部门空间入口在不改变权限语义的前提下，选择原生或远端处理后端。业务用户和管理员只操作毕昇；远端空间在任一时刻只有一个有效内容库。不迁移普通库、FAQ或存量原生数据，不为兼容旧入口在毕昇另存远端原文，不将未验证可选能力列作交付。

## 2. 关键约束与 Constitution Check

设计按[架构宪法](../../../docs/constitution.md)及[发布契约](../release-contract.md)核查。F026负责外部绑定、映射及操作恢复；消费F118资源事实、F048授权与已有引用契约，不建立第二套授权裁决。目标版本是WeKnora v0.9.0 `f17ee8a` 加经验证的明确扩展，而非任意main或单凭版本号放行。

| 条款 | 本特性的检查位置及放行证据 |
|---|---|
| C1、C4 | 业务层先加载所属空间、父链和生命周期，再通过现有权限入口判动作；Provider不写OpenFGA，endpoint不写库。API、Celery、Linsight同源装配。 |
| C2、C3 | 新增控制对象及索引须经MySQL/DM8迁移、唯一性和并发认领测试；请求主体决定租户，后台按受理意图恢复并重验，跨租户投影拒绝。 |
| C5、C6 | 映射现有已登记错误；需新码先登记，不在此占号。凭据留在实例秘密管理边界，错误、DTO、指标均不得包含Key、内部路径或正文。 |
| C7、C8 | 两端分别走各自API层，store不直调HTTP。消息仅作唤醒，可恢复状态在共享持久存储；请求期缓冲不是跨节点文件库。 |

## 3. 技术决策与被否方案

| 决策 | 选定及原因 | 否决方案／重新评估条件 |
|---|---|---|
| 业务入口 | 请求级Resolver固定租户、实例、库、代次、能力修订；Native只包执行部分。现有空间服务同时含权限与执行，直接包装会重复投影。 | 不在页面或业务路由写厂商分支；若新厂商引入全新业务语义，再升级公共端口。 |
| 内容与控制 | 本地持久文件/逻辑文档/版本身份，字节及派生内容全归远端。先登记版本和授权意图再流式发送。 | 不用MinIO中转异步重传；只有远端提供可验证续传收据时才开放断点续传。 |
| 跨系统写入 | 业务意图与待派发表同一短事务；HTTP在锁外，Beat扫描到期行，Worker用租约/修订条件回写，未知先查回。见主方案§9.2。 | 不假定跨系统事务，不因超时重新建库。若未来具备可靠事件交付可代替正常轮询，但不能省掉结果证明。 |
| 检索 | 先按用户选择、文件动作、版本、标签关系求交，再分后端/Embedding召回并按排名融合；将来源映回本地版本，进模型前复核。 | 不用全库回答后删引用模拟授权；仅当远端索引过滤与关系事实等价且经实测才作优化。 |
| Wiki与版本 | Wiki按空间visible，原文按文件动作；旧来源未撤回或未证实全部收尾时关闭受影响Wiki读取。单库重建仍须证明覆盖目标修订。 | 不按每篇来源裁Wiki正文，不把文档completed当库已收敛。若产品修改共享口径须重审规格。 |
| 标签 | 远端按库维护候选与双来源关联。空库唯一初始化冻结样本、模型、草案；发布词表时原子登记回填意图。 | 不以本地标签库绑定、每文件成功或同名唯一索引代替整库初始化；若远端不能保护来源或条件写则不开放对应操作。 |

## 4. 接手快照与拟变更

当前毕昇基线 `150dbe62b9`。**现状**：空间、文件权限、原生入库及引用已有业务链，多个消费入口非同一实现；下列是拟接入点，不是声明接口已经发布。

| 现有入口 | 拟变更（输入→执行→输出） | 不得绕过的边界 |
|---|---|---|
| [空间入口](../../../src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py)、[部门批建](../../../src/backend/bisheng/knowledge/domain/services/department_knowledge_space_service.py) | 选择预设→管理租户/权限→逐部门意图与预置UUID→远端建库回读→本地绑定/部门授权→ready；局部重试查回原库 | 组内只投影已就绪资源；隐藏、置顶、审批、退出和组织授权仍在本地 |
| [上传应用](../../../src/backend/bisheng/knowledge/application/space_upload.py)、[开放文件入口](../../../src/backend/bisheng/open_endpoints/api/endpoints/filelib.py) | 注册版本/额度预留→Provider上传→收据核对→权限映射与计量→远端处理；分别显示接收、解析、Wiki、标签阶段 | v1/v2、URL、频道和预制块均在落地前分流。无等价原协议拒绝，不做同步成功假象 |
| [权限装配](../../../src/backend/bisheng/api/services/f048_permission_runtime.py)、[检索资格仓储](../../../src/backend/bisheng/knowledge/domain/repositories/retrieval_file_repository.py) | API/Worker按绑定加载事实→动作检查→候选资格→返回前重验 | 不再用本地原文路径或原生SUCCESS推断外部权限；实例失联不建立新的读取资格 |
| [日常检索](../../../src/backend/bisheng/workstation/domain/services/chat_service.py)、[任务工具](../../../src/backend/bisheng/tool/domain/langchain/linsight_knowledge.py)、[工作流检索](../../../src/backend/bisheng/knowledge/domain/services/space_flow_retrieval.py) | 本轮/任务版本冻结所选空间和固定标签→工具上下文限定范围→统一检索→各入口原有格式和引用注册 | 新任务、恢复及子Agent均重验；shared只按既定作者策略；回答模型不使用远端处理模型ID |
| [引用解析](../../../src/backend/bisheng/citation/domain/services/citation_resolve_service.py)、空间文件读取 | 本地引用→版本/代次→JSON受控地址→GET/Range逐次验权→转发流并关闭上游 | 不返回远端签名链接；陈旧定位只降级为受控文件/片段或不可用，不指向新正文 |
| [原生调度](../../../src/backend/bisheng/worker/knowledge/processing_jobs.py)、[原生任务模型](../../../src/backend/bisheng/knowledge/domain/models/knowledge_processing_job.py) | 复用到期扫描、CAS和有限并发模式，独立外部操作账本区分sending、reconciling、applying及终态 | DB事实优先于消息。API恢复、Beat、Worker不得持SQL锁发HTTP，不重传已丢失字节 |

**模型数据流。** 在管理视角按实例验证LLM/Embedding的类型与可用证明、维度及VLM图像能力，提交前展示配置摘要。创建document库，分别启用Wiki索引、有效抽取预设、图像处理和自动标签；设置摘要模型，Wiki/标签用途默认不写独立覆盖。明确覆盖高于继承。按用途记录任务使用的模型修订。更新后仅新受理任务用新配置；Embedding空库亦不可改，模型身份变更需双库追平、验证、一次切换。

**文件/版本与恢复。** 对每个租户内的稳定请求键校验请求摘要，冻结目标版本与操作epoch；批次逐项报告。删除先冻结业务引用和版本清单、设本地墓碑，再执行远端索引/标签/来源撤回；多源Wiki仅在目标修订确证后解除屏障。迁移旧目标清理按冻结代次，不用当前指针重路由。历史版本计入用户额度至删除确认，迁移的同一版本不重复记费。两侧恢复点不一致时隔离相关空间，先对齐授权、删除意图及来源证明，再恢复读取。

**空库标签与模板。** 远端按目标库及绑定代次认领一次初始化。两批同时上传只有一份候选草案，失败按草案逐项查回。未发布时可继续解析，不按半份词表分类。发布后以文件版本＋词表修订回填，只更新自动来源；成功无匹配不无限重试。公共模板按部门分别冻结、导入、报告，不持续绑定源模板。人工空追加不清空，显式替换/清空比较文件关联修订；批操作预检不建词。删除标签只删关系，已被引用而无安全操作能力时拒绝。

**存储与迁移归属。** 拟增实例及秘密引用、绑定/单一生效代次、业务资源到远端对象映射、标签正整数引用、操作及预留计量事实；外部唯一范围含租户/实例/库/代次/资源类型。幂等、到期、租约按租户建立可索引列；先以可空/附加结构兼容旧记录，再显式标记原生空间、核对后放量。禁止用无法解析的外部绑定回落Native。配置灰度可关闭新受理，保留未决账本、墓碑和旧代次清理，不以回滚应用版本删除运行中的证据。远端收据、Wiki应用证明、标签草案/来源/回填、版本归档及模型锁是独立上游扩展责任；不得在毕昇内容表补齐。

### 4.1 Wave4 落地时新增/收紧的契约（2026-11-24）

- **外部预览降级为文本节选。** WeKnora 的 `/preview` 返回原件，不能冒充派生预览；首期能力声明为 `preview=conditional, preview_representation=text_excerpt`：只取少量同级文本块、限字节、纯文本内联（`nosniff` + CSP sandbox），领取时逐次重判权。原版式预览在具备安全渲染器前不开放。
- **任务范围持久化。** `linsight_session_version` 新增 `knowledge_space_tag_filters`（JSON，NULL=未记录）；提交→会话→Worker 工具同源读取，`TaskKnowledgeScope(recorded, knowledge_ids, tag_refs)` 冻结范围，模型参数只能收窄；缺身份或标签失效即失败，不回落全库。
- **Native 全局排序保留。** 检索装配先解析全部路由；全 Native 时走原有 `_retrieve_native_many`，不进入跨源交错融合，避免多库全局 top-k 被改写。
- **批处理会话可注入。** `get_batch_application` 接受 `app.state.provider_batch_session_factory`（生产默认共享库，测试用一次性 SQLite），写端口仍必须来自注册的 resolver。
- **迁移期标签与 Wiki 水位。** 标签写事务占用同一 `pending_write_operation_id` 写槽，切主比对标签修订；切主凭目标库自身 source-revision 证明安装 `wiki_target/applied_revision`，不沿用旧库水位。

### 4.2 不设建库预设（2026-11-25）

WeKnora 侧的常规修改不应要求同步修改毕昇配置，也不应让已建空间失效。

- **建在哪个实例。** 不再有预设：`weknora.deployment` 与 `BS_WEKNORA_PRESET_<租户>` 均已删除，YAML 里写 `deployment` 会在加载配置时报错。新空间建在该租户唯一一条 `provider_key=weknora`、`state=ready` 的 `knowledge_provider_instance` 上，实例 ID、`remote_scope_id`、`capability_revision` 都从这条记录读。没有或多于一条时拒绝创建，「WeKnora 连接」页在有多条连接时提示管理员处理。
- **抽取配置（创建时选择）。** 不再把模板 ID 写在 `knowledge_provider_instance` 上（迁移 `f026_drop_instance_template` 删除 `template_kb_id`）。创建人必须二选一：
  - `extract_template_kb_id`：从 `GET /api/v1/knowledge/space/provider-extract-templates` 列出的、本空间已开启且结构可用的 WeKnora 知识库中选一个，建库时拷贝其当前 `extract_config`；
  - `extract_config`：结构化提交 `text` / `tags` / `nodes` / `relations`（`enabled` 由服务端固定为 true；节点名唯一，关系两端必须落在已声明节点上）。
- **创建人选择（AC-03/05）。** 摘要对话模型、向量模型、视觉模型、分块长度和重叠长度，以及上述抽取来源，均在创建表单里选择：个人空间在 client 创建页，部门空间在平台部门批建。模型候选来自 `GET /api/v1/knowledge/space/provider-models`（本空间 KnowledgeQA、Embedding、VLLM；向量须带维度）。选择以 `ProviderSelection`（禁止多余字段，三模型互不相同，`0 ≤ overlap < chunk_size ≤ 100000`，且恰好一个抽取来源）提交：
  - 预览：`POST /creation-settings`，体为 `{provider_key:"weknora", provider_selection}`；部门预览的请求体为 `provider_selection`。
  - 创建：创建和部门批建在 `preset_summary` 旁同时提交 `provider_selection`。WeKnora 空间缺少它即拒绝，原生空间带上它也拒绝。抽取来源写入操作的 `target_manifest`，Worker 建库时再探测。
  - 前端核对：预览摘要中的模型 ID 和分块若与所选不一致，前端拒绝。选择进入幂等身份，同一请求键改了选择会被拒绝。
- **现场证明。** 实例修订号每次从 `ready` 实例行读取。模型按 ID 读目录并调用调试接口实测；版本取 WeKnora 模型的 `name`（实际调用的上游模型名），改 Key、限流等不会改变它。图谱每次检查 Neo4j。抽取：选模板则每次读该库当前 `extract_config`；手填则校验并摘要创建人提交的配置。
- **按空间冻结。** 预览摘要带上本次读到的 `extract_digest` 和模型版本；创建前重新探测，与创建人确认的摘要不一致则拒绝，不留下半建空间。建库后的回读和设置读取按空间自身冻结的实例与修订寻址，不再与当前实例配置比对，因此更换模板或修改连接不影响已建空间。
- **仍保留。** 向量强锁指纹由实例、空间 ID、向量模型 ID、上游模型名和维度组成；同一 ID 指向另一上游模型时仍被拦住。

## 5. 运行时陷阱与护栏

| 已知事实／证据 | 后果 | 处理位置 |
|---|---|---|
| [建库保留传入UUID](../../../dist/WeKnora/internal/application/service/knowledgebase.go#L136)，上传冲突却可能返回另一文件 | 盲重试建重库或泄露其他目录文件 | 建库按原ID查回；上传按原请求收据，冲突脱敏，不能按hash认领 |
| [文档库默认与图谱开关](../../../dist/WeKnora/internal/types/knowledgebase.go#L880)、[启用抽取的样例约束](../../../dist/WeKnora/internal/handler/knowledgebase.go#L1700) | 只传布尔开关可能建库失败或无自动标签 | 预设固定document；同库验证分块、Wiki、实体及文件标签四种产物 |
| [远端标签批写是替换](../../../dist/WeKnora/internal/handler/knowledge.go#L2660)，[强制删词可删除内容](../../../dist/WeKnora/internal/application/service/tag.go#L322) | 批量追加误清其他标签，甚至删除文档 | TagPort分开append/replace/clear；禁透传force，受限则拒绝 |
| [Wiki删除清理错误可仅记警告](../../../dist/WeKnora/internal/application/service/knowledge_delete.go#L200) | 原文虽已删，Wiki仍暴露旧贡献 | WikiPort读取屏障+可靠修订证明，管理员只能重试/重建不能强行解锁 |
| 空候选远端查询不等于“零命中”；分块scope_tag_ids仅记录逻辑范围 | 检索范围被放宽 | RetrievalPort发请求前以远端文档正清单约束双路；无候选直接结束，失败按空间明确报告 |

## 6. 对外契约与依赖

| 拟提供的契约 | 消费者及兼容要求 |
|---|---|
| `GET /api/v1/knowledge/space/{space_id}/capabilities`；能力状态及 `capability_revision` | client/平台/预检：区分conditional、unsupported、unverified与暂时不可用；确认时能力变化使计划失效。 |
| 现有创建/部门批建、文件列表和预览/下载；新旧响应需版本化或同源转换 | 部门批建逐项关联 `operation_id`；children不凭空增加total，search返回可见total；旧预览保留JSON信封，取件重新判权。 |
| `operation_id`、`request_key`、`expected_revision`、`generation`，以及外部实例内不透明ID | 统一操作服务、Worker和管理状态页。不同租户/请求主体不能认回他人收据；accepted/running/partial_failed/unknown独立于succeeded。 |
| `ProviderResolver`、组合Port、`RetrievalHit(space_id,file_id,version,locator,…)`、`tag_ref_id` | Native/WeKnora、任务/工作流、引用服务；客户端用本地ID，引用保留历史版本和代次；可选端口不能伪装成功。 |

依赖：WeKnora服务及其模型、存储、检索、图谱与工作进程；毕昇已有权限投影、消息调度、计量和会话存储。服务认证由实例配置决定，忽略浏览器提供的远端租户头。任一关键写结果无法证明时保持未决，库暂时不可用时不借管理员身份查询。能力协商不能降低首期必做要求；必做缺口是上线阻断项，而不只是隐藏按钮。

### 规格到设计的审查索引

| AC | 实现边界与主要验证点 |
|---|---|
| 01–03、08、35–36 | §4创建/组织链、§6空间契约：新旧创建、部门部分成功、授权投影与原生菜单语义 |
| 04–07 | §4模型与迁移：模型可用、用途继承、空库强锁、单一代次 |
| 09–16、29–31、34、37 | §3–5文件与恢复：存储归属、拒绝旧写入、查询/取件/删除、版本、配额及DR；§6区分受理与完成 |
| 17–19 | §3/5空间Wiki、来源与读取屏障：空间派生共享，原文逐文件判权 |
| 20–25 | §4/5远端词表、人工关联、初始化与补标；选择器分页，稳定标签引用 |
| 26–28 | §4–6任务/会话/工作流及引用：范围只能收窄、分别复核原文授权 |
| 32–33 | §6能力协商；已有metadata值按真实字段类型读写，下推或等价过滤，不提供schema迁移 |

## 7. 测试、观测与放行

单元层验证范围求交、模型继承、状态转移、旧修订拒绝；适配层公共契约在两个真实后端及仅供测试的第三Provider上区分路由验证与实际能力。集成层分别在MySQL和DM8验证幂等/并发/租约，注入Broker丢消息、WeKnora丢ACK、部分Wiki收尾和撤权。双端E2E通过client与platform，逐入口核对实际候选、引用以及MinIO/ES/Milvus无新增外部内容，不以HTTP状态代替成功证明。

手工走查：在测试租户用租户管理员从管理端的部门空间批建入口为两个部门建库；另用两名普通成员从客户端 `/workspace` 进入部门空间。两人具有相同空间读权，只有一人可读、下载受限来源文件。上传采购、安装、验收三份资料并生成Wiki；两人看同一节点，只有授权者取得来源。模拟第二次建库ACK丢失、Worker重启、删除一个多源页面的来源；查两侧库数、关联、任务收据和Wiki修订，再重放旧链接。按tenant/space/operation/generation定位日志；监控unknown时长、队列积压、过期租约、权限拒绝、传输与召回延迟。容量目标取真实目标环境测量值，不预报SLO。

## 8. 不做与重评条件

首期不开启上传前编辑冻结、schema迁移、未经证明的空目录/完整移动/版本合并推荐。远端中断不允许本地正文缓存兜底；会话与交付物是使用阶段记录，撤权不能冒称自动抹除已生成答案。新增厂商需扩展业务语义、改变共享口径、改变数据权威或削减必做能力时，先回到规格/设计门禁，不在开发中静默变更。

## 修订历史

2026-11-24：基于用户已确认的F026规格形成技术设计初稿。
2026-11-24：Wave4 落地后补充 §4.1（预览节选、任务范围持久化、Native 排序快路径、批处理会话 seam、迁移期标签/水位）。
2026-11-25：经用户确认补充 §4.2，预设去掉 WeKnora 侧事实（revision、model_pins、extract_digest、graph_verified_at），改为现场探测并按空间冻结。同日按用户要求，三类模型与分块从预设移到创建表单（`ProviderSelection`、`provider-models` 接口），预设只剩实例与模板。随后又去掉预设：实例取自 `knowledge_provider_instance`，模板改为实例上的 `template_kb_id`。
2026-11-26：按用户选择 C，抽取改为创建时选模板或结构化填写 `extract_config`；去掉实例 `template_kb_id`；新增 `provider-extract-templates`，WeKnora 预览改为 `POST /creation-settings`。
