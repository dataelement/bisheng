# F118 实施接口合同 V1

**状态**：2026-11-05 冻结；按已确认 spec/design 落实为实施合同。以下新 API/模块是待实现合同，不代表部署已提供。破坏性修改必须先更新本文件并通知全部消费者，由 INT 调整依赖；不得各 agent 私改字段。

## 0. 基线与实施约束

- 功能分支：`codex/3.1.0-beta1/118-knowledge-space-unification`。
- 已评审文档检查点：`0b80802ae`；远端发版线 `9eef0016de5e48fb6a35c7d09e4573adcb09f4a9`；合并后源码基线 `a1b1a2387949950eafe17679810f2df8eabae10b`。保留全部本地/远端提交；主工作区未改。
- 版本契约冲突已逐块合并，保留 F004 与 F118。F004 工作流软删除成功时解除有效来源绑定，保留历史行本身不意味着继续保护已删业务。
- 各 lane 从本合同冻结提交创建独立 worktree，业务代码先测试后实现。主 agent 唯一合流、共享入口、结构迁移与验证 Owner；分支不自动推远端。
- 正式迁移只在运维停服及一致备份后盘点冻结基线；脚本不检查/控制停服。迁移和真实双库/E2E 尚未运行。
- 所有源文件所有权及叶子例外见 parallel-development；实际源码发现的遗漏先追加任务，不能扩大同文件并发写入。

## 1. 共通线协议与错误

新接口沿用 `UnifiedResponseModel(status_code,status_message,data)` 和 `resp_200`；新增页为 `PageData(data,total)`，旧分页/envelope不替换。契约中 ID 均为真实稳定 ID；Reference内部规范化为十进制字符串，HTTP既有数字ID仍用数字，不混用file/document/version。

以下错误码已扫描全量 common/errcode 和 api_errors 源确认未占用，INT负责声明及三语源同步。v1保持原错误envelope；v2通过原handler返回真实http_status，错误对象应声明下表status。`data.reason`是稳定机器枚举，不解析人类message判逻辑；不得返回秘密或无权依赖名称。

| Code | 类名 | HTTP / 用途 |
| --- | --- | --- |
| 10994 | ReferenceCoverageNotReadyError | 503，引用覆盖未就绪/检查无法完整完成 |
| 10995 | ResourceReferenceConflictError | 409，普通有效引用阻断；确认范围变化保留reason |
| 10996 | ResourceReferenceInvalidError | 409，失效目标/来源修订冲突，按reason区分 |
| 10997 | KnowledgeProcessingObsoleteError | 409，相关业务配置/索引过期；J1中的JobObsolete名称统一此类 |
| 10998 | KnowledgeOperationPlanConflictError | 409，引用删除计划/锁集合不匹配 |
| 10999 | KnowledgeProcessingConflictError | 409，活跃任务/操作冲突 |
| 18082 | KnowledgeProcessingSettingsConflictError | 409，默认配置CAS失败 |
| 18083 | KnowledgeProcessingJobNotFoundError | 404，任务不存在或不可见统一响应 |
| 18084 | KnowledgeProcessingJobNotRetryableError | 409，当前状态不允许retry |
| 18085 | KnowledgeIdempotencyConflictError | 409，同键异规范请求 |
| 18086 | KnowledgeOperationConfirmationRequiredError | 409，需要确认，零资源修改 |
| 18087 | KnowledgeOperationPlanChangedError | 409，确认后影响变化，重新确认 |
| 18088 | KnowledgeOperationPlanExpiredError | 409，计划过期 |

错误码不在普通运行时自动注册或变更Catalog；当前v1错误响应保持原transport语义。已有权限、参数、配额和审批错误继续复用。

### 结构与并发统一字段

- Knowledge新增 `processing_defaults` (nullable JsonType)、`processing_config_version` (non-null int default0)、`model_config_revision` (non-null int default0)、`index_generation` (nullable string64)、`migration_origin` (nullable string64)。DDL只加结构/default，不跑数据转换；M2/M3账本按原计划初始化既有索引代/迁移来源，重跑不重新生成。
- 默认配置版本只追溯解析快照；相关model_config_revision随模型配置替换单调递增，A→B→A不能复活旧任务。index_generation独立，名称/说明与默认策略保存不使已启动任务过期。
- 幂等请求hash包含可信tenant/actor、kind/space及规范参数和实际范围，不能以同key让他人读取任务；job唯一键按J1，同键不同可信上下文/请求冲突，重投仍重新鉴权。
- 引用Source/Target DTO不公开任意CRUD。R2双入口无内部commit/begin/rollback，所有收据绑定当前SQL事务；零引用集合和根守卫含义按R1。
- SQLModel新增整表自动发现；既有表DDL由MIG唯一编排。当前Alembic单头已核对 `v310b1_f004_workflow_soft_delete`，新revision须再次核对后串接，不照文件名猜父链。

## P1：全平台 use 退役与纯可见授权（V1 合同）

### 数据与类型

以下是服务端拥有的发布元数据；HTTP `CatalogChangeRequest`、GrantMutationRequest 不增加可由调用者设置的纯可见开关。

```python
# 新增于 CustomModelSelection / DerivedPermissionModel / PermissionModelDTO
visibility_only_resource_types: tuple[str, ...] = ()
visibility_level: int | None = None  # 1..4，bool 不接受

# 新增于 GrantModelSnapshot；保留原 model_key / active / action_codes /
# derived_level / allow_same_level，不重命名原字段。
visibility_only_resource_types: tuple[str, ...] = ()
visibility_level: int | None = None
visibility_only: bool = False  # 由具体目标上下文派生；不从 HTTP 信任
```

