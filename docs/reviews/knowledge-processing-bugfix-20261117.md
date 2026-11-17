# 知识空间分段、覆盖上传与任务失败排查

- 基线：2026-11-17 拉取 `origin/feat/3.1.0-beta1`，`97487e9f25`。
- 分支：`codex/3.1.0-beta1/knowledge-processing-bugfix-20261117`。
- 独立 worktree：`.worktrees/beta1-knowledge-processing-bugfix-20261117`；原工作区未提交内容未搬移或覆盖。
- 本次为既有行为修复，不新增 API、数据库字段或任务类型；未部署、未恢复现场任务。

## 1. 分段调整与预检

`worker/knowledge/processing_jobs.py` 的 `file_reprocess` 和 `file_resplit` 都调用 `prepare_processing_file`。后者对两个 kind 均从原文件运行 `KnowledgeFilePipeline` 到 TRANSFORMER，再更新索引；没有“仅复用已解析文本”的另一条实现。因此两个按钮当前没有实际执行差异。

修复后，文件详情和历史版本菜单进入独立的三步页面：分段策略 → 原文对比 → 数据处理。路由使用 `process_file_id`，保留原目录、过滤条件和文件详情参数；返回恢复原上下文，切换目录/空间清理处理目标。统一提交 `file_reprocess`，保留旧 `file_resplit` API 和历史任务兼容。配置优先回显文件自身的规则，而非用当前空间默认配置覆盖旧文件。

仅展示、提交本文件适用规则：表格仅表格参数；普通文档仅文档参数，PDF 专用选项只给 PDF，层级切分只给 md/doc/docx；网页和音视频沿用其专用规则，不向处理预检提交普通文档或表格覆盖参数。原文对比复用原有上传预览与查看器，为只读预览：旧缓存编辑不会被当前任务处理器消费，不能让用户误以为预览里的人工改动已经保存。正式处理会覆盖原版本分段与既有人工调整，页面保留提示。

预检有实际作用，保留在“下一步”后：检查空间编辑权、目标版本和归属、文件可见性、解析状态/活跃任务、模型引用准入，并冻结模型配置/索引代次、处理配置版本、文档版本修订和源文件摘要。确认时按同一计划再校验，防止用过期配置或目标启动任务。计划有效期为 5 分钟；过期需返回重新预览。预检本身不是分段结果预览，也不代表文件已经重新解析。

代码：`application/processing_owner.py`、`domain/services/processing_job_service.py`、`application/knowledge_processing_commands.py`；前端 `SpaceProcessingDialog.tsx`、`FileProcessingPreview.tsx`、`fileProcessingRules.ts`。

## 2. 分段编辑权限

原 `PUT/DELETE /api/v1/knowledge/chunk` 只验证空间 edit、实际物理文件/版本归属和处理状态；未验证文件 visible。具有空间 edit 但文件不可见的用户可以直接修改或删除索引分段。

现于索引 IO 之前增加统一 `require_business_action(knowledge_file, visible)`。空间 edit 仍是编辑动作门槛，不要求文件具备不存在的 edit 动作。文件处理目标读取、预检及确认也补上同样的 visible 校验，避免另一路重新处理绕过文件可见性。保留合法历史物理版本的编辑能力。

回归覆盖更新/删除两入口在文件不可见时没有索引 IO，以及不可见版本在预检中不产生队列或文件状态写入。

## 3. 解析中是否禁止删除空间

**会禁止；本次保留保护。** `knowledge_space_delete_repository.py` 将实际范围内状态为 PROCESSING(1)、REBUILDING(4)、WAITING(5) 的文件标记为 busy。`knowledge_delete_precheck.py` 对文件/文件夹给出 processing；空间删除/清空只要任一 unit 包含 busy 文件就不可执行，force 也不能越过。空间本身重建或具有 model_transition 时另有 idle guard。

这避免异步解析/重建继续向已删除的对象、ES/Milvus 索引写入，以及删除流程与版本/授权/引用清理并发。FAILED(3)、TIMEOUT(6)、VIOLATION(7) 不因该状态保护单独阻断，仍要通过权限及引用检查。

影响：只要有一个排队/解析/重建文件，就可能挡住整个空间或包含它的文件夹；状态长期卡住也会长期挡住删除。截图里的“受影响数量 0”是当前可删除集合，不等于空间实际没有文件。不能通过手工改 status 或取消预检解决，应先核对真实队列/Worker 是否仍在执行，再走既有失败/超时恢复。

## 4. 重名覆盖失败和重复展示

可复现链路：后端按文件名或 MD5 判重，多份上传可命中同一个已有物理文件；每条响应返回相同 id/name，暂存对象也是同一个 `tmp/<id>.<ext>`。客户端 `extractDuplicateFileEntries` 过去照单全收，显示多行相同名称，并向 retry 接口重复提交 id。`LegacyRetryApplication._inputs` 因 `legacy_retry_invalid_file_id` 拒绝整个替换请求，错误码 10998 被展示成配置冲突。

