# T053 外部单文件标签契约

这是 BiSheng v1 本地接线契约，不代表已有部署具备该能力。以下地址均相对于 `/api/v1/knowledge/space/{space_id}`；响应示例指标准 v1 成功 envelope 的 `data`。三种请求都必须固定代次，普通读取不要求文件编辑权限。

| 请求 | 输入 | 成功 `data` |
| --- | --- | --- |
| `GET /provider-tags` | `generation`；`page` 从 1 起，`page_size` 1–200（默认 50） | `{data:[{tag_ref_id,name}],total,generation}`；`total` 是词条数，不是文档使用量 |
| `GET /files/{file_id}/provider-tags` | `generation` | `{tag_ref_ids,revision,generation,edit_contract:"manual-tags-v1"}`，仅该文件人工来源，未选时为 `[]` |
| `PUT /files/{file_id}/provider-tags` | `{generation,mode,tag_ref_ids,expected_revision}` | 与文件 GET 相同，表示本次 CAS 的结果；不是事后再读的另一次编辑 |
| `GET /files/{file_id}/provider-tag-labels` | `generation` | `{names:string[],generation}`，仅用于列表展示；只读，不返回引用身份 |

- `replace` 要求 1–50 个不同的本地安全整数 ref；`clear` 必须显式传 `[]`，不会清除自动来源。浏览器不得传远端 ID、库 ID 或版本 ID，`revision` 是与绑定、文件版本、操作 epoch 和实际标签修订关联的不透明安全整数，只能原样回送，不做递增运算。
- `status_code=10998` 表示已读方案或修订冲突（含换代、过时的 ref、写槽冲突）。重新读取并让用户复核，不自动重试覆盖。`18089` 是无法安全提供（包括旧实例、不匹配的回包、无法判定远端结果），不是“没有标签”。判权拒绝保留原业务权限错误。按业务码分支，不假定 v1 传输层错误状态。
- 词表通过绑定实例的 `GET knowledge-bases/{kb}/tags` 真分页，仅接收目标租户/库匹配的词项。不转发 `seq_id`、远端标签身份、文档及块计数。文件读取、写入分别检查空间可见和文件 `visible` / `rename` 权限，且只处理当前有效的主版本映射。
- 文件读写仅使用绑定实例的 `knowledge-bases/{kb}/documents/{doc}/manual-tags-v1`。写前先 GET 检查契约名、租户、库、文件、人工标签快照和修订；拿到共享写槽后再校验本地权属、权限、版本与代次，PUT 携带**远端实际修订**。不回落到 `/knowledge/tags`（旧版本可能忽略修订），也不把旧详情的 `tags:null` 当成 `[]`。无法证实写入结果时保留共享写槽，不伪造成功或自动重发。

## 列表每行标签（2026-11-26，经产品确认）

目录列表本身仍不带 `tags`：上游没有"按文档批量取标签"的接口（`GET knowledge/batch` 不填充 `Tags`，`Tags` 是 `gorm:"-"`），整页补全等于每行一次慢远程调用。因此新增**按需**单文件读取，只在用户点开某行的"查看标签"时发一次请求：

- 读 `GET knowledge/{doc}`，与整组契约同样的 `id`/`knowledge_base_id`/`tenant_id`/`tags` 校验（`tags:null` 视为空集）。
- 返回只含 `names`：名称仅用于展示，不是身份，不能回传为标签引用。
- 权限为该文件 `visible`；不要求 `rename`，也不申请写槽。
- 该接口同时兼容两种上游：`manual-tags-v1` 与 `whole-tags-v1` 模式下人工与自动标签都在同一关系表内，详情接口都能取到名称。

## 偏差记录（2026-11-26，经产品确认）
**变更：** 当上游对 `manual-tags-v1` 返回 404/405（专属路由不存在，例如 v0.9.0 原版镜像）时，改为使用整组契约 `whole-tags-v1`，不再直接拒绝。这是对上面“不回落到 `/knowledge/tags`”的显式推翻，原因是当前部署无法运行扩展版上游。

- 读取走 `GET knowledge/{doc}`，校验 `id` / `knowledge_base_id` / `tenant_id` 与绑定一致；`tags` 字段缺失或非数组一律拒绝。该版本把“没有标签”序列化成 `tags: null`（Go nil slice），因此 `null` 只在整组契约下按空集处理——否则新文档无法加第一个标签；上游标签联表查询失败时同样返回 null，这一点从响应无法区分，属于本降级的已知残余风险（上游会记录告警日志）。
- 写入走 `PUT knowledge/tags`，body `{kb_id, updates:{doc:[tag_ids]}}`，语义是**整组替换**；写前在同一共享写槽内重新读取并比对浏览器回送的修订令牌，不一致返回 10998，不重试覆盖。
- 修订令牌是同文档快照内容的本地哈希（`whole_revision`），不是远端修订；上游本身不做 CAS，因此这只能拦住“读后被别人改过”的窗口，不能阻止两端同时写。
- 不回送远端标签身份；本地 `tag_ref_id ↔ remote_tag_id` 映射与人工/自动来源的区分在上游不存在，故该模式下**选中的集合就是文档最终整组标签**，可能包含自动标签；前端必须明确提示整组写入。
- 能力表条目 `tag_edit` 仍为 `conditional`；响应中的 `edit_contract` 区分 `manual-tags-v1` 与 `whole-tags-v1`，调用方据此决定是否提示降级。

## 验证边界 / 缺口

当前证据是上游开发源代码的专属路由和 BiSheng 本地定向契约回归；不是已部署的 WeKnora、生产密钥、真实非管理员双账号或浏览器联调验证。外部编辑能力只能是 `conditional`；老版本、无专属路由或不能证明手工标签快照时拒绝。仅证明标签读取不代表有写权限。词表浏览、单文件编辑也不证明**目录列表**拥有按标签过滤或每行标签能力；目录过滤未接线时不可复用 Native 参数或冒充全库结果。本改动不涉及建词/删词、模板导入或批量编辑。