- `PermissionModel`（`domain/models/catalog.py`）持久化前两字段：types 用 dialect `JsonType`（只保存/加载完整列表，不 JSON 查询），level 用 nullable Integer；旧行 null 归一化为 `()/None`。既有表 DDL 归 MIG，PERM 不动 Grant/Source 表。
- types 为已注册资源类型、唯一、排序后的 tuple；每个被标记类型，移除 use 后的**该类型有效具体动作集合**必须为空。不存在 marker 或 level、类型非法、level 不在 1..4、普通任意空模型均拒绝作为合法纯可见模型。
- level 冻结原有效管理等级，不默认为 1。标准模型固定等级维持；普通非纯可见 custom 继续按有效动作最高等级派生。
- `model_key`、Grant ID、Source ID/fingerprint/locator/type、scope、主体、protected 标记不变；不扁平化部门/用户组、不复制为逐用户授权。
- `GrantModelDTO` 补只读 `visibility_only: bool = False`；`level` 给出**此目标的管理等级**，当前 active 标识保留。`PermissionModelDTO` 给出发布元数据（types/level），不以空 action_codes 隐藏合法模型。

### 目标化快照规则

统一纯函数的建议签名（正式代码可置于 permission 域，应用层必须调用同一函数）：

```python
def model_snapshot_for_target(
    model: GrantModelSnapshot,
    *,
    resource_type: str,
    applicable_action_codes: tuple[str, ...],
) -> GrantModelSnapshot: ...
```

`applicable_action_codes` 必须由当前 Catalog 的 action resource scopes 计算，不能由客户端提供。目标属于合法 marker types 时，返回 `visibility_only=True`、该目标 `action_codes=()`、`derived_level=visibility_level`；否则返回当前类型适用动作、原非纯可见等级。GrantMutationContext.models、操作者 capabilities、已有 roster 及 grantable/manageable DTO 均来自同一规则。全局还有 `download` 的模型可能对 tool 是纯可见、对 file 有 download，不能按全局 action_codes 是否为空猜测。纯可见主体没有 manage_permission，不因此成为可管理其他授权的操作者。

### 授予、列表、撤销与投影

- ADD / MOVE 目标模型：`active and level in 1..4 and (target actions nonempty or valid visibility_only)`；管理者仍满足原 manage_permission、等级/同级及 protected/source 限制。
- REMOVE 原来源：允许合法已存在模型 inactive；仍需可管理模型等级和原来源管理准入，不能以 `not action_codes` 拒绝。撤销 S1 只减 S1 的贡献；其他直接/部门/继承/系统 Source 保留。原 Grant 仍可沿 model_key 找到并撤销。
- `GrantSourceService._ensure_target_model` 同样识别合法纯可见；只放开受控标记模型，不放开任意空模型。
- 可见性继续由已有 active Grant/Source 编译为 `visible` 投影贡献。纯可见模型不产生具体 `can_*` 动作；Grant 的 model 关系、Source provenance 维持，复用 prepare → atomic projection → SQL finalize 及原幂等/修复协议。
- tenant 全员 tool/Skill 模型选择改为**当前目标合法纯可见模型**（含混合全局动作但本类型纯可见），原 tenant predicate/Source/fingerprint 保留；不再寻找包含 use 的模型。全新安装的 bootstrap 由服务端内置标准合同初始化 viewer 的纯可见类型和固定等级；已有安装由停服 M2 冻结迁移原 metadata。两者都不是客户端可造的空模型。

### Catalog、checksum 与活动动作

- 当前 Catalog 注册动作、model selected/effective action_codes、API 当前动作响应和新 FGA 模型中没有独立 `use`/`can_use`。`visible` 保持原可见性协议，不作为新的可分配具体动作。
- 旧固定协议的 use/use_kb 仅在兼容边界解释为 visible；历史发布、审计原文保留。遗留名字为 use 的技术字段若保留仅为过渡读取，不得贡献独立授权或绕过 visible。
- model canonical payload/checksum 包含排序 types 与 level（含空/None 的规范表示）；Catalog draft/read/persist/load、runtime current_catalog、model/Grant DTO、impact/commit checksum 必须同一轮贯通。迁移冻结原/新 checksum，不把旧 CURRENT 当新模型静默放行；受控旧基线读取不能走已要求新模型的生产权限 Context。
- ordinary Catalog HTTP 不接收 marker 字段；编辑已标记模型时，服务端保留/验证既有 marker，标记类型一旦出现具体动作则不再按纯可见目标派生，不能追加任意新类型。内置 bootstrap/显式升级发布负责 marker 的合法产生。
- 当前操作 rename 保持文件/文件夹 rename；edit 不扩到 file/folder。高级 Chunk/metadata/reprocess 原容器 edit；已有 retry/tags/encoding 原 rename，其他业务/tenant/scope/状态检查维持。

### 真实接线点与缺口

后端路径前缀为 `src/backend/bisheng/`。

| 文件 / 位置 | 当前事实与必须接线 |
| --- | --- |
| `permission/domain/schemas/f048.py:157` / `:306` | PermissionModelDTO / GrantModelDTO 缺新只读元数据；StrictRequest 不开放 server-owned marker |
| `permission/domain/services/model_policy.py:49,149,200,299` | DerivedPermissionModel / canonical payload / custom derivation / effective_model_action_codes；空动作现在 derived_level=None，需合法例外与目标化 |
| `permission/domain/models/catalog.py:225` | PermissionModel 的真实持久化位置；**不是 grant.py**，需两字段既有表 DDL |
| `permission/domain/services/grant_source_service.py:35,371` | GrantModelSnapshot 与 _ensure_target_model 现拒绝空 actions，必须配套修改 |
| `permission/domain/services/grant_service.py:194,231,298,444` | grantable/manageable filters、全员 use-only guard、existing inactive revoke；改统一合法模型判定 |
| `permission/domain/services/visibility_projection_service.py:88,198` | 原 Source→visible 编译及聚合已存在；保持来源并集/撤销，测试纯可见不额外授动作 |
| `permission/application/control_state.py:163` | current_catalog 从 SQL PermissionModel 构造 GrantModelSnapshot，必须加载并目标化新字段 |
| `permission/application/catalog_api.py:850,909,1000` | _load_models / _replace_children / impact 重新派生模型、持久化和 checksum；必须全链路保留元数据 |
| `permission/application/runtime.py:349,861,891,899` | tenant_use_grant 与 Grant context / grantable/manageable 路径，必须使用 target-scoped snapshot |
| `permission/domain/services/catalog_policy.py:16,53` | 已注册 actions/scopes 含 use；需移除，rename/edit 原 scope 不变 |
| `core/openfga/authorization_model_f048.py:48,93,124,405` | FGA actions/scopes、system共享动作和资源关系有 use；新发布不能留独立 use 决策 |

