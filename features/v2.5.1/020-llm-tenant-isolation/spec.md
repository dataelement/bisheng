# Feature: F020-llm-tenant-isolation (LLM 服务多租户隔离)

**关联 PRD**: [../../../docs/PRD/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md](../../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20多租户需求文档.md) §7.1
**优先级**: P1
**所属版本**: v2.5.1
**模块编码**: 198 (`llm_tenant`)
**依赖**: F011（Tenant 树）+ F013（权限检查链路）+ F019（admin-scope，用于超管切视图）

---

## 1. 概述与用户故事

**故事 A（Root 统一管控）**：
作为 **集团 IT 全局超管**，
我希望 **在 Root 注册统一模型服务（Azure OpenAI、自建 vLLM 等）并默认对所有子公司可见**，
以便 **集团内多数子公司共享统一的模型采购/合规审批结果**。

**故事 B（Child 独立配置）**：
作为 **子公司的 Child Admin**（例如数据敏感子公司），
我希望 **在本 Child 内自主注册独立的模型端点（API Key、区域端点、成本分账独立）**，
以便 **满足本子公司的合规、数据安全、成本管控要求，而不需要经过集团 IT 审批**。

**故事 C（超管跨 Child 管理）**：
作为 **全局超管**，
我希望 **切换到某个 Child 的管理视图，查看/配置该 Child 专属的模型**，
以便 **在集团 IT 代管某 Child 的场景下仍能管控模型配置**（走 F019 admin-scope）。

**背景**：2026-04-19 决策 2 + 3 + 4 锁定"Root 默认共享 + Child 完全自主 + 存量零成本升级"。代码侧 `llm_server` / `llm_model` 表已有 `tenant_id` 字段（v2.5.0/F001 迁移落地），但 DAO 全部查询忽略 tenant_id、写操作只放行全局超管；前端 ModelPage 仅按 `user.role === 'admin'` 判断。本 Feature 完成 DAO 租户感知 + 权限降级到 Child Admin + Root 共享只读 + 前端 scope 适配 + 升级兼容。

---

## 2. 验收标准

### 2.1 Root 默认共享（决策 2）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 全局超管 | `POST /api/v1/llm` body `{type: "openai", config: ..., models: [...]}` 不指定 tenant_id | 创建成功，`llm_server.tenant_id = 1`（Root）；默认 `share_to_children = true`（随 `Tenant.share_default_to_children`）；自动写 FGA `{llm_server:id}#viewer → tenant:{root}#shared_to#member` 元组 |
| AC-02 | 全局超管 | `POST /api/v1/llm` body 勾选 `share_to_children: false` | 创建成功；不写 FGA viewer 元组；Child 用户 `GET /api/v1/llm` 不可见此 server |
| AC-03 | Child 用户（叶子=Child 5） | `GET /api/v1/llm` | 返回本 Child 5 模型 + Root 已共享模型（tenant_id IN (5, 1) AND （tenant_id != 1 OR has viewer share_to Child 5 元组）） |
| AC-04 | 全局超管 | 切换已存在 Root 模型为 "仅 Root 使用" → `PUT /api/v1/llm/{id}` body `share_to_children: false` | 更新成功；FGA viewer 元组被删除；Child 用户再调 `GET /api/v1/llm` 不含此 server |

### 2.2 Child Admin 完全自主（决策 3）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-05 | Child Admin（叶子=Child 5） | `POST /api/v1/llm` 注册本 Child 模型 | 创建成功；`llm_server.tenant_id = 5`；不写 FGA shared_to 元组；仅 Child 5 用户可见 |
| AC-06 | Child Admin（叶子=Child 5） | `PUT /api/v1/llm/{child_5_own_id}` 修改本 Child 自注册模型 | 更新成功 |
| AC-07 | Child Admin（叶子=Child 5） | `DELETE /api/v1/llm/{child_5_own_id}` 删除本 Child 自注册模型 | 删除成功；级联撤销相关 FGA 元组 |
| AC-08 | Child Admin（叶子=Child 5） | `PUT /api/v1/llm/{root_shared_id}` 修改 Root 共享模型 | HTTP 403 + 错误码 `19801` `llm_model_shared_readonly` |
| AC-09 | Child Admin（叶子=Child 5） | `DELETE /api/v1/llm/{root_shared_id}` 删除 Root 共享模型 | HTTP 403 + 错误码 `19801` |
| AC-10 | Child Admin（叶子=Child 5） | `PUT /api/v1/llm/{child_7_own_id}` 修改 Child 7 的模型 | HTTP 404（不在可见集合）或 403（依赖 DAO 前置过滤） |
| AC-11 | Child Admin（叶子=Child 5） | `PUT /api/v1/llm/workbench` 等系统级配置端点 | HTTP 403 + 错误码 `19803` `llm_system_config_forbidden`（系统级 workbench/knowledge/assistant/evaluation/workflow 模型配置仍保留为全局超管独有）|
| AC-12 | Child Admin | 所有 LLM CRUD 操作 | 强制写 `audit_log`，action=`llm.server.{create,update,delete}` / `llm.model.{...}`，payload 含 endpoint URL、`api_key_hash`（不记录明文）、operator_id、operator_tenant_id |

