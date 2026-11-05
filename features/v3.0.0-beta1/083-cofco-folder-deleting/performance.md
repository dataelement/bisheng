# 大量文件夹删除后的刷新耗时：只读排查记录

日期：2026-11-04。范围：本地代码及客户提供的录屏阅读；未访问客户服务器、未执行删除、未查询客户数据库。

## 结论与本期边界

代码能够确认：删除工作量随子树及版本数量增长；删除成功会触发当前文件列表和左侧展开树刷新；后台清理完成前，列表还需要读取本空间的删除可见性记录。客户录屏已确认缺少删除中反馈及长时间列表加载的现象；尚未独立复现，也没有请求耗时或实际日志，不能宣称已找到刷新慢的根因。

第一阶段仅处理前端删除中的提示和操作限制。2026-11-05 用户追加要求在设计中覆盖刷新持续 loading：已补入 design.md §5.4，包含刷新策略和读取超时；具体后端性能补丁仍待实际耗时证据及确认。已确认慢发生在客户环境，客户数据量大；未提供具体空间、目录、规模或请求日志，本地 105 不能作为实测替代。

## 已确认链路

以下代码路径以仓库根目录为基准，行号为本次阅读时的定位辅助。

| 环节 | 代码证据 | 已确认行为 |
| --- | --- | --- |
| 单个目录删除入口 | `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py:681` | 先构造文件变更命令，再按权限、空间策略决定直接删除或进入审批。不是所有删除请求都会立即删除。 |
| 当前批量删除入口 | 同文件 `:858`；`src/backend/bisheng/knowledge/domain/services/knowledge_space_file_change_service.py:203` | 批次逐项等待处理，每项成功拥有自己的提交；整个批次返回前，前端无法从此响应获得逐项进度。旧的 `KnowledgeSpaceService.batch_delete` 不是当前前端批删入口。 |
| 子树授权 | `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:713`、`:3549`；`src/backend/bisheng/knowledge/domain/services/knowledge_space_direct_delete_service.py:68` | 目录删除会查询子树并逐资源检查删除权限；直接删除事务展开正式删除清单后，再检查清单中的资源，包括扩展出的版本。 |
| 同步删除准备 | `src/backend/bisheng/knowledge/domain/repositories/knowledge_space_mutation_repository.py:309`、`:377`、`:754` | 锁定空间及子树记录，查找版本关系；按涉及的文档逐次查询版本链，并生成删除清单。不能仅用顶层所选目录数量估计工作量。 |
| 数据库切换 | 同文件 `:517`；`src/backend/bisheng/knowledge/domain/services/knowledge_space_direct_delete_service.py:68` | API 事务内删除正式文件、文档及版本关系，写入持久删除账本和 footprint，再提交。 |
| 后台清理 | `src/backend/bisheng/knowledge/domain/services/knowledge_space_direct_delete_service.py:165`；`src/backend/bisheng/worker/knowledge/file_change_tasks.py:199`；`src/backend/bisheng/knowledge/domain/services/knowledge_space_mutation_executor.py:1077` | 提交后派发 Celery，清理 FGA、MinIO、ES、Milvus，并验证残留。API 不等待这些清理全部完成；不能把 API 等待直接解释为同步删除对象或向量。 |
| 前端刷新触发 | `src/frontend/client/src/pages/knowledge/hooks/useKnowledgeFileMutations.ts:104`、`:143`；`src/frontend/client/src/pages/knowledge/hooks/useFileManager.ts:372` | 直接删除成功后更新本地行；目录结构变化广播刷新事件，当前文件列表重新请求第一页。审批待处理项也会触发刷新以更新标记。 |
| 列表等待表现 | `src/frontend/client/src/pages/knowledge/hooks/useFileManager.ts:110` | 第一页刷新先清空当前列表，再等待请求结果；这会让网络或后端等待直接表现为列表加载状态。 |
| 左侧展开树刷新 | `src/frontend/client/src/pages/knowledge/sidebar/KnowledgeFolderTree.tsx:356`、`:374`；`src/frontend/client/src/api/knowledge.ts:1543` | 同一事件还会重取根目录，递归请求仍然存在且之前展开的节点。兄弟节点并发，层级间等待；树请求也调用 children 接口，带 `file_type=0`。 |
| children 查询 | `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:2973`、`:3176` | 游标获取候选项，按可见权限过滤直到凑够一页或数据耗尽，再补充版本、标签、目录后代状态及审批信息。当前 children 不计算精确总数。 |
| 删除后额外可见性读取 | 同文件 `:5536`；`src/backend/bisheng/knowledge/domain/services/knowledge_space_deletion_guard.py:40`；`src/backend/bisheng/knowledge/domain/repositories/knowledge_space_file_change_footprint_repository.py:387` | children 读取本空间尚未完成清理的删除 footprint，再按相关请求读取完整 checkpoint 判断切换标记。已避免每个 footprint 重复加载同一 checkpoint；但仍需读取每个相关请求的 checkpoint，其中包含删除清单。清理完成事务会退役 footprint，见 `knowledge_space_mutation_executor.py:1020`。 |
| 数量统计边界 | `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:1743`；`src/backend/bisheng/knowledge/domain/models/knowledge_file.py:285` | `/info` 会统计空间内成功文件数量；不能据此断言删除后的 children 刷新在等待 COUNT。是否同时发生 `/info` 请求需要实际网络记录确认。 |

