# 实施偏差与复盘 Retrospective: 知识文件解析三级优先级

## 2026-08-06 首钢门户上传记录扩展

- 变化：原规格仅覆盖 Platform 文件上传解析进度区；用户确认首钢门户上传也需要展示前方等待数量，因此将 Client 的“上传记录”纳入 `REQ-007`、`AC-REQ-007-13` 和 `T012`。
- 设计处理：继续复用现有 `GET /api/v1/knowledge/{knowledge_id}/parse-queue-positions`，不新增后端端点；门户当前页最多 20 条记录，按知识库分组后分别批量查询。
- 兼容处理：排队位置仍为旁路能力。查询失败、返回 unavailable 或文件进入终态时保留原上传状态，不弹高频错误提示，也不影响原 5 秒上传记录轮询。
- 代码组织：新增查询状态和文案提取到 `PortalUploadQueueStatus.tsx`；为使本次触及的 `PortalUploadedFilesDrawer.tsx` 回到项目 600 行门禁内，另将原有目录树节点的纯渲染与递归更新提取到 `PortalUploadFolderTree.tsx`，目录加载、选择和保存行为不变。
- 验证：Client API 契约、门户主路径/失败路径/终态路径、完整门户组件回归和 production build 通过；全库 TypeScript 类型检查仍被既有类型债务阻塞并记录在 `verification.md`。

## 2026-08-06 首钢门户排队文案与刷新体验收敛

- 变化：用户确认首钢门户“上传记录”不需要暴露标题提取、正式解析、重试阶段和全局运行数；queued 状态统一展示“排队中，前方约 N 个等待任务”。2026-08-09 生命周期收敛时 Platform 也同步改为无阶段通用文案，不再读取兼容 `stage` 字段或展示运行数。
- 刷新策略：首次打开与切换分页仍允许整表加载占位；当前页已有数据时，自动轮询、上传触发刷新和手动刷新保留现有表格并按文件 ID 合并服务端字段，避免记录行卸载、横向滚动和编辑上下文闪烁。
- 边界：不修改轮询间隔、分页契约或队列计算语义；后端 `active_count` 保持可观测契约，nullable `stage` 仅为旧前端滚动兼容暂留，新 Platform/Client 均不读取。

## 2026-08-09 文件解析生命周期收敛

- 触发原因：单并发 Worker 下，批量上传会按消息 FIFO 先执行多个文件的标题任务，再执行正式解析，形成“文件1标题→文件2标题→文件3标题→文件1解析”的跨文件阶段穿插；这与用户理解的一个文件解析生命周期不一致。
- 已确认决策：初次解析使用一个 delivery/ticket，领取后立即置 PROCESSING，并串行执行标题提取和正式解析；标题失败只记录日志并继续。重试使用一个 delivery/ticket，领取后立即置 PROCESSING，并串行执行旧向量清理和正式解析，不重新提取标题。
- 调度边界：Worker 总并发、单 `knowledge_celery`、Redis 三级优先级和 `prefetch_multiplier=1` 保持不变；PDF Artifact、相似文档候选、推荐投影继续异步，不并入主文件生命周期。
- 可观测调整：一次正常文件尝试只创建一个 queue ticket，内部步骤不换票；Platform 与首钢门户统一展示“排队中，前方约 N 个等待任务”，不再展示标题/正式解析/重试阶段。旧 `stage` 响应字段只允许作为滚动兼容的 deprecated 字段暂留。
- 发布影响：现有 T006/T007 和 2026-08-06 的标题后继验证只保留为历史基线；新增 T013 实现生命周期合并，并要求 Worker-first 兼容旧标题/正式解析/重试消息，禁止通过 purge 处理存量消息。
- 实施结果：新生产入口只发布带 `knowledge_parse_attempt_kind=initial|retry` 的正式解析/重试生命周期消息；初次解析领取后按 PROCESSING→标题 best-effort→正式解析连续执行，重试按 PROCESSING→旧向量清理→正式解析连续执行。旧标题消息直接完成初次生命周期且不再发布后继，缺新 header 的旧正式解析保持 formal-only。
- 前端结果：Platform 与首钢门户都只在 queued 时显示“排队中，前方约 N 个等待任务”；Platform 的 processing/unavailable 使用通用文案，门户保持原文件状态。门户已有上传记录刷新继续按文件 ID 原位合并，不卸载整表。

## 2026-08-09 门户上传完成队列名次提示

- 变化：用户要求门户上传成功时，如果本次文件前方已有 queued 任务，用一条 success Toast 显示本次非重复成功文件数及最靠前文件的当前 `X/Y` 名；无排队或位置不可用时继续显示“上传成功”。
- API 影响：位置响应新增向后兼容的 nullable `waiting_count`，口径为 high/medium/low 三级 waiting ZSET 的 queued ticket 总数，不包含 publishing/processing，不暴露其他任务身份。
- 可靠性边界：名次和总数仍是近似瞬时快照；若查询失败、缺少可靠 queued item 或出现 `Y < X` 的并发不一致，Client 不展示名次并安全降级，不阻断上传主流程。