测试优先复用 `test/permission/test_f048_model_policy.py`（旧空模型仍无效断言需保留并新增长标记合法空模型）、`test_inactive_model_existing_roster.py`、`test_f048_grant_api.py`、`test_f048_grant_subjects.py`、`test_f048_visibility_projection.py`、`test_f048_catalog_api.py`、`test_f048_catalog_runtime.py`、`test_f048_authorization_model.py`；新增 F118 配对测试按任务文件落 `test/knowledge_unification/`。必须有：use-only / 全局 download+本类型空 / inactive 原来源撤销 / 双来源撤一个 / tenant全员+全新安装 / catalog持久化往返和 checksum / 未标记空拒绝 / rename 不变 / 当前动作与FGA无use。


## REF V1：R1/R2/R3/B1/B2

核对基线：`a1b1a2387`，合入发版线 `9eef0016de`。以下是拟实现的内部应用协议；不是当前已存在代码，不新增通用依赖图、任务绑定或对外引用 CRUD API。

### R1 类型、键与集合

建议定义于 `resource_reference/application/contracts.py`，DTO 为 frozen dataclass 或 Pydantic `extra=forbid` 的内部只读结构。稳定字符串枚举：

```python
TargetType = Literal['model', 'knowledge_space', 'knowledge_file']
SourceType = Literal[
    'workflow_version', 'assistant', 'hosted_app_version',
    'channel_sync', 'knowledge', 'model_default',
]
ReferenceState = Literal['valid', 'deleting', 'invalid_deleted', 'invalid_legacy']
ReferenceSetKind = Literal['source', 'root_guard']
TargetDeleteStage = Literal['deleting', 'deleted']
```

- `SourceKey(tenant_id:int, source_type:SourceType, source_id:str, source_version:str)`：tenant>0；root/leaf 均是真实来源拥有租户，不取客户端任意 tenant。source_id 按业务真实稳定 ID 规范化，不放显示名。`source_version='current'` 表示单份可变业务；版本业务使用真实版本 ID 字符串，不用 latest。`'__root__'` 是内部保留键，普通提取器拒绝上报。
- `TargetKey(target_type, target_id:str)`：目前三类实体主键均为真实数值 ID，Owner 将其规范化为正整数十进制字符串；旧 type=0 的合法 ID 解析到同一个空间，不改变 ID。不用模型显示名、逻辑 document_id 代替真实目标 ID。folder 同样用 `knowledge_file` + 实际 folder 行 ID；版本选择规范化到实际 physical KnowledgeFile ID。
- `ReferenceSpec(slot_key:str, target:TargetKey)`：完整集合元素。slot 稳定按业务语义构造，节点 ID/字段路径，而不是数组下标。多选用 `(slot_key,target)` 集合；相同元素去重，不同槽同目标保留。
- `VerifiedReferenceTarget(key, target_tenant_id:int|None, target_space_id:str|None, model_server_id:str|None, state, target_revision, evidence)`：由目标 Owner 在当前事务按真实关系查询/加锁并验证。只有合法 legacy 证据路径允许 target_tenant_id=None；不能猜来源租户为目标租户。model 的 target_space_id=None；space 自身可为自己；file/folder 由真实归属派生。共享可用性仍由模型 Owner 检查。
- `LegacyEvidence(run_id, baseline_hash, evidence_key)`：仅内部迁移入口可注入，关联停服后、转换前冻结的正式基线；不接受 HTTP 提交，不伪造 tombstone。
- 规范化来源集合摘要：仅对配置身份元组 `(slot_key,target_type,target_id)` 按稳定字典序排序，以 UTF-8、JSON sort_keys=True、紧凑 separators 编码后 SHA256；digest算法版本固定 `sha256-reference-set-v1`。target_tenant_id/target_space_id、tombstone状态、legacy证据均为派生/核验元数据，单独对账，不混入配置摘要。文件移动只更新实际target_space_id，不改变来源配置/revision/digest；删除标记变更也不重写来源摘要。强删确认影响摘要另含目标归属/删除manifest与修订，不能复用配置digest忽略影响变化。

持久结构限已规划三表：`business_resource_reference`、`business_reference_set`、`resource_reference_tombstone`；MySQL/DM8 使用现有 dialect_helpers，显式列/关系/索引，不 JSON 函数或专有 upsert。候选长度 source_type32/source_id64/source_version64/slot_key192/target_type24/target_id64/hash64；channel 任意长子频道名和 APP name 通过业务稳定 hash 槽位，原显示标签从业务配置读，不撑大联合索引。最终 SQLModel 索引须两库验证。

集合唯一键 `(tenant_id,source_type,source_id,source_version)`；明细唯一键加 `(slot_key,target_type,target_id)`。源集合即使零引用也写 `record_kind=source`、revision、extractor_version、digest、effective/readiness。真实业务根同一 source_type/id 下的 `source_version='__root__', record_kind='root_guard'` 行保存根单调 revision；其不承载引用、不计覆盖/来源数量。根守卫同集合表实现，不增加各业务 root revision 列。

### R2 同事务 sync/async 双入口与持锁 receipt

历史写端同时有 sync Session 与 AsyncSession，自行开 Session 的旧 DAO 不能参与原子维护。两入口语义完全相同，不在 event loop 混调同步 DAO：

