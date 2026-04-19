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

---

## 7. 手工 QA 清单

- [ ] 共享开关生效，Child 用户可见
- [ ] 新 Child 挂载自动继承
- [ ] **取消共享元组撤销**：关闭开关后 `{resource}#viewer → tenant:{root}#shared_to#member` 元组被删除；Child 立即不可见；资源仍在 Root
- [ ] **解绑 Child 元组撤销**：解绑后 `tenant:{root}#shared_to → tenant:{child}` 元组被删除（无悬挂）
- [ ] MinIO fallback 读取共享文件
- [ ] Milvus 合并查询共享 collection
- [ ] Child 用户无法编辑共享资源
- [ ] 共享资源 tenant_id = Root；用量仅计 Root
- [ ] **衍生对话归属**：Child 用户与 Root 共享知识库对话，`chat_message.tenant_id = Child 叶子`
- [ ] **衍生 token 归属**：Child 用户调 Root 共享 LLM，token 累加进 Child `model_tokens_monthly` 用量
- [ ] **存储不重复计入**：Root 共享文件 100MB → Root 用量 +100MB，所有 Child 用量均不变

---

## 8. 错误码

- **MMM=195** (tenant_sharing)
- 19501: 仅 Root Tenant 可共享
- 19502: 资源类型不支持共享
- 19503: MinIO/Milvus 跨 Tenant fallback 失败
- 19504: 租户上下文缺失（衍生数据写入 `get_current_tenant_id()` 返 None，防 INV-T13 污染）
