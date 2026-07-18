# Feature: F022-llm-system-config-tenant-isolation (LLM 系统模型默认配置按租户隔离)

**关联 PRD**: [../../../docs/archive/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md](../../../docs/archive/2.5%20权限管理体系改造%20PRD/2.5%20多租户需求文档.md) §7.1（"Root 共享 + Child 扩展"延伸）
**优先级**: P1
**所属版本**: v2.5.1
**模块编码**: 沿用 198（`llm_tenant`），不新增模块编码
**依赖**: F011（Tenant 树 + `share_default_to_children`）+ F012（admin-scope ContextVar + `get_current_tenant_id()`）+ F019（admin-scope 中间件，写侧 tenant 来源）+ F020（LLM 服务多租户隔离，本 Feature 修订其 AD-07 + AC-11）

> **本 Feature 修订 F020 spec 的两处决策**：
> - **F020 AD-07**（"系统级 `/llm/workbench` 等配置保留为全局超管独有"）→ 本期修订为：5 类系统级模型默认配置按租户隔离，Child Admin 自主配置本 Child；Root 共享通过 `share_default_to_children` 兜底（与 LLM Server 共享语义对齐）
> - **F020 AC-11**（"Child Admin 调 `PUT /api/v1/llm/workbench` 返 19803"）→ 本期修订为：Child Admin 调用时操作的是**自己 Child 的配置**，返 200；只有跨 tenant 写入（target_tenant_id ∉ user.manageable_tenant_ids）才返 403 + 19803

---

## 1. 概述与用户故事

**故事 A（Child 自主默认模型）**：
作为 **子公司 Child Admin**（数据敏感子公司），
我希望 **为本 Child 配置独立的"知识库默认模型 / 助手默认模型 / 工作流默认模型 / 评测模型 / 工作台 ASR/TTS 模型"**，
以便 **本 Child 内的知识库导入、Agent 节点、评测任务都使用 Child 自己的模型(不继承 Root 的全局选择)，与本 Child 自注册的 LLM Server 配套使用，满足合规、成本分账、数据安全要求**。

**故事 B（Root 全局兜底）**：
作为 **集团 IT 全局超管**，
我希望 **在 Root 配置一份"集团默认模型选择"，对所有未自主配置的 Child 自动生效**，
以便 **新挂 Child 无需手动配置即可立即可用，沿用集团统一的模型采购/合规审批结果**。

**故事 C（超管跨 Child 代管）**：
作为 **全局超管**，
我希望 **切换到某个 Child 的管理视图（admin-scope），代该 Child 配置/调整其默认模型选择**，
以便 **集团 IT 代管某 Child 时仍能管控其默认模型，且不污染 Root 的配置**。

**故事 D（消费侧自然继承）**：
作为 **子公司用户**，
我希望 **导入知识库 / 触发工作流 / 创建助手 / 触发评测 / 使用工作台 ASR-TTS 时，自动使用本 Child 的默认模型选择**，
以便 **不需要在每个业务入口手动选模型，且不会"逃逸"使用其他 Child 的模型**。

**背景**：F020 落地完成 LLM Server / LLM Model 的按租户隔离，但**系统级默认模型选择**（`Config.key ∈ {knowledge_llm, assistant_llm, evaluation_llm, workflow_llm, linsight_llm}` 共 5 类）仍存于全局唯一的 `Config` 表行(v2.5.0 F001 主迁移注释 `Excluded: ..., config, ...` 主动排除)，admin-scope 中间件不读这 5 个端点。F020 AD-07 当时选"保留全局超管独有"是基于"全局共享"假设的合理决策；本 Feature 把存储语义升级为按租户隔离后，该担心不再成立，遂修订 AD-07 与 AC-11，实现完整的 LLM 多租户隔离闭环。错误码 19803（`llm_system_config_forbidden`）当时已在 `bisheng/common/errcode/llm_tenant.py:25` 预留定义，本 Feature 修订其触发语义并落地实际使用。

---

## 2. 验收标准

> AC-ID 在本 Feature 内唯一，格式 `AC-NN`。
> tasks.md 中的测试任务必须通过 `覆盖 AC: AC-NN` 追溯到此表。

### 2.1 Root 默认 + Child 自主（核心隔离）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 全局超管（无 admin-scope） | `POST /api/v1/llm/knowledge` body `{llm_model_id: 11, embedding_model_id: 12, rerank_model_id: 13}` | 200；`tenant_system_model_config(tenant_id=1, key='knowledge_llm', value=<json>)` 写入；不写其他 tenant 行 |
| AC-02 | 全局超管（无 admin-scope） | `GET /api/v1/llm/knowledge` | 200；`data` 含 AC-01 写入的内容；响应增加字段 `inherited_from_root: false` |
| AC-03 | Child Admin（叶子=Child 5） | `GET /api/v1/llm/knowledge` 且本 Child 5 未配置 + Root.share_default_to_children=1 | 200；`data` 等于 Root 行配置；`inherited_from_root: true` |
| AC-04 | Child Admin（叶子=Child 5） | `POST /api/v1/llm/knowledge` body 修改任一字段 | 200；`tenant_system_model_config(tenant_id=5, ...)` 写入；下次 GET 返回 Child 5 自身行；`inherited_from_root: false` |
| AC-05 | Child Admin（叶子=Child 5） | 已自主配置后再 `GET` | 200；返回 Child 5 自身配置；`inherited_from_root: false` |
| AC-06 | Child Admin（叶子=Child 5） | 本 Child 5 未配置 + Root.share_default_to_children=0 + Root 行存在 | 200；`data` 为空（各字段 null）；`inherited_from_root: false`；`fallback_blocked: true`；前端提示"Root 未开启共享，请联系超管配置或手动配置本 Child" |
| AC-07 | Child Admin（叶子=Child 5） | 本 Child 5 未配置 + Root 也未配置 | 200；`data` 为空（各字段 null）；`inherited_from_root: false`；`fallback_blocked: false` |