### 2.3 全局超管 + admin-scope（F019 集成）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-13 | 全局超管（已设 F019 scope=Child 5） | `GET /api/v1/llm` | 返回结果等价于 Child 5 视角：Child 5 模型 + Root 共享模型 |
| AC-14 | 全局超管（已设 scope=Child 5） | `POST /api/v1/llm` 在 Child 5 内注册模型 | 创建成功，`tenant_id = 5`；与 Child Admin 行为一致 |
| AC-15 | 全局超管（未设 scope） | `GET /api/v1/llm` | 返回 Root 下全部模型（含 `share_to_children=false` 的 Root 专用） |

### 2.4 存量升级零成本（决策 4）

| ID | 场景 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-16 | v2.4 升级到 v2.5.1，首次启动 | 检查 `llm_server` / `llm_model` 所有记录 | `tenant_id = 1`（Root），由 v2.5.0/F001 迁移保障 |
| AC-17 | 升级后首次挂载 Child | 弹窗预览 Root 共享模型列表 | 展示将自动分发给该 Child 的模型名称、model_type、endpoint 域；提供"不自动分发"选项 |
| AC-18 | 升级后挂载 Child 默认选项 | 完成挂载 | 所有存量 Root 模型立即对该 Child 可见（Child 用户 `GET /api/v1/llm` 验证） |
| AC-19 | 升级后挂载 Child 选"不自动分发" | 完成挂载 | Child 用户初始不可见任何 Root 共享模型；由超管后续逐个开启共享 |
| AC-20 | 存量知识库（`knowledge.model_id` 引用 Root 模型）在 Child 5 | 调用知识库检索 | 正常工作（Root 模型默认对 Child 5 可见） |
| AC-21 | 存量知识库引用的 Root 模型被改为"仅 Root 使用" | 调用知识库检索 | 抛 19802 `llm_model_not_accessible`；前端提示"模型不可用" |

### 2.5 跨 Tenant 模型引用

| ID | 场景 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-22 | Child 5 知识库引用模型 id=100（tenant_id=5） | Child 5 用户调用 | 正常工作 |
| AC-23 | Child 5 知识库引用模型 id=100（被管理员改为 tenant_id=7） | Child 5 用户调用 | 抛 19802 `llm_model_not_accessible`；外键 `knowledge.model_id` 保留原值不清洗（对齐 INV-T4） |
| AC-24 | Child Admin 提交 Child 5 知识库配置选型时 | 调用 `PUT /api/v1/knowledge/{id}` body `model_id=100` | 后端校验 model.tenant_id ∈ `{5, 1}`；不满足则 400 + 19802 |

---

## 3. 边界情况

