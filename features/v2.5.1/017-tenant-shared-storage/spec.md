# Feature: F017-tenant-shared-storage (集团共享资源机制)

**关联 PRD**: [../../../docs/PRD/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md](../../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20多租户需求文档.md) §7.2, §4.4
**优先级**: P1
**所属版本**: v2.5.1

---

## 1. 概述与用户故事

作为 **集团 IT**，
我希望 **Root Tenant 创建的资源可通过"共享给集团子公司"开关一键共享给所有 Child Tenant 成员**，
以便 **集团总部的统一知识库、频道、应用模板对子公司成员只读开放**。

---

## 2. 验收标准

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 全局超管 | 创建 Root 资源勾选"共享给集团子公司" | 写入 `{resource}#viewer → tenant:{root}#shared_to#member`；`resource.is_shared=true` |
| AC-02 | 新创建 Child Tenant | 自动分发可见 | 系统自动写入 `tenant:{root}#shared_to → tenant:{new_child}` |
| AC-03 | Child 用户 | 访问 Root 共享资源 | FGA 通过 shared_to 链路返回 viewer |
| AC-04 | Child 用户 | 尝试编辑 Root 共享资源 | FGA editor 检查失败；HTTP 403 |
| AC-05 | 全局超管 | 取消共享（资源详情页关闭"共享"开关） | **撤销** `{resource}#viewer → tenant:{root}#shared_to#member` 元组；Child 立即不可见；资源继续存在 Root（PRD §7.2 新增） |
| AC-06 | Child 用户 | 从 MinIO 读共享文件 | 路径前缀走 Root；不通过则 fallback（PRD §4.4.2）|
| AC-07 | 系统 | 解绑 Child Tenant | 自动撤销 `tenant:{root}#shared_to → tenant:{child}` 元组（避免悬挂关系）；同时撤销该 Child 名下所有 owner/member 元组 |
| AC-08 | Child 用户 | 与 Root 共享知识库对话产生消息记录 | `chat_message.tenant_id = Child 叶子`（衍生数据归属，INV-T13 / PRD §1.2）；不写入 Root |
| AC-09 | Child 用户 | 调用 Root 共享 LLM 模型消耗 token | token 计入 Child `model_tokens_monthly` 配额（INV-T13）；不消耗 Root token 配额 |
| AC-10 | 系统 | 共享资源存储空间统计 | 仅计入 Root 自身 `storage_gb` 用量一次；Child 不重复计入（即使被多个 Child 读） |
| AC-11 | 开发 | 衍生数据写入时 `get_current_tenant_id()` 返 None（理论不应发生，中间件保障） | `ChatMessageService.acreate` / `LLMTokenTracker.record_usage` 抛 `TenantContextMissing` exception；上层统一捕获返 HTTP 500 + `19504` "租户上下文缺失"；**禁止 tenant_id=NULL 静默落库**，防 INV-T13 衍生数据归属被污染 |
| AC-12 | 全局超管 | 取消资源共享（AC-05 细化时序） | 精确执行四步：① `FGAClient.delete_tuple({resource}#viewer → tenant:{root}#shared_to#member)` 撤销 viewer 元组；② **保留** `{resource}#owner → user:{root_creator}` 元组（资源在 Root 不删）；③ Child 用户 `GET /resources` 列表立即不再返回此资源；④ 已有 Child 用户与该资源产生的衍生 chat_message / token 记录**保留**（tenant_id 已是 Child 叶子，独立归属 INV-T13）；不级联清理 |
| AC-13 | 全局超管 | 挂载 Child 弹窗勾选"不自动分发" | `ChildMountService.on_child_mounted(root_id, child_id, auto_distribute=False)` 跳过写 `tenant:{child}#shared_to → tenant:{root}` 元组；Child 初始不可见任何 Root 共享资源；audit_log `action='tenant.mount'` metadata 记录 `auto_distribute=false`；超管后续逐个资源开启共享 |

---

## 3. 边界情况