客户端现在按已有文件 ID 合并冲突项，保留最后一次暂存响应，与服务端最后保存的暂存字节一致；同一文件只展示和提交一次。真正新登记的文件仍按原流程进入可见列表，不因为存在冲突而跳过。未改变“同名或同内容判重”的既有规则；仅凭截图不能确认所谓未重名文件是否实际 MD5 相同。

尚不能据此排除其他现场覆盖失败原因，例如真实文件仍处理中、版本链损坏或并发变化。这里修复的是本地已重现的重复 ID 拒绝链路。

## 5. 批量移动/复制任务

第 6 张截图标题及状态是**空间复制**，不是批量移动：目标空间 4394、0 成功/11 失败。两条实现分别为 `space_copy_jobs.py` / `space_copy_worker.py` 与 `move_jobs.py` / `move_index_worker.py`。

代码确认两者都有同一诊断限制：若异常不是 BaseErrorCode，会统一记录 `ResourceReferenceInvalidError.Code = 10996`，因此普通对象存储/索引/运行时错误也可能显示成“资源引用已失效或修订发生变化”。**不能由这一行提示断言失效引用就是根因。** Worker 的 `logger.exception` 仍保留真实堆栈，可据 job_id/item_id 找到第一处错误。

当前 beta1 的复制逻辑已按源空间→目标空间顺序获取行锁，并在锁内完成每个权限投影；这不构成本次 4394 任务根因已经解决的证据。

本轮尝试只读 SSH `root@192.168.106.116`，密钥认证未通过，未拿到该任务 Worker 日志、部署版本或 SQL 状态。已向用户请求可用排查连接/日志。移动、复制及其恢复的本地回归通过，但不代表截图现场通过。本次不对这一项猜测修复、不重新执行现场任务。继续所需：目标 4394 的 job_id、第一条 item 失败堆栈，以及用户所述实际移动任务对应 job_id；检查模型引用、权限投影账本、对象存储及 ES/Milvus 错误时以首个异常为准。

## 6. 截图预检问题：存在性和影响（先列清单，不调整迁移/配额行为）

| 截图项 | 最新代码结论 | 影响 |
|---|---|---|
| KS-185：预检异常缺少定位信息 | 存在。`unification_preflight._blocked` 只传 reason，CLI 的 BaseErrorCode 分支只输出 code/reason/run_id 等，缺少失败对象的 tenant_id、资源类型及 ID。 | 会正确阻断，但跨租户/大量对象下难以定位修复对象，可能反复扫描；不能把阻断当作检查已通过。 |
| KS-686/689：迁移空间不计个人数量 | 当前并非 Bug。现行 spec AC-61 明确要求持续豁免迁移空间个人可新建数量；DAO 和 `QuotaRepository.usage_statement` 均按非空 migration_origin 排除。 | 迁移空间不会消耗个人“可新建数量”；租户空间总量仍计入，超过租户上限仍禁止新增。与旧截图所引 PRD 口径不一致，本次遵守当前确认规格。 |
| KS-192：历史 upload 文件存储漏计 | 存在。`role/domain/repositories/quota_repository.py` 的个人/租户存储 SUM 只纳入 channel、space_upload；`unification_preflight.py` 的 quota_usage.stored_bytes 同样忽略 upload。现有原生 SQL 测试含 1000 字节 upload，断言总量仅 700，证明遗漏，而非仅静态推测。 | 历史原文仍占存储，但个人/租户存储用量和配额准入偏低；迁移基线本身也沿用漏计口径，不能据它证明物理存储用量一致。迁移转换不应重复增加用量，但应按真实占用计算。修复需同时核对原 upload/历史来源及准入口径。 |

以上“预检”是升级迁移 M2 预检，与第 1 项用户操作前的处理预检不是同一机制。

## 验证边界

验证数量及审查结论见同目录 `knowledge-processing-bugfix-review-20261117.md`。未访问真实 116 数据、未执行 DM8 回归、未进行真实解析服务和对象存储/ES/Milvus 的端到端验收。没有修改迁移配额或取消删除保护。

## 现场验收清单（待执行）

1. 在普通和管理范围分别打开成功文档及历史版本，调整分段 → 原文对比 → 数据处理；刷新/返回保留目录和过滤参数，确认后只改变目标物理版本。
2. 分别以 PDF、md/docx、txt、表格、网页和音视频核对规则展示、预览及实际索引结果；预览不提供人工编辑入口。
3. 非管理员拥有空间 edit、文件不可见时，直接调用 Chunk 更新/删除与 processing-target/precheck/confirm，均拒绝且无索引写入。
4. 同一批多个文件命中同一已有文件并混合真正新文件时，冲突列表只显示一个已有目标，替换成功；新文件照常登记。另核对同名不同内容和同内容不同名的既有判重规则。
5. 取得 116 日志后，定位目标 4394 复制任务及实际移动任务首个异常；按根因处理后在原任务上重试，核对源/目标文件、版本、索引和授权。当前未满足这一验收条件。