- **`tenant_id=0` 系统级语义废弃**：v2.4 历史上可能存在 `llm_server.tenant_id=0` 的记录，F001 迁移脚本已回填为 1；若后续发现残留，按 Root 处理即可
- **LLM 调用量归属**（INV-T13）：Child 用户调用 Root 共享模型 → `chat_message.tenant_id = Child 叶子`、token 计入 Child 配额；由 F017 §5.4 `ChatMessageService` / `LLMTokenTracker` 承载
- **Root 共享开关的 FGA 语义**：复用 `tenant#shared_to#member`，不新增 `is_shared_to_children` 列；`PUT` 切换开关时 DAO 层补写/撤销对应 FGA 元组
- **`llm_server.config` 中的 API Key**：仍加密存储（沿用现有 Fernet 机制），但 audit_log payload 仅记录 `api_key_hash = sha256(api_key)[:16]`，不留明文
- **endpoint 白名单 config** (`llm.endpoint_whitelist`)：默认空 = 不限制；若客户启用（如 `["https://api.openai.com", "https://*.azure.com"]`），Child Admin 注册 LLM Server 时后端校验 `config.endpoint` 必须匹配某一前缀，否则 400 + 19804 `llm_endpoint_not_whitelisted`；全局超管不受限
- **同名冲突**：LLM Server `name` 字段原先全局唯一；v2.5.1 将 `UNIQUE(name)` 改为 `UNIQUE(tenant_id, name)`，允许 Child 5 和 Child 7 都注册 `Azure-GPT-4`（需 DDL 变更，列入任务清单）
- **多租户关闭时**（`multi_tenant.enabled=false`）：API 兼容，LLMDao 查询按 `tenant_id=1` 过滤；写操作仅全局超管可用（无 Child Admin 概念）
- **前端 scope 切换器仅对超管可见**：Child Admin 的 ModelPage 顶部无切换器，直接展示本 Child 模型 + Root 共享（只读）

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 |
|----|------|------|------|
| AD-01 | Root 共享机制 | A: 新增 `is_shared_to_children` 列 / B: 复用 FGA `tenant#shared_to#member` | B（与 F017 共享资源机制同构，避免多套语义） |
| AD-02 | LLMDao 改造方式 | A: 所有方法签名加 `tenant_id` / B: 沿 §4.1 SQLAlchemy event 自动注入 | B（零签名破坏，向后兼容） |
| AD-03 | Router 权限依赖 | A: 保持 `get_admin_user`（仅全局超管）/ B: 新增 `get_tenant_admin_user`（全局超管 + Child Admin 本 scope） | B（落地决策 3 Child 自主）|
| AD-04 | Child Admin 对 Root 共享模型 | A: 可编辑 / B: 只读 | B（决策 2 锁定 Root 统一管控） |
| AD-05 | endpoint 白名单 | A: 必须启用 / B: 可选 config | B（默认宽松，合规客户按需启用） |
| AD-06 | 跨 Tenant 模型引用失败 | A: 级联清理外键 / B: 保留 id + 运行时报错 | B（对齐 INV-T4，便于管理员排查）|
| AD-07 | 系统级 `/llm/workbench` 等配置 | A: 降级 Child Admin 可改 / B: 保留全局超管独有 | B（工作台默认模型等是集团级决策，避免 Child 误改影响全局）|
| AD-08 | 名称唯一约束 | A: 全局唯一 / B: Tenant 内唯一 | B（允许不同 Child 重名，符合子公司独立命名习惯）|

---

## 5. 核心实现

### 5.1 LLMDao 改造

查询方法沿用 §4.1 SQLAlchemy event 自动注入 `WHERE tenant_id IN (...)`；无需修改方法签名。

写方法显式处理：

```python
# src/backend/bisheng/llm/domain/models/llm_server.py

class LLMDao:

    @classmethod
    async def ainsert_server_with_models(cls, server: LLMServer, models: list[LLMModel]):
        # tenant_id 由 get_current_tenant_id() 填充（admin-scope 优先；否则 JWT leaf）
        current_tenant = get_current_tenant_id()
        server.tenant_id = current_tenant
        for m in models:
            m.tenant_id = current_tenant

        # 2026-04-19：Child Admin 注册端点白名单校验（AD-05 可选 config；默认空=不限制）
        # 全局超管不受限（合规客户可选启用）
        operator = get_current_user()
        if not operator.is_global_super and settings.llm.endpoint_whitelist:
            endpoint = (server.config or {}).get("endpoint", "")
            if not any(endpoint.startswith(prefix) for prefix in settings.llm.endpoint_whitelist):
                raise BusinessError(19804, "llm_endpoint_not_whitelisted")

        async with get_async_db_session() as session:
            session.add(server)
            await session.flush()
            for m in models:
                m.server_id = server.id
            session.add_all(models)
            await session.commit()
            await session.refresh(server)

        # 默认共享：tenant_id=Root 且未显式关闭 share_to_children
        tenant = await TenantDao.aget(current_tenant)
        if tenant.parent_tenant_id is None and tenant.share_default_to_children:
            # Root + 默认共享开启
            if getattr(server, "_explicit_share", True):  # 创建请求默认 True
                await FGAClient.write_tuple(
                    user=f"tenant:{current_tenant}#shared_to#member",
                    relation="viewer",
                    object=f"llm_server:{server.id}",
                )

        return server

    @classmethod
    async def aupdate_server_share(cls, server_id: int, share_to_children: bool, operator: UserPayload):
        """切换 Root 模型的共享开关（仅全局超管）"""
        server = await cls.aget_server_by_id(server_id)
        if not server or server.tenant_id != ROOT_TENANT_ID:
            raise BusinessError(19802, "llm_model_not_accessible")
        if not operator.is_global_super:
            raise BusinessError(19801, "llm_model_shared_readonly")

        tuple_args = dict(
            user=f"tenant:{ROOT_TENANT_ID}#shared_to#member",
            relation="viewer",
            object=f"llm_server:{server_id}",
        )
        if share_to_children:
            await FGAClient.write_tuple(**tuple_args)
        else:
            await FGAClient.delete_tuple(**tuple_args)

    @classmethod
    async def aupdate_server_with_models(cls, server_id: int, data: dict, operator: UserPayload):
        """Child Admin 修改本 Child 模型 / 全局超管修改任何"""
        server = await cls.aget_server_by_id(server_id)  # 已被 IN 列表过滤
        if not server:
            raise BusinessError(19802, "llm_model_not_accessible")

        # Root 共享模型 + Child Admin → 拒绝
        if server.tenant_id == ROOT_TENANT_ID and not operator.is_global_super:
            raise BusinessError(19801, "llm_model_shared_readonly")

        # 正常更新...
```