## 待验证假设

1. **慢在删除请求，而不是刷新请求。** 逐项处理、子树授权及版本链准备可增加响应时间。需分别记录 delete/batch-delete 返回时间和随后 children 时间，区分两个阶段。
2. **后台清理积压使删除可见性读取变重。** 大量尚未清理完的 footprint 及请求 checkpoint 会增加 children 的读取、JSON 解码和过滤工作。需对比同空间后台清理完成前后 children 耗时及未完成规模；这是关联假设，不是已证实瓶颈。
3. **刷新树增加并发请求或串行层级等待。** 展开节点越多，树恢复需要的请求越多。需记录发起方、`parent_id`、开始/结束时间，并对比主列表是否先完成、树是否仍在加载。请求多不等于服务器一定已被拖慢。
4. **列表候选扫描、权限判断或后代状态补充占时。** 代码已有对应分阶段日志。需用实际耗时区分数据库、权限和补充信息；不能仅凭复杂查询形态断言缺索引或锁等待。
5. **清理任务与 API 共享资源产生竞争。** 需要实际资源、数据库等待或任务时间证据；当前没有证据证明竞争、锁等待、连接池耗尽或某个外部存储是根因。

删除账本按“尚未完成的清理工作”读取，并非无条件遍历全部历史删除请求。不得将其描述成永久随删除历史增长。

## 已有观测字段

指标通过 `BS_METRIC` 输出，是否存在实际记录取决于环境配置及日志保留情况；没有日志不能视为耗时为零。实现入口为 `src/backend/bisheng/common/services/metric_log.py:81`。

| 指标域 | 可使用字段 | 可回答的问题 |
| --- | --- | --- |
| `knowledge_space_children` | `space_id`、`parent_scope`、`page_size`、`system_scope`、`status`、`returned_count`、`has_more`、`total_elapsed_ms`；`auth_elapsed_ms`、`cursor_elapsed_ms`、`version_filter_elapsed_ms`、`scan_elapsed_ms`、`version_enrich_elapsed_ms`、`extra_info_elapsed_ms`；错误时 `failed_stage`、`error_type` | 慢请求主要发生在哪个阶段。注意 `parent_scope` 只分根/目录，不包含具体目录 ID；与网络记录对齐时仍需时间及请求上下文。 |
| `permission_visible_list`（`resource_type=space_child`） | `candidate_count`、`visible_count`、`scanned_candidates`、`returned_items`、`scan_amplification`、`batch_count`、`db_elapsed_ms`、`permission_elapsed_ms`、`total_elapsed_ms`、`target_build_elapsed_ms`、`permission_decision_elapsed_ms`、`verified_target_count` | 是否扫描多批候选、是否权限阶段主导。不要把同时间窗口内其他请求的扫描日志误配给目标请求。 |
| children 权限上下文 | `actor_resolve_count`、`actor_cache_hits`、`actor_resolve_elapsed_ms` | 权限主体构建是否重复、耗时多少。 |
| `knowledge_space_info`（仅实际发生 `/info` 请求时） | `space_id`、`total_elapsed_ms`、`file_count_elapsed_ms`、`member_count_elapsed_ms`、`auth_elapsed_ms` 等分阶段字段 | 文件数量统计是否真的占用本次页面等待时间。 |
| `db_query` / `db_query_agg` | 慢查询的 `op`、`elapsed_ms`、`status`，以及聚合直方图 | 支持判断数据库是否慢；这些指标自身没有 SQL 文本，不能单凭它们定位某条查询。 |

当前阅读范围内未发现 delete API 与所有清理步骤均有统一的专用分阶段性能指标。应优先使用现有网关/访问日志、浏览器网络时间，以及已有 Celery 开始/结束记录；缺失则标注“缺数据”，不要填估算值冒充实测。

## 建议只读采样清单

只分析用户已经发生的操作或自然产生的请求，不为了复现额外删除数据，也不改日志配置、重试任务或清理记录。