```python
def replace_source_bindings(
    session: Session,
    source_key: SourceKey,
    expected_revision: int | None,
    new_revision: int,
    references: VerifiedReferenceSet,
    effective: bool,
) -> BindingReplaceResult: ...

async def areplace_source_bindings(
    session: AsyncSession,
    source_key: SourceKey,
    expected_revision: int | None,
    new_revision: int,
    references: VerifiedReferenceSet,
    effective: bool,
) -> BindingReplaceResult: ...
```

`VerifiedReferenceSet` 含规范化 ReferenceSpec 集合、extractor_version 和 `BindingWriteContext`。`expected_revision=None` 只用于尚无来源集合的真实创建/迁移；已有来源必须显式 CAS，new_revision 严格递增（同业务幂等重放返回已存在结果，不产生隐式覆盖）。修改无引用相关字段是否递增由业务 Owner 定义，但不得回退 revision。`effective=False` 表示已成功业务删除/配置生命周期解除：清空该真实来源明细，保留集合终态记录。配置仅暂停/非当前不能传 false。

`BindingWriteContext` 必须包含：source_key、expected_root_revision、已锁根守卫当前 revision、完整旧/新 target 锁集、规范化旧集合摘要、目标 Owner receipts、session 与 **active transaction 对象身份**、receipt schema/version。约束：

1. receipt 只由应用层受信 Registry 调用 Owner 的 Repository-backed `lock_and_verify(session, target_keys, source_key, operation)` 产生，不接受 HTTP DTO 或任意 TargetKey 直接代替。REF 不查询 knowledge/llm ORM，也不反向 import 业务 Service；装配根注入 Owner Port。
2. 同一 Session、同一 active transaction 身份、同 source、完整集合精确匹配才可消费 context；commit/rollback 后 receipt 失效。async 对 transaction identity 使用其底层 sync_session transaction，不能只比 tenant 或 Session ID。
3. 固定序：相关模型服务按 ID → 固定类型序 `model, knowledge_space, knowledge_file` + ID → 文件实际归属/删除 manifest → 真实业务 root → root_guard → source/version set。此类型序供锁排序，不改变鉴权语义；同类型数值 ID 按数值升序。
4. 候选读确定旧+新目标与根修订；事务内锁后当前读复核，锁集/归属/来源修订变化则整体 rollback 后重算，不能持锁反序追加目标。新建来源集合/root_guard 唯一冲突以整个事务幂等有限重试，不用专有 upsert。
5. 每次版本创建/修改/删除都锁真实业务 root 和同 root_guard、递增 root revision；多版本删除计划核对该 revision。原 source row 的 CAS 与 root guard CAS 都必须成功。
6. 业务配置保存、R_old-R_new 删除、R_new-R_old 插入、交集 revision 更新、source set/digest/root_guard 同一 Session 一次提交。REF Repository 不自行 begin/commit/rollback，不发 Celery；异常由业务用例整笔 rollback。
7. 原 source/version/slot/target 未变且有合法 tombstone 或冻结 legacy 证据时允许保留失效项并逐项修复；新增来源/复制导入/新增槽位不能复用此许可。移除失效项不要求旧 live 目标存在；通过旧绑定+证据检查即可。新目标必须 live 且租户/共享/业务条件合法。

`BindingReplaceResult(source_key,source_revision,root_revision,digest,added,removed,retained_invalid)`；无 display name/凭据。计数为操作证据，不能作为独立删除依据。

### R3 删除影响、覆盖和失效

内部 `ReferenceRepository` 受外部 Session 支配：`get_source_set/get_root_guard/replace_source_set/list_inbound_targets/list_inbound_space/list_inbound_exact_files`，对应 `a...` 版本或内部适配。root/source 锁定读同事务。共享模型专用可信入口可在 Repository 内短范围 bypass 来源 tenant filter，按真实 target Owner/目标精确条件读所有实际来源租户；普通请求不接受 bypass 开关。INSERT 使用自动 tenant 填充；bulk UPDATE/DELETE 需显式限定已核实来源 tenant，因为当前 SQLAlchemy hook 仅 SELECT 自动注入。

- `TargetImpact(check_complete,blocked,can_delete_normally,can_force_delete,source_counts,visible_sources,restricted_counts,confirmation_plan_id)`；counts 按 source/version 去重，详情可列多槽；隐藏来源不返回 ID、tenant、name、version、URL。依赖装饰失败不抹掉阻断事实。
- 若覆盖/检查异常，不能把 unknown 当零：`check_complete=False` 时两个 can_* 必为 false，blocked 只作普通引用阻断不提供放行依据。存储/运行异常按业务错误失败，不生成可执行 plan。
- 强删 plan 持久化并冻结 actor/具体 tenant/operation、目标全集及修订、root revisions、完整规范化入向集合摘要（包含隐藏来源）、计数、幂等 operation_id、expires_at。ID 是服务端 opaque token，HTTP 不能自拼 digest。最终执行锁内重新授权、对账；任何目标/影响改变要求重新确认。强删仅跳过已知有效引用阻断。
- 文件/夹实际删除 manifest 的 `knowledge_file` 精确 ID/版本集合才参与直接保护；仅 space 绑定不阻普通文件，夹任一引用整项阻；file/folder/clear 永不 force。空间删除/clear 查 space + target_space_id 直接内容，模型服务查全部 removed targets。
- `resource_reference_tombstone` unique `(target_type,target_id,target_tenant_id)`，只有真实已核实拥有租户，deleting/deleted、operation_id、actor/time；不含配置/凭据。space 强删的直接文件失效由其 target_space_id 对应 tombstone 推导。legacy 不写假 tombstone。
- 目标Owner判定 live + tombstone + legacy evidence：`valid/deleting/invalid_deleted/invalid_legacy`；无证据 missing 为不一致、fail closed。详情保原 ID/失效，执行/发布/重新启用明确失败，不 fallback。
- coverage 存放 MIG/INT 的持久账本，REF 消费 `CoveragePort.get_status(tenant_id,source_type,writer_contract_version)`；状态须覆盖所有启用来源及零引用集合。无记录不是 ready，合法已对账 legacy 不是缺口。新空安装/新tenant初始化由 INT 在可信业务创建事务调 bootstrap、证明无旧数据且全部同步写端启用、持久 writer_contract 版本；REF 不导入知识业务 Service。已有 tenant 不能冒充空数据跳回填。