### 2.2 admin-scope（修订 F020 AC-11）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-08 | 全局超管（已设 admin-scope=Child 5） | `POST /api/v1/llm/knowledge` body 任意 | 200；写入 `tenant_id=5` 行；行为等价于 Child 5 Admin 自主配置 |
| AC-09 | 全局超管（已设 admin-scope=Child 5） | `GET /api/v1/llm/knowledge` | 200；返回 Child 5 行（若有）或 Root fallback；与 Child 5 Admin 视角一致 |
| AC-10 | Child Admin（叶子=Child 5）| 通过构造请求绕前端，`POST /api/v1/llm/knowledge` body 试图写入 `tenant_id=1`（Root） | 403 + 错误码 19803 `llm_system_config_forbidden`；`tenant_system_model_config` 内 Root 行不变 |
| AC-11 | Child Admin（叶子=Child 5）| `POST /api/v1/llm/knowledge` 走正常路径（admin-scope 不会注入跨 tenant） | 200；`get_current_tenant_id()` = 5（Child 5 没有 admin-scope 写入权限，决策 1 限制 admin-scope 仅超管）；落到 `tenant_id=5` 行 |

> **修订声明**：本 AC-10 / AC-11 共同取代 F020/AC-11 的"Child Admin 写 system 配置一律返 19803"。F020 spec.md 应被打补丁——本期修订 F020 spec.md 表 §2.2 的 AC-11 行为描述（详见 §11 相关文档）。

### 2.3 5 类配置覆盖（不只是 Knowledge）

| ID | 配置类 | 端点 | 预期 key |
|----|------|------|---------|
| AC-12 | Workbench | `GET/POST /api/v1/llm/workbench` | `linsight_llm` |
| AC-13 | Knowledge | `GET/POST /api/v1/llm/knowledge` | `knowledge_llm` |
| AC-14 | Assistant | `GET/POST /api/v1/llm/assistant` | `assistant_llm` |
| AC-15 | Evaluation | `GET/POST /api/v1/llm/evaluation` | `evaluation_llm` |
| AC-16 | Workflow | `GET/POST /api/v1/llm/workflow` | `workflow_llm` |

每条 AC 都按 AC-01~AC-11 的语义在自己的 endpoint 上验证一遍（自测清单展开为 5 × 11 = 55 条 case，但 ac-verification.md 阶段可压缩为参数化测试）。

### 2.4 消费侧 tenant 解析（INV-T18 落地）

| ID | 场景 | tenant 来源 | 预期 |
|----|------|------|---------|
| AC-17 | Child 5 用户上传文件到 Child 5 知识库 → 后台抽取标题 | resource owner（`Knowledge.tenant_id=5`） | `LLMService.get_knowledge_llm(tenant_id=5)` 调用，使用 Child 5 的配置或 Root fallback |
| AC-18 | 全局超管（admin-scope=Child 5）触发同一知识库的导入 | resource owner（`Knowledge.tenant_id=5`） | 同 AC-17，**不**因为操作人是超管而误用 Root 配置 |
| AC-19 | Child 5 用户在 Flow（tenant_id=5）的 Agent 节点执行 | resource owner（`Flow.tenant_id=5`） | `sync_get_assistant_llm(tenant_id=5)` 调用 |
| AC-20 | Child 5 用户在 Workflow input 节点引用了 Root 共享的知识库（KB.tenant_id=1） | KB owner 优先（KB.tenant_id=1） | `get_knowledge_default_embedding(tenant_id=1)` 调用，使用 Root 的 embedding（保证向量库一致性） |
| AC-21 | Child 5 用户创建新助手（资源未落库） | 调用人 tenant（`get_current_tenant_id()=5`） | `get_assistant_llm()` 默认入参，从 ContextVar 取 |
| AC-22 | Child 5 用户使用 Workbench ASR | 调用人 tenant | `get_workbench_llm()` 默认入参，从 ContextVar 取 |
| AC-23 | Celery 异步知识库导入 worker 执行 | task payload 显式带的 `tenant_id` | worker 进程 ContextVar 为空，**必须**从 task payload 取 `tenant_id` 并显式传入 service；漏传时 fallback Root + warn log |
| AC-24 | Celery 异步评测 worker 执行 | task payload 显式带的 `tenant_id` | 同 AC-23 |

### 2.5 存量升级零成本（继承 INV-T16）

| ID | 场景 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-25 | v2.5.0 已部署且 Root 已配置 5 类全局 key → upgrade alembic head | `tenant_system_model_config` 表 5 行（key ∈ 5 类，tenant_id=1）；`config` 表旧 5 行不删 | DAO 切到新表读写；旧 `config` 行变孤儿但不影响运行 |
| AC-26 | v2.5.0 升级 + Root.share_default_to_children=1 + 已挂 Child 5 | Child 5 Admin 登录立即 `GET /api/v1/llm/knowledge` | 返回 Root 行（fallback），`inherited_from_root: true` |
| AC-27 | 升级后 Root.share_default_to_children=0 + Child 5 未配置 | Child 5 用户触发知识库导入 | service 解析得 `value=None` → 业务侧抛 `NoSystemModelConfigError`，前端提示"未配置默认模型" |
| AC-28 | alembic downgrade f034 → 重新 upgrade | F034 backfill 用 `INSERT IGNORE`，幂等 | 不会插入重复行 |

### 2.6 审计

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-29 | 任何 admin | `POST /api/v1/llm/{type}` | 写 `audit_log`，action=`llm.system_config.update`，metadata 含 `key, target_tenant_id, operator_tenant_id, before, after`（before/after 为脱敏的 model_id 列表，不含 API Key） |