- **Milvus 共享**：Child 检索时 fallback 到 Root collection（PRD §4.4.1）
- **新 Child 挂载**：自动分发所有标记 `share_default_to_children=true` 的 Root 资源
- **Root 修改共享资源**：Child 自动看到新版（最终一致；shared_to 关系不关心版本）
- **不支持**：
  - Child 拒绝接受共享（PRD Review P0-B 决策）
  - 可编辑共享（MVP 仅只读）
  - 跨 Root 共享（仅私有化单 Root，2026-04-20 收窄）

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 |
|----|------|------|------|
| AD-01 | 共享粒度 | A: 资源级 / B: 全 Root 统共享 | A（按资源开关）|
| AD-02 | 新 Child 自动继承 | A: 自动 / B: 手工申请 | A（PRD §7.2） |
| AD-03 | 共享资源的 tenant_id | A: Root ID / B: 复制到 Child | A（单点维护，Child 通过 shared_to 访问） |
| AD-04 | **衍生数据归属** | A: 跟资源走（归 Root） / B: 跟读者走（归 Child 叶子） | B（INV-T13 / PRD §1.2 / §6.3）：对话/token/调用日志归 Child 叶子，资源本身归 Root；避免 Root 共享被 Child 大量消耗时背锅 |
| AD-05 | 取消共享处理 | A: 仅删元组 / B: 删元组 + 删资源 / C: 删元组 + Child 镜像保留 | A（资源继续存在 Root，Child 仅失去可见性；PRD §7.2 新增）|

---

## 5. 实现要点

### 5.1 资源创建时写入

```python
class ResourceCreationService:
    async def create_with_sharing(self, owner_id: int, share_to_children: bool, ...):
        resource = await self._create(...)
        await fga.write_tuple(user=f"user:{owner_id}", relation="owner", object=f"{type}:{resource.id}")

        if share_to_children and self.is_root_tenant(resource.tenant_id):
            await fga.write_tuple(
                user=f"tenant:{resource.tenant_id}#shared_to#member",
                relation="viewer",
                object=f"{type}:{resource.id}"
            )
            resource.is_shared = True
```

### 5.2 新 Child 挂载时分发

```python
class ChildMountService:
    async def on_child_mounted(self, root_id: int, child_id: int, auto_distribute: bool = True):
        """
        auto_distribute=True（默认）：为新 Child 写 shared_to → tenant:{root} 关系，
        使所有 `share_default_to_children=true` 的 Root 资源立即对本 Child 可见。

        auto_distribute=False：跳过 shared_to 写入；Child 初始不可见任何 Root 共享资源；
        超管后续需逐个资源在 UI 开启共享（对应 PRD §5.2.1 挂载 review 弹窗"不自动分发"选项，
        应对内部法务微调等敏感模型不应自动暴露新 Child 的场景）。audit_log metadata 记录
        本次 auto_distribute 取值 + 若为 true 时被分发的资源 id 清单。
        """
        if auto_distribute:
            await fga.write_tuple(
                user=f"tenant:{child_id}",
                relation="shared_to",
                object=f"tenant:{root_id}",
            )
```

### 5.3 外部存储共享（MinIO / Milvus）

- **MinIO**：Child 读时若本 Tenant 前缀未命中，fallback 到 Root 前缀；通过应用层实现
- **Milvus**：Child 检索时同时查本 Tenant + Root 共享 collection；BM25 / vector search 合并

### 5.4 衍生数据写入层（2026-04-21 新增，承接 INV-T13）

**背景**：Child 用户读 Root 共享资源（知识库 / 应用 / 助手）产生的衍生数据（对话记录、消息 token 消耗、LLM 调用日志）归属 Child 叶子 Tenant 而非 Root；F016 配额计数依赖此行为。

**实现改造点**：

| 服务 / 组件 | 改造点 | 文件路径 |
|-----------|-------|---------|
| `ChatMessageService.acreate` | 创建消息时 `tenant_id = get_current_tenant_id()`（叶子），**不**继承所读资源的 tenant_id | `src/backend/bisheng/chat_session/domain/services/message_service.py` |
| `MessageSessionService.acreate` | 会话 tenant_id = 用户叶子（与所属应用资源 tenant_id 解耦） | `src/backend/bisheng/chat_session/domain/services/session_service.py` |
| `LLMTokenTracker.record_usage` | token 用量记录 tenant_id = 用户叶子，计入 Child `model_tokens_monthly` | `src/backend/bisheng/llm/domain/services/token_tracker.py`（若未建则新增） |
| `ModelCallLogger.log` | 调用日志 tenant_id = 用户叶子 | `src/backend/bisheng/llm/domain/services/call_logger.py`（若未建则新增） |

**伪代码示例**：

```python
class ChatMessageService:
    @classmethod
    async def acreate(cls, user_id: int, session_id: int, content: str, assistant_id: int = None, **kw) -> ChatMessage:
        # 2026-04-21：衍生数据归属叶子 Tenant，不依赖 assistant.tenant_id（可能是 Root 共享）
        leaf_tenant_id = get_current_tenant_id()  # JWT 中间件已设好
        return await ChatMessageDao.acreate(
            user_id=user_id,
            session_id=session_id,
            tenant_id=leaf_tenant_id,          # ← 关键：叶子 Tenant，非资源 tenant_id
            content=content,
            ...
        )
```