主agent已冻结错误码：10994 ReferenceCoverageNotReadyError、10995 ResourceReferenceConflictError（普通引用阻断/变化type通过data.reason区分）、10996 ResourceReferenceInvalidError（目标失效/来源修订冲突通过reason）、10997 KnowledgeProcessingObsoleteError、10998 KnowledgeOperationPlanConflictError、10999 KnowledgeProcessingConflictError。由INT统一代码及三语注册，REF不另申请模块号、不导入知识业务Service。以下内部reason：`reference_revision_conflict`、`reference_lock_plan_changed`、`reference_target_invalid`、`reference_target_deleted`、`reference_target_unexplained_missing`、`reference_coverage_not_ready`、`reference_check_failed`、`reference_confirmation_changed_or_expired`、`reference_force_not_supported`。revision/锁集可按业务幂等键有限重试；auth、非法跨租户/歧义/覆盖缺口/确认变化不能自动重试为成功。target_invalid 对外裁剪，不能泄露目标是否存在。

### B1 来源维护与最新基线接缝

| source_type / version | 提取、保留与解除 |
|---|---|
| workflow_version / FlowVersion.id | root=Flow.id；root与version均未删才维护，草稿/非当前/下线保留；Flow.data 镜像不另计。F004 WORKFLOW 软删在同事务设置 Flow.is_delete=1、FlowVersion.is_delete=1，该成功事务解除相应来源，不因行仍存在保留执行绑定；历史内容继续保留 |
| assistant / current | 当前 model_name 标识/AssistantLink.knowledge_id；create/update/delete均接入；OFFLINE不解除；真删除、移除/改绑槽位才更新 |
| hosted_app_version / AppVersion.id | root=App.id；所有已保存且应用未删除版本，含管理预览历史、terminal、停止/被替代；新版本只新增集合，不改旧manifest/解绑旧版；整个应用删除成功才解除 |
| channel_sync / current | root=channel.id；主/子配置稳定语义槽（子频道规则名的规范化hash），不可用每次重建sync行ID；关闭is_enabled保留，目标移除/频道解散才解除 |
| knowledge / current | root=Knowledge.id，不以type0/3区分来源；空间/QA实际当前和切换阶段模型槽都维护；clear保留，真删除finalize才解除 |
| model_default / current | source_id=原始配置key、tenant=实际存储来源Root/leaf；五类defaults含linsight/workbench；恢复继承只解除leaf override，Root保留，不给继承消费者复制 |

任务、排队参数、对话、审计、评测结果不登记来源，不以历史模型ID阻删除。需要保存的草稿即使缺其他参数不能运行，也不得过滤已保存有效引用。

### B2 不可变应用名字声明与冻结 ID

保存/停服回填时由 APP Owner 采用当前运行语义解析：模型 name、knowledge name/id；歧义失败，原ID明确但冻结基线已证实missing才legacy。`ReferenceSpec.slot_key` 对原不可变声明语义稳定（如 `capabilities.model:<sha256(stripped_name)>`），target是真实ID；引用集合本身就是版本目标映射，无需改manifest或复制凭据。

运行、管理预览、capability status与模型网关必须加载 **相同 app/version SourceKey 的已登记完整集合**。原名字协议允许保留，但最终解析到的目标ID必须与该槽冻结ID相同；rename/重名/名称改指向M2都不允许漂移。模型/空间已删则明确失效，不静默删 whitelist 项或换另一个默认。名称解析暂不可确定是失败，不把未绑定新ID当许可。删除tombstone/覆盖状态须参与缓存失效，旧缓存不可允许新调用。

### 已核对的现有入口（均需改为外部 Session 路径）

- `database/models/flow.py:213 FlowDao.delete_flow` 已在根 `with_for_update` 后 WORKFLOW软删/所有版本is_delete，并自行commit；须把业务+绑定合成一个事务。
- `database/models/flow_version.py:65 create_version`、`:81 update_version`、`:104 aupdate_version` 都已有根锁但自开Session/commit，适合改为参与Owner外部事务，不能保持旧commit再补引用。
- `knowledge/domain/repositories/knowledge_space_delete_repository.py:36 prepare` 已锁space/真实tree/版本链并返回精确manifest，可复用真实file/version映射；SQL cutover前必须完成既有F048投影，不能原样复制旧直接删除次序。
- `llm/domain/models/llm_server.py:238 update_server_with_models`、`:460 adelete_server_by_id`、`:497 adelete_model_by_ids` 目前独立写事务；LLM应用用例算差集/目标锁后在同Session执行。
- `llm/domain/models/tenant_system_model_config.py:99 aget`、`:119 aupsert` 是Root/leaf默认存储；Owner需新增外部Session Repository协议，不沿用自提交DAO做绑定后补。
- `app_publish/domain/services/version_service.py:_insert_version` 为真实不可变版本插入；`capability_bus_service.py:187 load_effective_declaration` 当前按在线/预览版本读取，却`:225 _resolve_knowledge_refs`实时名称解析、模型仅保存名字，`:331 declared_model_names`与 `open_api/.../model_range_policy.py` 需要版本冻结ID消费接线。
- `core/database/tenant_filter.py:41 _TENANT_AWARE_MODEL_MODULES` 为新三表强制注册；当前hook仅SELECT过滤，需严格隔离读取，写者验证tenant，跨tenant共享反查限Repository。


# J1 / A1 V1 冻结合同（基线 a1b1a2387，2026-11-05）

本稿为新实现的合同，不代表当前 API 已提供。前缀 `/api/v1/knowledge/space`。复用 `resp_200` / `UnifiedResponseModel(status_code,status_message,data)`；新增分页统一 `PageData(data,total)`，旧列表/游标列表/旧文档返回结构不替换。现有 `/{space_id}/children` 已是游标分页，继续 `PageInfiniteCursorData`。