---

## 3. 边界情况

- **5 类齐头并进**：本期不支持"只共享 Workbench 不共享 Knowledge"。`tenant_system_model_config.is_shared_to_children TINYINT(1) DEFAULT NULL` 字段**预留**但不读不写（DAO `aresolve()` 仅看 `Tenant.share_default_to_children`）；未来若细化沿用此字段升级
- **跨级 fallback 不递归**：MVP 锁 2 层 Tenant 树（INV-T1），fallback 链路只有 `Child → Root`；3 层及以上 fallback 留待 v2.6+
- **Root 行不存在 + Root.share=1 时**：等价于"Root 也没配"，AC-07 行为，不抛错
- **`config` 表旧 5 行不删除**：保留作为 alembic downgrade 的安全锚点；upgrade 完成后服务读写切到新表，旧行变孤儿（CI 守卫：`config` 表中 5 个 key 不应再被任何代码路径读取，可加 grep 检测）
- **Child 自主配置后 Root 修改**：Child 已自主配置时，Root 后续修改**不影响** Child（fallback 只在 Child 行不存在时触发）。前端 banner 已说明"未配置项才继承 Root"
- **写侧 `target_tenant_id` 来源**：`get_current_tenant_id()`（含 admin-scope 覆盖）。Child Admin 没有 admin-scope 写入权限（INV-T14 锁仅超管），所以 Child Admin 路径下 `target_tenant_id` 必然 = 自己 leaf；防御性校验 `target_tenant_id ∈ user.manageable_tenant_ids` 兜底（防御构造 PUT 攻击）
- **`get_model_admin_user` 依赖保留**：本 Feature 不降级到 `get_tenant_admin_user`（避免与 F020 LLM Server 的权限语义混淆）；`get_model_admin_user` 已经允许 admin 或带 `model` 菜单的 Child Admin
- **多租户关闭（`multi_tenant.enabled=false`）**：`get_current_tenant_id()` 始终返回 1（Root），所有读写命中 `tenant_id=1` 行，行为兼容 v2.4
- **Workbench 子配置部分共享 vs 全部共享**：Workbench 的 value JSON 是粗粒度的整体（task_model + embedding + asr + tts + knowledge_space_llm + chat_title_llm 等捆绑一起），fallback 是行级粒度（要么整行继承要么整行不继承）。不支持"只继承 ASR 不继承 task_model"

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | **修订 F020 AD-07**：5 类系统级配置是否租户隔离 | A: 保留全局超管独有（F020 现状） / B: 按租户隔离 + Child 自主 | **B** | F020 当时担心"Child 误改影响全局"是基于全局共享假设；隔离后 Child 改自己不影响其他 tenant，担心不成立；隔离后能与 F020 LLM Server 隔离形成完整闭环（Server + Default Selection 同步隔离） |
| AD-02 | 数据存储方案 | A: `config` 表加 `tenant_id` 列 + 复合 unique / B: 新建 `tenant_system_model_config` 表搬出 5 个 key | **B** | `config` 表 v2.5.0 主迁移 `Excluded` 列表是有意识的语义决策（"配置表不是租户资源"）；只升级 5 个 key 为租户资源，搬出去最干净，不污染其他全局 key（`initdb_config` / `web_config` / `home_tags` / `workstation` 等仍真正全局） |
| AD-03 | fallback 共享开关粒度 | A: `Tenant.share_default_to_children` 单一开关，5 类齐头并进 / B: 5 类各自独立开关（新增 5 个布尔列）/ C: 行级 `is_shared_to_children` 列覆盖 | **A**（行级列预留 NULL，本期不读） | F020 决策 2 已锁单一开关；简单 > 灵活；未来要细化时升级到 C，无破坏性 schema 变更 |
| AD-04 | LLMService 方法签名变更方式 | A: 加 `tenant_id: int \| None = None` 可选参数 / B: 不改签名内部走 ContextVar / C: 拆 `get_*_llm()` + `get_*_llm_for_tenant(tenant_id)` 两个方法 | **A** | Celery worker 必须显式传 tenant_id（无 ContextVar），消费侧资源 owner 解析也需显式传；A 兼容现有调用点（不传=走 ContextVar）；B 不支持 worker；C 方法数翻倍且大多数调用点不需要区分 |
| AD-05 | 消费侧 tenant 来源（INV-T18） | A: 全部 resource owner / B: 全部调用人 tenant / C: 资源场景 owner，创建/实时场景调用人 | **C** | 知识库导入/工作流执行/评测必须按 owner（保证向量库一致性、不"逃逸"），但创建/实时场景资源未落库 → 用调用人 tenant 是唯一合理选择 |
| AD-06 | Migration 是否清理旧 `config` 5 行 | A: F034 upgrade 时 DELETE 旧 5 行 / B: 保留旧行作 rollback 锚点 | **B** | downgrade 时直接 DROP 新表即可恢复旧行为；旧行不影响运行（service 读写切到新表）；CI 守卫 grep 监控 `config` 表中 5 个 key 是否还被代码读 |
| AD-07 | 错误码新建 vs 沿用 19803 | A: 沿用 19803，修订 Msg / B: 新增 19805 区分语义 | **A**（修订 Msg） | 19803 当时定义就是为本 Feature 预留（语义"system config write forbidden"未变）；只是触发条件从"任何 Child Admin 写"改为"跨 tenant 写"，错误码本身语义没变 |
| AD-08 | 模块编码 | A: 沿用 198 / B: 新增 199 `llm_system_config` | **A** | F022 是 F020 的延伸，错误码沿用 19803（已在 198 模块下），不需要新模块编码 |
| AD-09 | 写侧权限校验位置 | A: router 层 / B: service 层 / C: 双重 | **C** | router 层判 `target_tenant_id ∈ user.manageable_tenant_ids` 早失败；service 层最后兜底（防绕过 router 的内部调用错误） |