- 环境与样例：用户确认的环境、空间 ID、目标目录 ID、目录深度、顶层所选数量、子目录数量、文件数量、涉及版本数量。未知数量记为未知；如需查数据库，仅在确认环境和权限后以租户与空间限定的只读方式取聚合。
- 删除阶段：操作时间和时区、单删/批删、直接删除/待审批/失败结果、HTTP 状态、delete 或 batch-delete 总耗时。待审批结果要单独记录，不能与实际直接删除混算。
- 刷新阶段：随后每个 children 请求的开始/结束时间、耗时、`parent_id`、`file_type`、分页大小、发起方（右侧列表/左侧树）、返回项数量。分别记录第一项可用、主列表可用和树恢复完成的时间。
- 服务端阶段：同时间窗口内上述 children 和权限扫描指标；若有 request/trace 关联标识则保留无敏感内容的关联 ID，否则明确关联精度限制。
- 后台阶段：关联删除请求的内部 ID、Celery 排队/开始/结束时间、重试次数与结果；若已有清理步骤时间，分别记录 FGA/MinIO/ES/Milvus。没有逐步骤日志时只记可证实的总任务时间。
- 后台完成前后对照：同一空间、目录范围、分页条件、用户权限及展开状态，采样现有请求耗时；同时记录未完成清理的请求数及 footprint 数量。不能将不同数据规模或权限下的请求直接当作对照。
- 账本时间辅助：若授权只读查询，可只提取 checkpoint 中的 `cutover_completed_at`、`purge_completed_at` 与执行状态。两者差值是切换后到清理结束的总历时，含排队/重试，不等于纯工作耗时。

采样材料不包含 Cookie、Authorization、密码、execution token、文件正文、对象路径、完整 checkpoint 或删除清单。导出网络信息时只整理上述字段，不直接提交带认证头的原始 HAR。

## 下一步判断标准

先区分“删除尚未返回”和“删除已返回但 children 慢”，再用 children 分阶段指标定位。只有取得实际证据后，才提出具体性能方案并单独确认实施；本记录不授权或实施性能改动。

## 客户录屏证据（2026-11-04 补充）

用户指定下载目录中的两段录屏。仅在本机解码查看，不上传视频，不操作客户环境。
时间来自关键帧采样，为画面时间而非接口耗时。

- `录屏2026-11-02 10.53.45.mov`，时长约 14.87 秒：约 3–4 秒出现删除确认弹窗，约 5 秒弹窗关闭；目标目录仍显示普通行，没有删除中反馈。随后用户能进入该目录并看到子项，再返回上层时目标目录仍在。录屏内未看到能确认删除完成的明确提示，不能将“弹窗关闭”当作“接口成功”。
- `录屏2026-11-02 10.56.40.mov`，时长约 41.31 秒：录制开始时主列表已在加载，直到约 19.3 秒采样画面仍未展示列表；约 22 秒画面中用户已切换其他空间，后续多次切换及返回时仍可见加载。只能确认录屏可见范围内约 20 秒持续等待，不能据此计算完整请求时长。

两段视频分别支持“删除中缺少反馈且仍能打开目录”和“列表加载长时间等待”的现象。
视频没有网络面板、请求标识或服务端日志，无法证明第二段等待由第一段删除引起，
也无法区分后台清理资源竞争、删除可见性查询开销、权限查询或其他请求等待。
后续以客户同时间窗口的 children / 删除请求日志及现有性能指标交叉确认。

## 105 并发上传／删除现象（2026-11-05）

用户在上传可能尚未完成时手动测试删除。报错请求为删除空间 142 中的目录 2874，
返回 `F046 delete resource not found: 2874`。使用用户提供的会话，仅执行只读核对：

- 本地 Vite 代理和 105 直连的 children 响应一致：同名测试目录仍在，但 ID 为 **4476**，并非 2874；响应 `has_more=false`。
- 目录 2874 的 parent 接口返回 18020（目标不存在）。不能仅凭此断言整个同名测试目录删除成功。
- 代码证据：`execute_direct_file_change` 的 upload 分支逐个登记文件，每个文件沿相对路径查目录，目录缺失就调用 `add_folder` 重建。批次由 `request_changes` 逐项 await，并非整个文件夹原子登记。

因此，上传批次未完成时并发删除，后续文件可能重建同名目录，产生新的 ID。
该逻辑可以解释“旧 ID 删除报不存在、列表仍有同名新目录”；具体本次请求的先后顺序
及谁先移除 2874，仍需服务端请求／删除账本日志确认。前端本页删除锁不能代替后端
上传批次与目录删除的并发约束，也不能跨标签页阻止已有上传。未重放 DELETE、未改后端。

## 2026-11-05 诊断日志增量

按用户要求已补 loading 排查日志，使用原追踪 ID；覆盖列表/搜索的开始、关键阶段及结束，并细分删除可见性数量与耗时。客户端只添加固定来源请求头。没有增加数据库查询，也未实施读取超时、列表刷新性能调整。使用与采集条件见 [loading-log-guide.md](./loading-log-guide.md)。