## J1：默认策略

新增 `knowledge/domain/schemas/processing_settings.py`，独立定义纯 DTO，不能 import `api/v1/schemas.py`（避免 domain -> API 依赖）；兼容适配在应用/已有 API DTO 层执行。

- `DocumentProcessingRule` 字段直接沿用 FileProcessBase：`split_mode: Literal[auto,custom,hierarchical]`；`separator: list[str]`、`separator_rule: list[Literal[before,after]]`；`chunk_size:int`、`chunk_overlap:int`；`hierarchy_level:int`、`append_title:bool`、`max_chunk_size:int`；`retain_images/force_ocr/enable_formula/filter_page_header_footer: Literal[0,1]`。
- `TableProcessingRule` 直接沿用 ExcelRule 四字段：`slice_length:int`、`header_start_row:int`、`header_end_row:int`、`append_header:Literal[0,1]`。它不带普通文档分隔符/overlap，不带具体sheet/file信息。
- `ProcessingDefaults(schema_version:Literal[1], document:DocumentProcessingRule, table:TableProcessingRule)`。
- `ProcessingSettingsRead(space_id:int, config_version:int, saved_defaults:ProcessingDefaults|None, effective_defaults:ProcessingDefaults)`；NULL历史配置 `config_version=0`，effective 从现有系统规范化默认计算，绝不从某历史文件反推。
- `ProcessingSettingsWrite(expected_config_version:int>=0, defaults:ProcessingDefaults)`，整体校验、CAS、一次保存两组规则，成功递增版本；取消/任何失败零保存、不创建历史文件重处理任务。
- `ProcessingOverrides(document:PartialDocumentRule|None, table:PartialTableRule|None)`：稀疏显式覆盖。`null` 按未指定解释；不把服务器补出的默认值看作客户端显式值。业务先保留原始 payload 中真正显式字段，再合并 system -> space -> batch -> file，最后应用能力限制和网页/音视频既有专用覆盖。普通文档只消费 document，表格只消费 table。
- 最终 `EffectiveProcessingSnapshot(schema_version=1, file_kind, effective_rule, space_config_version, supplied_fields_by_layer)` 冻结至文件 split_rule / job item；不保存临时URL/文件名/sheet实例/cache/knowledge_id。修改空间默认不改变已开始任务及旧文件快照；重试读原实际快照。

### 规范化与校验

普通切分 `chunk_size>0`，`0<=chunk_overlap<=chunk_size`；separator 与 rule 对齐且 rule 只 before/after；hierarchy_level 沿当前后端接受范围 1..6，max_chunk_size>0。表格 slice_length>0，header 行号>0 且 start<=end，append_header仅0/1。现有前端 hierarchy 上限5、表头UI上限1000只是 UI 当前约束；本合同不凭UI额外收紧既有后端能接收的历史值，前端新默认策略控件按同一服务端合同对齐。

现 `FileProcessBase.check_separator_rule` 的 before validator 会就地补值；其缺省 force_ocr 实际补1（Field表面默认0）。系统默认必须从现有真实规范化行为适配，不能复制字段表面默认作为新真相。不能用已经补值后的 `.model_dump()` / `.model_fields_set` 推断显式覆盖。旧调用适配必须在标准化前捕获显式输入；旧完整 split_rule 一律作为已冻结实际配置，不再与新空间默认合并。

## J1：任务 DTO 与状态

`ProcessingKind`（持久/公开枚举）=`embedding_rebuild|file_reprocess|file_resplit|metadata_schema_change|move_index|space_copy`。公共高级任务创建只接受前四项；后两项由已有移动/复制用例创建。`JobState`=`accepted|running|succeeded|partial_failed|failed|obsolete`；`ItemState`=`pending|running|succeeded|failed|obsolete`。

- `ResourceVersionTarget(file_id:int, document_id:int, version_id:int)`：三个ID不得混用。客户端可提供 file/version，Owner 验证并补齐真实三元组；空间全量任务由服务端展开。
- `ProcessingPrecheckRequest(kind, targets:list[ResourceVersionTarget]|None, parameters:对应kind的DTO)`；model rebuild parameters 含 `embedding_model_id:int`（可省略表示当前合法模型的手动全量重建）；reprocess/resplit 含显式 overrides 和覆盖人工Chunk影响；metadata含当前schema修订及新增/重命名/删除结构差异。
- `ProcessingCreateRequest(idempotency_key:str[1..64], confirmation_id:str, plan_digest:str)`，不重复接受可以扩大冻结范围的targets或model参数。通过precheck冻结的参数执行。
- `JobAccepted(job_id:str(UUID), accepted:Literal[True], state:JobState, reused:bool)`；accepted只代表命令已接收，state来自持久记录；同键重投可能返回已在running或终态的同job，不能假重置为accepted。
- `ProcessingJobRead(id, space_id, kind,state,revision, accepted_at,started_at,finished_at,total_count,succeeded_count,failed_count,pending_count,hidden_item_count,retryable,obsolete_reason,error_code)`；摘要不含模型凭据、文件全文、隐藏依赖名。
- `ProcessingItemRead(id,file_id?,document_id?,version_id?,step,state,attempt,error_code,message?,retryable)`；无权文件的名称、ID、正文与入口不返回，以 job 的 hidden_item_count/count/state 聚合呈现。后台当前身份可见才给明细，不复用管理员缓存。
- `ProcessingRetryRequest(idempotency_key:str[1..64], expected_job_revision:int)`；只恢复原job原失败items，不接受model/space/target替换。人工retry重新鉴权；failed/partial_failed可重试，obsolete终态拒绝。旧模型恢复也需新重建。

持久 job 唯一 `(tenant_id,kind,idempotency_key)`，记录 canonical request_hash；同key异payload拒绝。同key相同payload返回原job。job item 唯一 `(job_id, file_id, version_id)`；整版本任务的 step/checkpoint 累进，同 item retry 增 attempt，不再生成文件/版本/授权。

### 修订与租约