---

## 5. 数据模型

### 5.1 `tenant_system_model_config` 表

```python
# src/backend/bisheng/llm/domain/models/tenant_system_model_config.py

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, SmallInteger, String, UniqueConstraint, text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class TenantSystemModelConfig(SQLModelSerializable, table=True):
    __tablename__ = 'tenant_system_model_config'

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(
        sa_column=Column(Integer, nullable=False, index=True,
                         comment='Owner tenant; 1=Root, others=Child leaf'),
    )
    key: str = Field(
        sa_column=Column(String(64), nullable=False, index=True,
                         comment='ConfigKeyEnum value: linsight_llm/knowledge_llm/...'),
    )
    value: Optional[str] = Field(
        default=None,
        sa_column=Column(LONGTEXT, nullable=True, comment='JSON-encoded config payload'),
    )
    is_shared_to_children: Optional[int] = Field(
        default=None,
        sa_column=Column(SmallInteger, nullable=True,
                         comment='Reserved (v2.6+): row-level override of Tenant.share_default_to_children; NULL=use tenant default'),
    )
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')),
    )
    update_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')),
    )

    __table_args__ = (
        UniqueConstraint('tenant_id', 'key', name='uq_tenant_system_model_tenant_key'),
        {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"},
    )
```

### 5.2 Domain DTO（响应增加 fallback 元信息）

```python
# src/backend/bisheng/llm/domain/schemas/system_model.py

from pydantic import BaseModel
from typing import Optional


class SystemModelConfigEnvelope(BaseModel):
    """Generic envelope returned by all 5 GET endpoints, wrapping the legacy
    typed config objects (KnowledgeLLMConfig / AssistantLLMConfig / ...).

    `inherited_from_root=True` means current tenant has no row, the value
    came from Root via Tenant.share_default_to_children fallback.

    `fallback_blocked=True` means current tenant has no row AND Root has a row
    AND Root.share_default_to_children=0 — the frontend should hint that
    Root has not opted into sharing.
    """
    data: dict  # The original 5 typed configs (KnowledgeLLMConfig.dict() etc.)
    inherited_from_root: bool = False
    fallback_blocked: bool = False
```

---

## 6. API 契约

### 6.1 端点（5 组路由不变；行为变更）

| Method | Path | 描述 | 认证 | 隔离行为 |
|--------|------|------|------|---------|
| GET | `/api/v1/llm/workbench` | 读 Workbench（Linsight）默认配置 | `get_login_user` | 读 `tenant_id=get_current_tenant_id()` 行；fallback Root |
| POST | `/api/v1/llm/workbench` | 写 Workbench 默认配置 | `get_model_admin_user` | 写 `tenant_id=get_current_tenant_id()` 行；权限校验 |
| GET | `/api/v1/llm/knowledge` | 读 Knowledge 默认配置 | `get_login_user` | 同上 |
| POST | `/api/v1/llm/knowledge` | 写 Knowledge 默认配置 | `get_model_admin_user` | 同上 |
| GET | `/api/v1/llm/assistant` | 读 Assistant 默认配置 | `get_login_user` | 同上 |
| POST | `/api/v1/llm/assistant` | 写 Assistant 默认配置 | `get_model_admin_user` | 同上 |
| GET | `/api/v1/llm/evaluation` | 读 Evaluation 默认配置 | `get_login_user` | 同上 |
| POST | `/api/v1/llm/evaluation` | 写 Evaluation 默认配置 | `get_model_admin_user` | 同上 |
| GET | `/api/v1/llm/workflow` | 读 Workflow 默认配置 | `get_login_user` | 同上 |
| POST | `/api/v1/llm/workflow` | 写 Workflow 默认配置 | `get_model_admin_user` | 同上 |

### 6.2 请求/响应示例

**Knowledge GET（Child 5 已自主配置）**:

```json
GET /api/v1/llm/knowledge
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "data": {
      "llm_model_id": 51,
      "embedding_model_id": 52,
      "rerank_model_id": 53,
      "extract_title_model_id": 54
    },
    "inherited_from_root": false,
    "fallback_blocked": false
  }
}
```

**Knowledge GET（Child 5 未配置 + Root.share=1）**:

```json
{
  "data": {
    "data": { "llm_model_id": 11, "embedding_model_id": 12, ... },
    "inherited_from_root": true,
    "fallback_blocked": false
  }
}
```

**Knowledge POST**:

```json
POST /api/v1/llm/knowledge
{
  "llm_model_id": 51,
  "embedding_model_id": 52,
  "rerank_model_id": 53
}

// → 200, body.data 同 GET 形态（更新后），inherited_from_root: false
```

**Knowledge POST 跨 tenant 拒绝**（Child 5 Admin 构造 body 试图写 Root；admin-scope=null）:

```json
{
  "status_code": 403,
  "status_message": "llm_system_config_forbidden",
  "data": null,
  "code": 19803
}
```

### 6.3 错误码

| HTTP | Code | Error | 场景 | 关联 AC |
|------|------|-------|------|---------|
| 403 | 19803 | `LLMSystemConfigForbiddenError` | Child Admin 通过构造请求试图写 `target_tenant_id ∉ user.manageable_tenant_ids` 的行 | AC-10 |

> **Msg 修订**：`bisheng/common/errcode/llm_tenant.py:25` 当前 Msg 是 "System-level LLM configuration ... is restricted to the global super admin"；本 Feature 修订为 `"Cross-tenant write forbidden: target tenant_id is not in caller's manageable set"`，反映新语义。

---

## 7. Service 层逻辑

### 7.1 LLMService 方法签名变更