### 5.2 Router 权限降级

```python
# src/backend/bisheng/llm/api/router.py

from bisheng.common.dependencies import get_tenant_admin_user, get_admin_user

@router.post("")
async def create_llm(data: LLMServerCreate, user: UserPayload = Depends(get_tenant_admin_user)):
    # 2026-04-19: get_admin_user → get_tenant_admin_user
    ...

@router.put("/{id}")
async def update_llm(id: int, data: LLMServerUpdate, user: UserPayload = Depends(get_tenant_admin_user)):
    ...

@router.delete("/{id}")
async def delete_llm(id: int, user: UserPayload = Depends(get_tenant_admin_user)):
    ...

# 系统级配置保留 get_admin_user
@router.post("/workbench")
async def set_workbench_config(data: WorkbenchConfig, user: UserPayload = Depends(get_admin_user)):
    ...
```

新增依赖：

```python
# src/backend/bisheng/common/dependencies/user_deps.py

async def get_tenant_admin_user(user: UserPayload = Depends(UserPayload.get_login_user)) -> UserPayload:
    if user.is_global_super or user.is_child_admin:
        return user
    raise HTTPException(status_code=403, detail={"code": 19801, "msg": "tenant_admin_required"})
```

### 5.3 前端 Scope 切换器

```tsx
// src/frontend/platform/src/pages/ModelPage/manage/index.tsx

const { user } = useUser();
const { scope, setScope } = useAdminScope();  // 新 hook

return (
  <div>
    {user.is_global_super && (
      <TenantScopeTabs
        value={scope.scope_tenant_id ?? 'global'}
        tenants={[
          { value: 'global', label: '全局' },
          { value: 1, label: 'Root' },
          ...childTenants,
        ]}
        onChange={async (v) => {
          await setScope(v === 'global' ? null : Number(v));
          refetch();
        }}
      />
    )}
    {user.is_child_admin && !user.is_global_super && (
      <h2>管理 {user.leaf_tenant_name} 的模型</h2>
    )}
    <LLMServerList servers={servers} onEdit={handleEdit} />
  </div>
);

function LLMServerList({ servers }) {
  return servers.map((s) => (
    <Card key={s.id}>
      <h3>{s.name}</h3>
      {s.tenant_id === ROOT_TENANT_ID && user.leaf_tenant_id !== ROOT_TENANT_ID && (
        <Badge>Root 共享（只读）</Badge>
      )}
      <Button
        disabled={s.tenant_id === ROOT_TENANT_ID && !user.is_global_super}
        onClick={() => handleEdit(s)}
      >
        编辑
      </Button>
    </Card>
  ));
}
```

### 5.4 知识库/工作流调用链校验

```python
# src/backend/bisheng/llm/domain/services/llm_service.py

class LLMService:
    @classmethod
    async def get_model_for_call(cls, model_id: int) -> LLMModel:
        model = await LLMDao.aget_model_by_id(model_id)  # 自动 tenant 过滤
        if not model:
            raise BusinessError(19802, "llm_model_not_accessible")
        return model
```

知识库检索入口：