`space_config_version`仅追溯默认快照，不使旧任务因修改默认而过期。另用空间 `model_config_revision`（只随模型配置替换单调递增，A->B->A也递增）和 `index_generation`（当前/目标索引代的稳定标识）作为相关业务期望值。名称/说明变化不动它们。job 记录 expected_model_config_revision + expected_index_generation；每次领取、人工/自动恢复、可控步骤与SQL finalize重验，失配obsolete。实际模型读取当前空间业务槽位，不从job历史参数恢复绑定。

worker领取另有 job/item `lease_token`、`lease_until`、`claim_generation`，接管递增claim_generation，SQL finalize 必须匹配租约/claim_generation以及上面的业务修订。它不与 index_generation 混为同一字段。任务+待投递记录同事务，broker失败由持久恢复补发；不以Celery result作为业务状态。Celery headers 的 tenant_id -> ContextVar，任务行tenant/actor核实；不存bearer。

模型重建活跃期间保目录/原文件预览/下载，暂停空间检索及同空间冲突写；其他空间不受阻。原Chunk与metadata分页全量读取（超过10000），失败保可重试文本源；全部items尝试后成功项恢复检索、失败项排除。外部已在途I/O迟到与后续用户修改竞态排除，不加attempt staging/外部CAS。

## A1：冻结的新路由

| 方法 | 完整路径（均含 `/api/v1`） | 请求 -> data |
| --- | --- | --- |
| GET | `/api/v1/knowledge/space/admin/list` | keyword?,page=1,page_size=20(1..200) -> PageData[KnowledgeSpaceListItemResp]；只一个可信具体tenant |
| GET | `/api/v1/knowledge/space/{space_id}/processing-settings` | 无 -> ProcessingSettingsRead |
| PUT | `/api/v1/knowledge/space/{space_id}/processing-settings` | ProcessingSettingsWrite -> ProcessingSettingsRead |
| POST | `/api/v1/knowledge/space/{space_id}/processing-jobs/precheck` | ProcessingPrecheckRequest -> OperationPrecheck |
| POST | `/api/v1/knowledge/space/{space_id}/processing-jobs` | ProcessingCreateRequest -> JobAccepted |
| GET | `/api/v1/knowledge/space/{space_id}/processing-jobs` | page=1,page_size=20(1..200),kind?,state? -> PageData[ProcessingJobRead] |
| GET | `/api/v1/knowledge/space/{space_id}/processing-jobs/{job_id}` | 无 -> ProcessingJobRead |
| GET | `/api/v1/knowledge/space/{space_id}/processing-jobs/{job_id}/items` | page=1,page_size=20(1..200),state? -> PageData[ProcessingItemRead] |
| POST | `/api/v1/knowledge/space/{space_id}/processing-jobs/{job_id}/retry` | ProcessingRetryRequest -> JobAccepted |
| POST | `/api/v1/knowledge/space/{space_id}/files/operations/precheck` | discriminated operation=delete/download/tag/retry/move + 原类型参数 -> OperationPrecheck |

静态 `/admin/list` 与既有 `/{space_id}/info` 不冲突；`processing-jobs/precheck` 必须注册在 `processing-jobs/{job_id}` 前。现 router prefix 为 `/knowledge/space`，总 router `/api/v1`，不得再重复 knowledge 前缀。新增processing endpoints可独立router同prefix，由KN/INT唯一装配。

`OperationPrecheck` 固定字段：`confirmation_id`, `plan_digest`, `expires_at`, `check_complete`, `can_execute`, `valid_items`, `invalid_items`（reason/error_code；无权项隐藏name/content），`impact`（whole-version/metadata loss/permission inheritance/retrieval pause/overwrite-manual-chunk等对应类型），`requires_skip_confirmation`。precheck不建job、不改业务对象；持久的确认计划不算业务修改。无有效项 `can_execute=false`，不能强造空job。

确认是服务端持久的 opaque ID，不是客户端布尔值。计划绑定操作者、具体tenant、操作、目标集合/版本、相关资源与来源修订、规范化payload/hash及影响摘要。执行同时提交ID/digest并重新检查；任一变化报 `KnowledgeOperationPlanChangedError`，不扩集合/不自动忽略新增阻断。过期报 `KnowledgeOperationPlanExpiredError`。人工取消不调用执行，因此零资源/任务修改。强删范围和tombstone使用R3合同；文件/文件夹及clear无force。

现有move / batch-delete / batch-download / batch-tag / batch-retry路径保留、参数和返回envelope不重定义；新确认信息作为可选扩展接入。仅当业务要求二次确认或存在跳过项时，未带确认的旧请求返回既有envelope内的“需要确认”业务错误/附加data，零修改；已带旧skip_invalid=true本身不能代替被冻结的影响确认。没有二次确认要求且所有项都有效时，旧请求仍能直接走统一用例，不能为了新UI整体禁止旧API。所有入口最终执行前复核最新业务条件，不能用旧接口绕保护。跨空间move/删除已知历史内容提示/覆盖人工chunk等既定强制确认仍需执行此流程。

## A1：可信管理员范围与授权动作

新基线 `AdminScopeMiddleware` 已将 `/api/v1/knowledge` 作为管理路径，通过F019绑定 request.state.management_tenant_id / management_tenant_scope。GET admin/list 只能平台超管/相应租管，并要求有效具体tenant；super默认own且可按既有scope切换，租管仅own。拒绝空/全租户汇总，不从query body任意切换tenant；ordinary管理列表入口不能取得全量。

管理写入需 `X-Management-Tenant` 对照当前可信scope防止浏览器切换tenant后旧页面误写；当前middleware的expected-write表未覆盖space新路由，INT需用小任务补明确的新管理写入路径，保持普通client/API凭证入口原语义，不能把所有space普通写入一律强加网页管理头。新后台高级PUT/POST可在processing endpoint显式调用已有 require_expected_management_tenant；admin上下文接线由KN/INT负责。服务账号开放凭证按现有scope/actor/tenant，不要求网页菜单/这个浏览器头。