每个 `get_*_llm` / `update_*_llm` / `sync_get_*_llm` 加 `tenant_id: int | None = None` 参数：

```python
# src/backend/bisheng/llm/domain/services/llm.py

class LLMService:

    @classmethod
    async def get_knowledge_llm(
        cls, tenant_id: int | None = None,
    ) -> tuple[KnowledgeLLMConfig, bool, bool]:
        """Returns (config, inherited_from_root, fallback_blocked).

        If tenant_id is None, fallback to get_current_tenant_id() — picks up
        admin-scope override automatically. Celery workers MUST pass tenant_id
        explicitly.
        """
        target_tenant_id = tenant_id or get_current_tenant_id() or ROOT_TENANT_ID
        value, inherited, blocked = await TenantSystemModelConfigDao.aresolve(
            tenant_id=target_tenant_id, key=ConfigKeyEnum.KNOWLEDGE_LLM.value,
        )
        cfg = KnowledgeLLMConfig(**(json.loads(value) if value else {}))
        return cfg, inherited, blocked

    @classmethod
    async def update_knowledge_llm(
        cls, payload: KnowledgeLLMConfig, tenant_id: int | None = None,
    ) -> KnowledgeLLMConfig:
        target_tenant_id = tenant_id or get_current_tenant_id() or ROOT_TENANT_ID
        await TenantSystemModelConfigDao.aupsert(
            tenant_id=target_tenant_id,
            key=ConfigKeyEnum.KNOWLEDGE_LLM.value,
            value=json.dumps(payload.model_dump(), ensure_ascii=False),
        )
        return payload

    # 4 类同此签名（assistant / evaluation / workflow / workbench）
```

旧无参签名保留(同步版本同此规则)，调用点不强制立即迁移；ac-verification 阶段验证消费侧 7 处都按 §AD-05 规则传值。

### 7.2 fallback resolve 逻辑（DAO）

```python
# src/backend/bisheng/llm/domain/dao/tenant_system_model_config.py

class TenantSystemModelConfigDao:

    @classmethod
    async def aresolve(cls, tenant_id: int, key: str) -> tuple[Optional[str], bool, bool]:
        """Returns (value, inherited_from_root, fallback_blocked)."""
        own = await cls.aget(tenant_id, key)
        if own and own.value:
            return own.value, False, False

        if tenant_id == ROOT_TENANT_ID:
            return None, False, False

        root = await cls.aget(ROOT_TENANT_ID, key)
        if not root or not root.value:
            return None, False, False

        # Root has value; check share gate
        with bypass_tenant_filter():
            root_tenant = await TenantDao.aget(ROOT_TENANT_ID)
        if root_tenant and root_tenant.share_default_to_children:
            return root.value, True, False
        return None, False, True

    @classmethod
    async def aupsert(cls, tenant_id: int, key: str, value: str) -> 'TenantSystemModelConfig':
        # SQL: INSERT ... ON DUPLICATE KEY UPDATE value=:value
        ...

    @classmethod
    async def aget(cls, tenant_id: int, key: str) -> Optional['TenantSystemModelConfig']:
        ...
```

### 7.3 router 写侧权限校验

```python
# src/backend/bisheng/llm/api/router.py

@router.post('/knowledge', ...)
async def update_knowledge_llm(
    config_obj: KnowledgeLLMConfig = Body(...),
    user: UserPayload = Depends(UserPayload.get_model_admin_user),
):
    target_tenant_id = get_current_tenant_id() or ROOT_TENANT_ID

    # Defense-in-depth: even if Child Admin somehow obtained a token claiming
    # admin-scope, manageable_tenant_ids is the source of truth.
    if not user.is_global_super:
        manageable = await user.aget_manageable_tenant_ids()
        if target_tenant_id not in manageable:
            raise LLMSystemConfigForbiddenError.http_exception()

    payload = await LLMService.update_knowledge_llm(
        config_obj, tenant_id=target_tenant_id,
    )
    await audit_log(action='llm.system_config.update', metadata={
        'key': 'knowledge_llm', 'target_tenant_id': target_tenant_id,
        'before': <prev>, 'after': <new>,
    })
    return resp_200(data=payload)

# 5 个 POST 端点同模板
```

GET 端点不需要权限分级（`get_login_user` 即可），但内部调用要透出 fallback 元信息：

```python
@router.get('/knowledge', ...)
async def get_knowledge_llm():
    cfg, inherited, blocked = await LLMService.get_knowledge_llm()  # tenant_id 默认从 ContextVar 取
    return resp_200(data={
        'data': cfg.model_dump(),
        'inherited_from_root': inherited,
        'fallback_blocked': blocked,
    })
```

### 7.4 消费侧改造矩阵（AD-05 + INV-T18 落地）