**边界**：

- 若用户叶子 = Root（集团总部用户），衍生数据归 Root（= 资源 tenant_id），无差异
- `current_tenant_id` 未设置时（理论不应发生，中间件保障）抛错 `TenantContextMissing`，拒绝写入
- F016 的配额计数走 `strict_tenant_filter()`，直接按 `tenant_id = Child` 精确计数，自然命中本节的衍生数据

---

## 6. 依赖

- F013-tenant-fga-tree（shared_to 关系）
- F011-tenant-tree-model（Tenant 树 + share_default_to_children 字段）
- v2.5.0/F008-resource-rebac-adaptation（资源创建服务）

### 6.1 前置修复（已完成）

- **v2.5.0 F005 KI-01** 已于 2026-04-19 F016 自测时修复：`_RESOURCE_COUNT_TEMPLATES['knowledge_space']` / `channel` / `channel_subscribe` / `tool` 共 4 个模板的 SQL 错误（不存在的 `status` 列、错误的表名 `gpts_tools`）已修正，114 probe 验证 `knowledge_space` 计数 0→15、`tool` 计数 0→37。F017 AC-02 "共享 knowledge_space 不计入 Child 用量" 现在可以用真实数据证伪。详见 [v2.5.0/F005 §9.1](../../v2.5.0/005-role-menu-quota/spec.md#91-known-post-release-issuesv251-自测发现)。

---

## 7. 自测清单（对应 AC）

> 开发者在完成实现后必须自行运行以下测试；不依赖用户/产品人肉点击。FGA/MinIO/Milvus 依赖可用 fixture 起真实服务或 mock client。

| Test | AC | 类型 | 备注 |
|------|----|------|------|
| `test_share_toggle_writes_viewer_tuple` | AC-01 | pytest 集成测试 | 共享开关 ON 写入 `{resource}#viewer → tenant:{root}#shared_to#member` 元组 |
| `test_new_child_auto_distributes_shared_tenants` | AC-02 | pytest 集成测试 | 新 Child 挂载自动写 `tenant:{root}#shared_to → tenant:{child}` |
| `test_child_user_sees_shared_resource_via_fga` | AC-03 | pytest 集成测试 | FGA check shared_to 链路返 viewer |
| `test_child_user_cannot_edit_shared_resource` | AC-04 | pytest 集成测试 | FGA editor 拒绝；API 返 403 |
| `test_revoke_share_deletes_viewer_tuple` | AC-05, AC-12 | pytest 集成测试 | 关闭开关撤销 viewer 元组；owner 保留；资源仍在 Root；衍生数据不级联清理 |
| `test_minio_fallback_reads_shared_file_from_root` | AC-06 | pytest 集成测试 | Child 路径 miss → fallback Root 前缀 |
| `test_unmount_child_revokes_shared_to_tuple` | AC-07 | pytest 集成测试 | 解绑 Child 撤销 `tenant:{root}#shared_to → tenant:{child}` + Child 名下 owner/member 元组 |
| `test_chat_message_tenant_id_is_child_leaf` | AC-08 | pytest 集成测试 | 衍生对话 `chat_message.tenant_id = Child 叶子`（§5.4 写入层） |
| `test_llm_token_attributed_to_child_leaf` | AC-09 | pytest 集成测试 | Root 共享 LLM 的 token 计入 Child `model_tokens_monthly` |
| `test_shared_storage_counted_once_on_root` | AC-10 | pytest 单元测试 | Root 共享文件 100MB → Root +100MB，Child 不叠加 |
| `test_missing_tenant_context_raises_error` | AC-11 | pytest 单元测试 | `get_current_tenant_id()` 为 None 时抛 `TenantContextMissing`；返 19504 |
| `test_mount_child_skip_auto_distribute` | AC-13 | pytest 集成测试 | `auto_distribute=False` 跳过 shared_to 写入；audit_log 记录 metadata |
| `test_milvus_fallback_queries_shared_collection` | AC-06 | pytest 集成测试 | Child 检索合并 Root collection 结果 |

---

## 8. 错误码

- **MMM=195** (tenant_sharing)
- 19501: 仅 Root Tenant 可共享
- 19502: 资源类型不支持共享
- 19503: MinIO/Milvus 跨 Tenant fallback 失败
- 19504: 租户上下文缺失（衍生数据写入 `get_current_tenant_id()` 返 None，防 INV-T13 污染）