高级settings/rebuild/reprocess/chunk/metadata按既有容器edit；文件/夹rename用目标rename，retry/tag/encoding保持原文件rename，不新增fileedit或额外可见gate。管理详情/操作在同一可信tenant里，但管理员不跳配额、安全、部门审批、任务冲突、引用保护；copy仍仅源创建者。

### 新错误名（数值由INT T012核对占用后统一分配）

`KnowledgeProcessingSettingsConflictError`（expected version已变）、`KnowledgeProcessingConflictError`（活跃冲突任务）、`KnowledgeProcessingJobNotFoundError`（无权/不存在不泄露）、`KnowledgeProcessingObsoleteError`、`KnowledgeProcessingJobNotRetryableError`、`KnowledgeIdempotencyConflictError`（同键异payload）、`KnowledgeOperationConfirmationRequiredError`、`KnowledgeOperationPlanChangedError`、`KnowledgeOperationPlanExpiredError`。引用/coverage等错误采用R3，已有权限/配额/审批/参数错误复用。不从此合同私占新错误码或改旧错误含义。

## 源码锚点

- `knowledge/api/endpoints/knowledge_space.py`: prefix54；create83；info175；move578；batch-delete640；batch-retry661；原目录游标358。
- `knowledge/domain/schemas/knowledge_space_schema.py`: create56、info87、move224、batchdelete242。
- `api/v1/schemas.py`: ExcelRule564、FileProcessBase573、before validator606；注意只在兼容适配层依赖它。
- `knowledge/rag/knowledge_file_pipeline.py`: split_rule构造41-44、web专用覆盖45-48。
- `common/schemas/api.py`: envelope9、PageData44、PageInfiniteCursorData61。
- `common/middleware/admin_scope.py`: management prefix30、expected writes63、可信scope绑定148；`admin/application/tenant_scope.py` require_expected_management_tenant39。
- `worker/knowledge/rebuild_knowledge_worker.py`: 当前单次10000的查询204、实际add_texts236。
- `knowledge/domain/models/knowledge_document_version.py`: document_id/file_id/version_no与主版本；`knowledge_space_delete_job.py`已提供durable lease/token/manifest模式参考，不能直接等同J1状态。


## 冻结与变更记录

2026-11-05：INT 汇总 PERM/REF/PROC 三份独立源码核对，冻结 P1/R1/R2/R3/B1/B2/J1/A1。处理快照原始覆盖、pure-visible持久化、root_guard与双Session入口、F004软删、应用冻结ID、新空租户覆盖初始化均纳入V1。后续修订记录明确版本、受影响任务/消费者与兼容处理。

## T001 字面use接线盘点（冻结基线）

以下是对全部 bisheng Python 源的字面use/use_kb命中，不意味着每处都是当前独立鉴权；历史迁移解码、审计快照与固定协议保留字按兼容合同处理。实际活动决策必须收敛visible。表中Owner独占对应叶子，新增发现先补任务；SDK实际适配为 `dev_toolkit/sdk_compat.py`，MCP为 `open_mcp/{compatibility,tools/knowledge,tools/file,tools/apps}.py`，检索共用RetrievalFacade。

| src/backend/bisheng 下的文件 | 唯一接线 Owner |
| --- | --- |
| `api/services/assistant.py` | AS |
| `api/services/f048_application_permission.py` | PERM |
| `api/services/workflow.py` | WF |
| `api/v1/assistant.py` | AS |
| `api/v1/chat.py` | EDGE |
| `api/v1/workflow.py` | WF |
| `app_publish/domain/services/app_publish_current_visibility_service.py` | APP |
| `app_runtime/domain/schemas/app_authorization.py` | APP |
| `app_runtime/domain/services/entry_authz_service.py` | APP |
| `channel/domain/services/f048_channel_permission.py` | CH |
| `common/chat/manager.py` | EDGE |
| `core/openfga/authorization_model_f048.py` | PERM |
| `dsh/domain/services/capability_catalog.py` | EDGE |
| `dsh/domain/services/work_capabilities.py` | EDGE |
| `knowledge/api/endpoints/knowledge.py` | KN |
| `knowledge/domain/knowledge_rag.py` | KN |
| `knowledge/domain/services/knowledge_permission_service.py` | KN |
| `knowledge/domain/services/knowledge_service.py` | KN |
| `knowledge/domain/services/retrieval_facade_service.py` | KN |
| `linsight/domain/services/skill_permission.py` | EDGE |
| `linsight/domain/services/user_skills.py` | EDGE |
| `open_api/domain/services/task_mode_service.py` | EDGE |
| `open_endpoints/api/endpoints/workflow.py` | EDGE |
| `permission/application/business_authorization.py` | PERM |
| `permission/application/catalog_api.py` | PERM |
| `permission/application/runtime.py` | PERM |
| `permission/domain/services/catalog_policy.py` | PERM |
| `permission/domain/services/grant_service.py` | PERM |
| `permission/domain/services/owner_service.py` | PERM |
| `permission/migration/f048_model_mapper.py` | PERM |
| `tenant/domain/services/resource_share_service.py` | PERM |
| `tool/api/tool.py` | EDGE |
| `tool/domain/services/executor.py` | EDGE |
| `tool/domain/services/f048_tool_permission.py` | EDGE |
| `tool/domain/services/saved_tools.py` | EDGE |
| `tool/domain/services/tool.py` | EDGE |
| `worker/workflow/tasks.py` | EDGE |
| `workstation/api/endpoints/apps.py` | EDGE |
| `workstation/domain/services/workstation_service.py` | EDGE |

旧知识读写消费面同时核对平台 `controllers/API/knowledgeSpace.ts` / `controllers/hooks/knowledge.ts`、客户端 `api/{knowledge,knowledgeUpload,permission}.ts`、助手/工作流/工作台、APP能力声明/运行/预览、频道同步、v2 filelib/knowledge和SDK/MCP。两端当前动作模型由服务端返回，通用授权组件不得用空action数组隐藏合法纯可见来源。