| # | 调用点 | 配置类 | tenant_id 传入策略 | 改动 |
|---|--------|------|------|------|
| 1 | `knowledge/api/endpoints/knowledge.py:415` 个人 KB 初始化 | knowledge_llm | 默认入参（调用人 tenant，资源未落库） | 不显式传 |
| 2 | `api/services/knowledge_imp.py:207` 知识库导入抽取标题 | knowledge_llm | `Knowledge.tenant_id` 显式传 | 改 `decide_knowledge_llm(invoke_user_id)` 接收 `knowledge` 对象，提取其 `tenant_id`；Celery task 入队时把 `tenant_id` 写进 payload |
| 3 | `knowledge/domain/services/knowledge_utils.py:186` 摘要 | knowledge_llm | `Knowledge.tenant_id` 显式传 | `get_knowledge_abstract_llm(invoke_user_id, tenant_id)` 加参 |
| 4 | `workflow/nodes/agent/agent.py` Agent 节点 | assistant_llm | `Flow.tenant_id` 显式传（从 workflow context 取） | `sync_get_assistant_llm(tenant_id=...)` |
| 5 | `workflow/nodes/input/input.py:266` 工作流向量库 embedding | knowledge_llm | KB.tenant_id 优先，否则 Flow.tenant_id | `get_knowledge_default_embedding(user_id, tenant_id)` 加参；上游识别引用的 KB |
| 6 | `api/services/assistant.py:172` 助手创建默认模型 | assistant_llm | 默认入参（调用人 tenant，资源未落库） | 不显式传 |
| 7 | `api/services/evaluation.py:288` 评测执行 | evaluation_llm | `Evaluation.tenant_id` 显式传；Celery payload 带 | 同 #2 模板 |
| 8 | `llm/domain/services/llm.py:982` Workbench ASR | linsight_llm | 默认入参（调用人 tenant，实时功能） | 不显式传 |
| 9 | `llm/domain/services/llm.py:1002` Workbench TTS | linsight_llm | 默认入参（调用人 tenant，实时功能） | 不显式传 |

> **Celery worker 兜底**（覆盖 AC-23 / AC-24）：service 入口检测 `tenant_id is None and get_current_tenant_id() is None` → fallback `ROOT_TENANT_ID` + warn log（监控指标 `llm_system_config_tenant_missing_total`）。

---

## 8. 前端设计

### 8.1 弹窗组件 `SystemModelConfig.tsx`

文件：`src/frontend/platform/src/pages/ModelPage/manage/SystemModelConfig.tsx`

**改动点**：
1. 顶部 Header 读 `useAdminScope()` 取当前管理视图 tenant
2. 三种状态 banner：
   - `currentTenant.id === rootTenant.id && isGlobalSuper` → banner: "正在配置 Root（全局默认）"
   - `currentTenant.id !== rootTenant.id` → banner: "正在配置租户「{currentTenant.name}」。未配置项将从 Root 继承（若 Root 开启共享）。"
   - `currentTenant.id === rootTenant.id && !isGlobalSuper` → banner: "Root 共享 · 只读" + 全 Tab input disabled
3. 每个 Tab 顶部显示 `inherited_from_root: true` 时的 Badge "继承自 Root"，用户首次编辑任一字段时清掉（转为本租户独立配置）
4. `fallback_blocked: true` 时额外 Banner: "Root 已关闭共享。请联系超管开启共享或在此为本租户独立配置。"

### 8.2 5 个 Tab 组件 queryKey 加 tenantId

`src/frontend/platform/src/pages/ModelPage/manage/tabs/{Workbench,Knowledge,Assistant,Evaluation,Workflow}Model.tsx`：

- queryKey 从 `['llm', 'workbench']` 改为 `['llm', 'workbench', tenantId]`
- ScopeBar 切换租户时 `queryClient.invalidateQueries({ queryKey: ['llm'] })`

### 8.3 ScopeBar 联动

`src/frontend/platform/src/pages/ModelPage/manage/ScopeBar.tsx`：在 onChange 里追加 `queryClient.invalidateQueries({ queryKey: ['llm'] })`。

### 8.4 i18n 新增 key（三语 en / zh-Hans / ja）

`src/frontend/platform/src/i18n/lang/{en,zh-Hans,ja}/model.json`：

| key | zh-Hans 文案示例 |
|----|---------|
| `model.systemConfig.tenantBanner` | "正在配置租户「{tenantName}」。未配置项将从 Root 继承（若 Root 开启共享）。" |
| `model.systemConfig.rootBanner` | "正在配置 Root（全局默认）。所有未自主配置的子租户将继承此项。" |
| `model.systemConfig.rootReadOnlyBanner` | "Root 共享 · 只读。请切换到本租户视图以配置自有默认。" |
| `model.systemConfig.inheritedBadge` | "继承自 Root" |
| `model.systemConfig.fallbackBlockedBanner` | "Root 已关闭共享。请联系超管开启共享或在此为本租户独立配置。" |
| `model.systemConfig.forbiddenWriteRoot` | "权限不足：无法修改 Root 默认配置。" |

### 8.5 API 客户端类型扩展

`src/frontend/platform/src/controllers/API/{linsight,knowledge,assistant,evaluation,workflow}LLM.ts`：

返回类型从原 typed config 改为 envelope:

```ts
export interface SystemModelConfigEnvelope<T> {
  data: T;
  inherited_from_root: boolean;
  fallback_blocked: boolean;
}
```

调用点解构 `data` 字段以兼容老使用（最小破坏）。

---

## 8.5 自测清单（对应 AC）

> 开发者完成实现后必须自行运行；不依赖用户/产品人肉点击。