```python
# src/backend/bisheng/knowledge/domain/services/retrieval.py
model = await LLMService.get_model_for_call(knowledge.model_id)
# 若拿不到，向上抛 19802，前端 controllers/request.ts 拦截器捕获后通过 toast 提示：
#   "该知识库引用的模型已不可用，请联系管理员更新模型选项"
# 外键 knowledge.model_id 保留原值不清洗（对齐 INV-T4：资源数据不跟归属/可见性变更迁移）
```

### 5.5 DDL 变更

```sql
-- src/backend/bisheng/database/migrations/v2_5_1_f020_llm_tenant.py

-- STEP 1：前置校验（存量 (tenant_id, name) 组合必须已经唯一，否则 ADD UNIQUE 会失败）
--   v2.5.0/F001 已为 llm_server 添加 tenant_id 字段并回填为 1（Root），此时若 v2.4 历史存在
--   重名 server（原 UNIQUE(name) 保障了旧数据全局唯一），现所有 tenant_id=1 下应仍唯一，不会冲突。
--   但保险起见迁移脚本 upgrade() 函数首行执行检查：
-- SELECT tenant_id, name, COUNT(*) FROM llm_server GROUP BY tenant_id, name HAVING COUNT(*) > 1;
--   若返回任意行，迁移中止并抛 `DuplicateNameBeforeMigration` 异常（附冲突清单），由 DBA 手工
--   重命名冲突记录（如附 `-dup-{id}` 后缀）后再重跑迁移。

-- STEP 2：删旧索引（v2.5.0 的 UNIQUE(name)）
ALTER TABLE llm_server DROP INDEX name;

-- STEP 3：建新复合唯一索引
ALTER TABLE llm_server ADD UNIQUE KEY uk_llm_server_tenant_name (tenant_id, name);

-- 注：llm_model 的 UNIQUE(server_id, model_name) 不需要改（server 粒度已隔离）
```

**Alembic 脚本骨架**（`upgrade()` 函数）：

```python
def upgrade():
    # STEP 1：前置校验
    result = op.get_bind().execute(text("""
        SELECT tenant_id, name, COUNT(*) AS cnt
        FROM llm_server GROUP BY tenant_id, name HAVING cnt > 1
    """)).fetchall()
    if result:
        conflicts = "\n".join(f"  tenant_id={r.tenant_id}, name={r.name}, count={r.cnt}" for r in result)
        raise RuntimeError(
            f"llm_server 存在 (tenant_id, name) 重复记录，迁移中止：\n{conflicts}\n"
            f"请 DBA 手工去重后重跑 alembic upgrade。"
        )

    # STEP 2 + 3
    op.drop_index('name', table_name='llm_server')
    op.create_index('uk_llm_server_tenant_name', 'llm_server', ['tenant_id', 'name'], unique=True)
```

---

## 6. 错误码

| 错误码 | 含义 | HTTP |
|--------|------|------|
| `19801` | `llm_model_shared_readonly` — Child Admin 尝试修改 Root 共享模型 | 403 |
| `19802` | `llm_model_not_accessible` — 目标 model 不在当前可见集合（包括跨 Tenant 引用失败） | 404 |
| `19803` | `llm_system_config_forbidden` — Child Admin 尝试修改系统级 workbench/knowledge 配置 | 403 |
| `19804` | `llm_endpoint_not_whitelisted` — Child Admin 注册的 endpoint 不在 config 白名单 | 400 |

---

## 7. 配置项

```yaml
# config.yaml
llm:
  endpoint_whitelist: []       # Child Admin 注册 LLM Server 时 endpoint 前缀白名单；默认空=不限制

multi_tenant:
  group_shared_by_default: true  # Root 创建资源是否默认共享（已有）
```

---

## 8. 关键文件

