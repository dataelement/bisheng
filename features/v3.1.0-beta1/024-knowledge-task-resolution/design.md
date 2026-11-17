# 失败任务处理候选设计（待确认）

状态：供确认的设计，不表示已经实现或可直接用于生产。基于 ed1062e82a；真实证据见 116-task-failures.md。遵守 constitution C1–C8；特别保持租户、权限投影台账、异步幂等和双 DB 约束。

## 1. 现状及不能直接取消的原因

- task.state 只有 accepted/running/succeeded/partial_failed/failed/obsolete，API 仅查询/重试，没有取消/回退。
- move 先在 SQL/权限层变更归属，再异步处理索引。space_copy 先创建空间和占位记录，再权限确认/初始化/内容复制。processing_item.succeeded_count 只代表异步 item，不能表达全部业务进度。
- SourceMoveInputRepository 对消费过的 move/space_copy 计划检查源输入；只有任务及全部 item 完整成功才通过。失败不会自动释放。
- 116 的移动目标 4394 是已有失败复制任务的目标；移动失败时目标 ES 不存在，后来才创建。复制 4410 则在 Root 权限投影 FINALIZED 后，被来源标识的格式差异校验阻断。

## 2. 决策与备选

1. 选择两个明确动作：放弃后续处理保留完整结果；整体回退撤销本任务结果。否决单一“取消”按钮同时承担两种含义。若用户本期不选回退，可缩小范围，但不能暗中改成回退。
2. 第一版处理失败/部分失败且可停稳的 copy/move；有活跃 lease/分派时先阻止新执行并等待在途执行到检查点。否决修改 failed→succeeded 或删计划，因那会绕过源输入保护且丢失审计。
3. 回退只针对任务冻结的确切资源集合，并在所有前置检查通过后确认；后续编辑/引用/权限/索引代次冲突则拒绝。否决全空间快照覆盖，因为会损失其他操作。
4. 放弃也必须完成善后和原始文件可读验证。未完成的复制占位不能当成果保留；移动保留归属但索引未就绪时需明确待重新解析。源保护只依赖 owner 发出的持久完成证据，不依赖 UI 状态。

## 3. 数据与接口候选

- knowledge owner 新增任务处理应用；使用原 operation plan 的 precheck→confirmation_id/plan_digest/idempotency_key→异步执行模式。precheck 必须冻结 mode、job revision、claim generation、scope manifest、源/目标当前事实、权限和索引代次、影响及冲突。
- 候选接口：GET job 的阶段进度；POST job/resolution-precheck；POST job/resolution；GET job/resolution。路径继续位于对应 space 的 processing-jobs/{job_id} 下，不在前端直接写旧任务表。
- 处理记录使用独立持久表，记录原 job、方式、操作者、冻结快照校验值、执行/清理检查点、幂等键及审计结果；按 SQLModel owner 建表规范及 MySQL/DM8 验证，不能藏在日志或本地文件中。
- 原任务保留原 failed/partial_failed 及历史错误，不扩展旧 job.state 枚举。处理记录区分 pending/running/failed/completed，结果区分 abandoned/rolled_back；同租户同原任务只允许一个已确认处理记录，方式冻结，失败只能恢复同一次操作。读取接口在兼容原错误的基础上增加 resolution 与 phase_progress。scheduler、retry 和 worker 都检查该记录及执行代次，不让旧 worker 将处理后的任务重新排队。
- source guard 只接受同租户、同 job/plan/manifest、处理记录完成且源依赖已清理的 owner 释放凭据。普通 failed/obsolete、SQL JSON null、无效记录均不能释放。同步及异步删除路径保持同一规则。
- 删除预检返回结构化 blockers（operation、stage、state、counts、诊断、受控查看入口）；通过现有权限 owner 做详情披露。无权任务只计受限依赖，不向删除者泄露目标名称或原始异常。

## 4. 执行流程

1. 准入：当前租户、任务查看/处理资格及实际源/目标动作权限；冻结 preview，检查 job 状态和在途执行。
2. 确认：原生事务锁定 job/处理记录以及源/目标根，重读冻结事实并提升执行代次/关闭分派；旧 lease 后续检查点、完成和重试必须拒绝。仅 lease 过期不足以证明外部写已停止，执行 fencing 与每步 guard 一起生效。
3. 执行期间使用持久处理占用，源/目标空间的写入 owner（上传、改名、元数据、版本、移动、删除等）统一检查并拒绝冲突写；浏览和原始文件下载保持。只锁处理涉及的两个空间，不扩大到租户；按固定顺序锁根避免死锁。不能仅在清理器内检查快照而让其他写入口绕过占用。
4. 放弃：逐资源核对完整结果；复制移除本任务未完成占位/权限/对象/索引残留，保留完整副本；移动保持归属并验证原始对象可读、标明索引未就绪，清理不再使用的源索引/引用。所有写走各 owner 的台账，不在 application 直接跨模块 SQL/FGA。
5. 回退：确认全部资源无冲突后，移动按冻结原位置/关联/权限恢复并核对源索引与目标残留；复制按任务确切映射移除副本，只有确为本任务创建且未被后续使用的新空间才随回退删除。后续空间配置/其他文件变更保持。
6. 外部对象/索引/权限的每步都写持久检查点并读回核对，失败恢复同一次处理；完成后签发源输入释放事实，更新读取摘要及审计。清理失败继续阻断源空间删除。

## 5. 阶段进度

按逻辑变更、权限确认、原始内容、目标索引、源清理分别展示计数及状态。计数来自 acceptance manifest、当前受验证 SQL、投影 receipt 和 item checkpoint；completed job 的单一 succeeded_count 不作为阶段进度来源。历史事实不足显示“无法确认”。前端文案不使用 lease/receipt 等内部词。

116 例：移动已变更归属 2/2、索引迁移 0/2、源清理 0/2；复制已创建文件记录 30/30（另有一个文件夹），内容复制 0/30、权限确认失败。Root 权限 FINALIZED 不代表整个复制树权限已完成。

## 6. 根因修复候选与验证

- copy：原始 source_ref/source_fingerprint 不能直接与目标拷贝后规范化值比较。由 permission owner 复用既有复制来源规范化规则，按目标语义验证预期授权，同时保留冻结 plan/delta、保护所有者、CURRENT 状态和校验和的严格核对；不是删除校验。补历史格式→新格式、自定义/继承模式、额外授权、丢失授权、错误所有者及重放回归。
- move：预检识别失败复制保留目标，直接拒绝向该未完成副本移动；正常空空间若需要初始化，将其作为确认后的首个阶段，由知识 owner 完成模型/schema/索引初始化并验证之后才变更归属。预检自身不写外部数据。worker 不静默造空索引掩盖源数据缺失；初始化失败时文件仍在源位置。
- 错误记录：保留稳定阶段/原因字段；日志中的底层异常经过受控映射给用户，不直接暴露堆栈、索引名或服务器地址。

## 7. 验证与交付边界

需要真实 race/fence、重复确认、部分失败恢复、源/目标后续修改、授权撤销、restricted blocker、MySQL/DM8 与外部索引/对象/权限联调。现有 source_move_input 测试保留，并增加凭据缺失/篡改/错租户及有效放弃/回退释放矩阵。代码未实现前不能声称任务可放弃或整体回退。

确认 spec/design 后读取 QA 八列表模板并生成 test-cases.md、拆分 tasks，再实施和验收；116 的实际处置仍独立授权。