| Test | AC | 类型 | 备注 |
|------|----|------|----|
| `test_root_admin_no_scope_writes_root_config` | AC-01 | pytest 集成测试 | tenant_id=1 行写入 |
| `test_root_admin_no_scope_reads_root_config` | AC-02 | pytest 集成测试 | inherited_from_root=false |
| `test_child_inherits_root_when_share_on` | AC-03 | pytest 集成测试 | Child 5 未配置，Root.share=1，返 Root 行 |
| `test_child_writes_own_config` | AC-04 | pytest 集成测试 | tenant_id=5 行写入；下次 GET 不再 inherit |
| `test_child_reads_own_config_after_write` | AC-05 | pytest 集成测试 | inherited_from_root=false |
| `test_child_blocked_when_root_share_off` | AC-06 | pytest 集成测试 | fallback_blocked=true，data 空 |
| `test_child_returns_empty_when_root_unset` | AC-07 | pytest 集成测试 | data 空，blocked=false |
| `test_super_admin_with_scope_acts_as_child_write` | AC-08 | pytest 集成测试 | admin-scope=5 + POST → 写 tenant_id=5 |
| `test_super_admin_with_scope_acts_as_child_read` | AC-09 | pytest 集成测试 | admin-scope=5 + GET → 同 Child 5 视角 |
| `test_child_admin_cross_tenant_write_forbidden` | AC-10 | pytest 集成测试 | 构造 target_tenant_id=1 → 403 + 19803 |
| `test_child_admin_normal_write_succeeds` | AC-11 | pytest 集成测试 | 自然路径下 tenant_id=自己 leaf |
| `test_workbench_endpoint_isolation` | AC-12 | pytest 参数化 | linsight_llm key |
| `test_knowledge_endpoint_isolation` | AC-13 | pytest 参数化 | knowledge_llm key |
| `test_assistant_endpoint_isolation` | AC-14 | pytest 参数化 | assistant_llm key |
| `test_evaluation_endpoint_isolation` | AC-15 | pytest 参数化 | evaluation_llm key |
| `test_workflow_endpoint_isolation` | AC-16 | pytest 参数化 | workflow_llm key |
| `test_knowledge_import_uses_kb_tenant` | AC-17 | pytest 集成 | KB.tenant_id=5 → service 调用 tenant_id=5 |
| `test_super_admin_triggered_import_uses_kb_tenant` | AC-18 | pytest 集成 | Root admin 触发 Child 5 KB 导入 → 仍用 5 |
| `test_workflow_agent_uses_flow_tenant` | AC-19 | pytest 集成 | Flow.tenant_id=5 → assistant_llm 用 5 |
| `test_workflow_input_kb_owner_priority` | AC-20 | pytest 集成 | 引用 Root KB → embedding 用 Root |
| `test_assistant_create_uses_caller_tenant` | AC-21 | pytest 集成 | 资源未落库 → 调用人 tenant |
| `test_workbench_asr_uses_caller_tenant` | AC-22 | pytest 集成 | Workbench 实时调用 → 调用人 tenant |
| `test_celery_worker_tenant_id_explicit` | AC-23 | Celery 单测 | worker payload 带 tenant_id |
| `test_celery_worker_missing_tenant_falls_back_to_root` | AC-23 | Celery 单测 | 漏传时 fallback Root + warn log |
| `test_evaluation_celery_worker_explicit_tenant` | AC-24 | Celery 单测 | 评测 worker 同知识库 |
| `test_alembic_upgrade_backfills_root_rows` | AC-25 | alembic 测试 | F034 upgrade 后 5 行 tenant_id=1 |
| `test_existing_install_with_share_on_inherit` | AC-26 | pytest 集成 | 升级 + Root.share=1 → Child 立即 inherit |
| `test_existing_install_with_share_off_returns_empty` | AC-27 | pytest 集成 | 升级 + Root.share=0 → Child 业务侧抛 NoSystemModelConfigError |
| `test_alembic_downgrade_then_upgrade_idempotent` | AC-28 | alembic 测试 | 重复 upgrade 不重复插入（INSERT IGNORE） |
| `test_audit_log_on_system_config_update` | AC-29 | pytest 集成 | metadata 含 before/after/target_tenant_id |

---

## 9. 文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `src/backend/bisheng/llm/domain/models/tenant_system_model_config.py` | ORM + DAO（同文件，沿用 `llm_server.py` 既有惯例：`{Entity}Base` + `{Entity}` table + `{Entity}Dao` 一文件搞定） |
| `src/backend/bisheng/llm/domain/schemas.py` | 在原有单文件 schemas.py 中追加 `SystemModelConfigEnvelope`（spec 起初提议 `schemas/system_model.py` 子目录，但 schemas.py 是单文件惯例，遵循之） |
| `src/backend/bisheng/core/database/alembic/versions/v2_5_1_f034_tenant_system_model_config.py` | alembic 迁移：建表 + backfill `config` 5 个 key 到 tenant_id=1（INSERT IGNORE 幂等）。spec 起初规划 F031，实施时该编号已被 `startup_hotfix_fields` 占用，统一改用 F034 |
| `src/backend/bisheng/core/database/tenant_filter.py` | 在 `_TENANT_AWARE_MODEL_MODULES` 列表追加新模块路径，让全局事件监听器自动启用 tenant filter |

### 修改

| 文件 | 变更内容 |
|------|---------|
| `src/backend/bisheng/llm/domain/services/llm.py` | 5 类 get/update + sync 版本加 `tenant_id: int | None = None` 参数；DAO 切到 `TenantSystemModelConfigDao`；返回 envelope 元信息 |
| `src/backend/bisheng/llm/api/router.py` | 5 个 POST 入口加 `target_tenant_id ∈ user.manageable_tenant_ids` 校验；5 个 GET 透出 envelope；audit_log 写入 |
| `src/backend/bisheng/common/errcode/llm_tenant.py:25` | 修订 `LLMSystemConfigForbiddenError` Msg："Cross-tenant write forbidden..." |
| `src/backend/bisheng/common/middleware/admin_scope.py` | 验证 5 个 endpoint 已被 `MANAGEMENT_API_PREFIXES` 覆盖（`/api/v1/llm` 已在列表，无需改动） |
| `src/backend/bisheng/knowledge/api/endpoints/knowledge.py:415` | 个人 KB 初始化无需改（默认入参） |
| `src/backend/bisheng/api/services/knowledge_imp.py:207` | `decide_knowledge_llm` 接收 `knowledge` 对象，传 `tenant_id`；Celery task 入队带 `tenant_id` payload |
| `src/backend/bisheng/knowledge/domain/services/knowledge_utils.py:186` | 摘要函数加 `tenant_id` 参数 |
| `src/backend/bisheng/workflow/nodes/agent/agent.py` | `sync_get_assistant_llm(tenant_id=flow.tenant_id)` |
| `src/backend/bisheng/workflow/nodes/input/input.py:266` | `get_knowledge_default_embedding(user_id, tenant_id)` 加参，KB owner 优先 |
| `src/backend/bisheng/api/services/assistant.py:172` | 默认入参（调用人 tenant），无需显式 |
| `src/backend/bisheng/api/services/evaluation.py:288` | `get_evaluation_llm_object(user_id, tenant_id=evaluation.tenant_id)` 加参；Celery payload |
| `src/frontend/platform/src/pages/ModelPage/manage/SystemModelConfig.tsx` | 顶部 banner（3 状态）；5 Tab 接 `currentTenant` / `isReadOnly` |
| `src/frontend/platform/src/pages/ModelPage/manage/tabs/{Workbench,Knowledge,Assistant,Evaluation,Workflow}Model.tsx` | queryKey 加 tenantId；inherited Badge；首次编辑清 inherited |
| `src/frontend/platform/src/pages/ModelPage/manage/ScopeBar.tsx` | onChange invalidateQueries `['llm']` |
| `src/frontend/platform/src/controllers/API/*LLM.ts` | 返回类型扩展为 `SystemModelConfigEnvelope<T>` |
| `src/frontend/platform/src/i18n/lang/{en,zh-Hans,ja}/model.json` | 6 个新 i18n key |