| 类别 | 文件 | 改动 |
|------|------|------|
| DAO | `src/backend/bisheng/llm/domain/models/llm_server.py` | 全部查询方法 tenant 感知（沿 §4.1 event）；`ainsert_server_with_models` 填充 tenant_id + 写 FGA viewer 元组；新增 `aupdate_server_share`；`aupdate_server_with_models` / `adelete_server_by_id` 加写权限校验 |
| Router | `src/backend/bisheng/llm/api/router.py` | `POST/PUT/DELETE /llm` 依赖改 `get_tenant_admin_user`；保留 `POST /llm/workbench` 等系统级端点为 `get_admin_user`；`PUT /llm/{id}/share` 新端点 |
| Service | `src/backend/bisheng/llm/domain/services/llm_service.py` | 调用链入口 `get_model_for_call` 抛 19802 |
| 依赖 | `src/backend/bisheng/common/dependencies/user_deps.py` | 新增 `get_tenant_admin_user` |
| 迁移 | `src/backend/bisheng/database/migrations/v2_5_1_f020_llm_tenant.py` | 唯一索引改 `(tenant_id, name)` |
| 错误码 | `src/backend/bisheng/common/errcode/llm_tenant.py` | 新建；19801~19804 |
| 审计 | `src/backend/bisheng/llm/api/router.py` | CRUD 统一写 audit_log |
| 前端（全局复用，**本 Feature 拥有**） | `src/frontend/platform/src/components/AdminScopeSelector.tsx`（新） | **由本 Feature 抽取实现**（F019 §9 Out-of-scope 明确剥离给 F020），供 ModelPage（首个消费方）+ 未来 RolesPage / QuotaPage / AuditLogPage 复用；Props: `{value, onChange, tenants, disabled}`；底层调用 F019 的 `useAdminScope` hook |
| 前端 | `src/frontend/platform/src/pages/ModelPage/manage/index.tsx` | 顶部挂载 `<AdminScopeSelector>`（仅超管可见）；Root 共享 Badge；编辑按钮 disabled 规则 |
| 前端 | `src/frontend/platform/src/pages/ModelPage/manage/SystemModelConfig.tsx` | Child Admin 隐藏此组件 |
| 前端 | `src/frontend/platform/src/contexts/userContext.tsx` | 扩展 `user.is_global_super / is_child_admin / leaf_tenant_id / leaf_tenant_name` |
| 前端 | `src/frontend/platform/src/hooks/useAdminScope.ts`（新） | 读/写 F019 scope API |
| 挂载弹窗 | `src/frontend/platform/src/pages/TenantPage/MountDialog.tsx`（可能合作在 F011） | 新增"预览将自动分发的 Root 模型列表" + "不自动分发"选项 |

---

## 9. 不做的事（Out of Scope）

- LLM Server 的物理隔离（独立 Kubernetes Namespace 等）
- Child Admin 注册模型的合规性自动审核
- 跨 Child 的模型调用分账看板（留给 v2.6+ 商业化）
- `llm_model.tenant_id` 独立变更（模型应随 server 一起归属；不提供"单独迁移模型"接口）
- "逐资源分发共享"精细能力（由 F017 承载，本 Feature 仅对接挂载弹窗的"不自动分发"选项）

---

## 10. 依赖清单

| 依赖 | 说明 |
|------|------|
| F011 | Tenant 树数据模型 + `Tenant.share_default_to_children` 字段；挂载 Child 工作流（挂载弹窗"不自动分发"选项由 F011 UI 实现，本 feature AC-17~19 仅提供"可见模型列表查询" + UI 文案） |
| F013 | 权限检查链路（IN 列表过滤、super_admin 短路、Child admin 短路）+ `tenant#shared_to#member` FGA 关系 |
| F017 | Root 共享资源的 `shared_to` 元组机制（本 Feature 复用同一套 FGA 关系）；§5.4 衍生数据写入层（Child 用户调 Root 共享 LLM → token 计入 Child，本 feature 只依赖结果） |
| F019 | admin-scope（全局超管切换到 Child 5 视图后，本 Feature 所有端点自动按 Child 5 上下文运行） |
| **新依赖** | `src/backend/bisheng/common/dependencies/user_deps.py::get_tenant_admin_user`（本 feature 新增，允许 Child Admin 操作本 Child LLM、全局超管操作任意 Tenant；见 §5.2） |
| INV-T15 / INV-T16 | 本 Feature 落地的不变量 |

---

## 11. 相关文档

- PRD §1.1 背景（模型服务默认统一、可按 Child 扩展）
- PRD §3.3 Child Admin 能力清单（LLM CRUD + token 配额 + Root 共享只读）
- PRD §7.1 LLM 模型服务（Root 共享 + Child 扩展）——本 Feature 的主需求章节
- PRD §5.2.1 挂载 Child 弹窗 review 步骤
- PRD §10.4 废弃 API 说明（与 admin-scope 区别）
- 技术方案 §11.2 权限检查链路
- 技术方案 §11.7 关键修改文件清单
- 升级迁移方案 §3.7 LLM 模型升级行为
- release-contract INV-T15 / INV-T16 / 模块编码 198