---

## 10. 配置项

无新增配置项。沿用：
- `multi_tenant.admin_scope_ttl_seconds`（F019）
- `Tenant.share_default_to_children`（F011）

---

## 11. 不做的事（Out of Scope）

- **5 类共享开关独立化**：`tenant_system_model_config.is_shared_to_children` 字段预留 schema，本期不读不写；未来 v2.6+ 实施
- **配置版本化历史**：DAO 不写 `*_history` 表；用现有 `audit_log` 承载（action=`llm.system_config.update`）
- **配置导入导出**（"Root 模板复制到 Child"）：表结构已可直接 SELECT/INSERT，前端工具留待后续
- **3 层及以上 Tenant fallback**：MVP 锁 2 层（INV-T1），不递归
- **Workbench 子配置部分共享**：Workbench JSON 是粗粒度整体，行级粒度 fallback；不支持"只继承 ASR 不继承 task_model"
- **`/api/v1/llm/{type}` 增量字段更新（PATCH 语义）**：当前 POST 是全量替换，本期保留全量替换行为
- **Workstation/Linsight 其他 Config key 的租户化**（如 `workstation_subscription` / `workstation_knowledge_space`）：本期仅覆盖 5 类 LLM 默认配置；其他 key 留待后续 feature 评估

---

## 12. 依赖清单

| 依赖 | 说明 |
|------|------|
| F011 | `Tenant.share_default_to_children` 字段；fallback 策略依赖此开关 |
| F012 | `get_current_tenant_id()` ContextVar 读取（含 admin-scope 覆盖）；`bypass_tenant_filter` 用于跨租户读 Root tenant |
| F019 | admin-scope 中间件（写侧 tenant 来源）；`/api/v1/llm` 已在 `MANAGEMENT_API_PREFIXES` 列表，本 Feature 无需追加 |
| F020 | LLM Server / Model 隔离基础；本 Feature 是 F020 的延伸，**修订 F020 AD-07 + AC-11** |
| INV-T17 | （新增）系统模型设置写入必须命中 admin-scope 覆盖后的 tenant；Child Admin 写入 `target_tenant_id ∉ user.manageable_tenant_ids` 时返 403 + 19803 |
| INV-T18 | （新增）系统模型设置消费侧 tenant 解析规则：资源场景按 owner（Knowledge/Flow/Evaluation 的 tenant_id），创建/实时场景按调用人 tenant；Celery worker 必须 task payload 显式带 tenant_id |

> **新增 INV 提案**：INV-T17 / INV-T18 需在 release-contract.md 表 2 追加（本 Feature 实施第一步，sdd-review 通过后由 spec.md 一并打补丁）。

---

## 13. 相关文档

- 主 PRD `docs/archive/2.5 权限管理体系改造 PRD/2.5 多租户需求文档.md`：
  - §7.1（Child 独立模型）— 需补一段"系统模型设置同样按租户隔离"
  - §10.4（废弃 API 说明）— 与本 Feature 无直接关系，仅参考
- 升级迁移方案 `docs/archive/2.5 权限管理体系改造 PRD/2.5 版本升级迁移方案.md`：
  - §3.7 LLM 模型升级行为 — 需追加 F034 alembic 迁移说明（spec 起初规划为 F031，但 F031 已被 `startup_hotfix_fields` 占用，本期实施时改用 F034）
- 运维手册 `docs/archive/2.5 权限管理体系改造 PRD/2.5 多租户切换运维手册.md`：
  - §6 故障排查矩阵 — 需追加 19803 实际触发场景
  - §8.3 v2.5 多租户相关 alembic 迁移列表（21 个）→ 22 个（追加 F034 `tenant_system_model_config`）
- F020 spec.md：
  - §2.2 AC-11 行为 — 本 Feature 修订
  - §4 AD-07 — 本 Feature 修订
  - §6 错误码表 19803 Msg — 本 Feature 修订
- 前序 spec：
  - F019 admin-tenant-scope: §5.3 中间件白名单（`/api/v1/llm` 已覆盖）
  - F011 tenant-tree-model: `Tenant.share_default_to_children` 默认值
- release-contract `features/v2.5.1/release-contract.md`：
  - 表 2 INV 列表 — 追加 INV-T17 / INV-T18
  - 表 3 Feature 依赖图 — 追加 F022 行
  - 已分配模块编码表 — 沿用 198，无新增
  - 变更历史 — 追加 2026-04-26 F022 修订 F020 AD-07 / AC-11 条目
