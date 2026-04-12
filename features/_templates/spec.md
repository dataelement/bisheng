# Feature: <名称>

> **前置步骤**：本文档编写前必须已完成 Spec Discovery（架构师提问），
> 确保 PRD 中的不确定性已与用户对齐。

**关联 PRD**: [<PRD 文件路径> §章节名]
**优先级**: P0 / P1 / P2
**所属版本**: v2.5.0

---

## 1. 概述与用户故事

作为 **<角色>**，
我希望 **<目标>**，
以便 **<价值>**。

---

## 2. 验收标准

> AC-ID 在本特性内唯一，格式 `AC-NN`。
> tasks.md 中的测试任务必须通过 `覆盖 AC: AC-NN` 追溯到此表。

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | <角色> | <执行什么操作> | <系统返回/显示什么> |
| AC-02 | <角色> | <边界/错误场景操作> | <错误码/HTTP 状态码> |

---

## 3. 边界情况

- 当 <异常场景> 时，系统应 <预期行为>
- **不支持**：<明确排除的功能>（延后到 vX.X.X）

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | <决策主题> | A: ... / B: ... | 选 A | <理由> |

---

## 5. 数据库 & Domain 模型

### 数据库表定义

> 使用 SQLModel ORM 定义。所有新表必须继承 `SQLModelSerializable`，
> 包含 `tenant_id`（多租户）、`create_time`/`update_time` 字段。

```python
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, String, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class NewEntity(SQLModelSerializable, table=True):
    __tablename__ = "new_entity"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: Optional[str] = Field(default=None, index=True)
    name: str = Field(sa_column=Column(String(255), nullable=False))
    # ... 业务字段

    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: Optional[datetime] = Field(
        sa_column=Column(
            DateTime, nullable=False,
            server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        )
    )
```

### Domain 模型 / DTO

> Pydantic Schema 用于请求/响应序列化。

```python
from pydantic import BaseModel


class NewEntityCreate(BaseModel):
    name: str
    # ...


class NewEntityRead(BaseModel):
    id: int
    name: str
    create_time: datetime
    # ...
```

---

## 6. API 契约

### 端点列表

> 认证：`UserPayload = Depends(UserPayload.get_login_user)`
> 响应包装：`UnifiedResponseModel[T]`

| Method | Path | 描述 | 认证 |
|--------|------|------|------|
| GET | `/api/v1/<resource>` | 列表查询（分页） | 是 |
| POST | `/api/v1/<resource>` | 创建 | 是 |
| GET | `/api/v1/<resource>/{id}` | 详情 | 是 |
| PUT | `/api/v1/<resource>/{id}` | 更新 | 是 |
| DELETE | `/api/v1/<resource>/{id}` | 删除 | 是 |

### 请求/响应示例

**创建请求**:
```json
POST /api/v1/<resource>
{
  "name": "示例"
}
```

**成功响应**:
```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "id": 1,
    "name": "示例",
    "create_time": "2025-01-01T00:00:00"
  }
}
```

**分页响应**（使用 `PageData[T]`）:
```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "data": [...],
    "total": 100
  }
}
```

### 错误码表

> 错误码遵循 5 位 MMMEE 编码。MMM=模块编码，EE=模块内错误类型。
> 新模块编码需在 release-contract.md「已分配模块编码」中注册。

| HTTP Status | MMMEE Code | Error Class | 场景 | 关联 AC |
|-------------|------------|-------------|------|---------|
| 200 (body) | MMMEE | XxxError | 参数不合法 | AC-0X |
| 200 (body) | MMMEE | XxxError | 唯一性冲突 | AC-0X |
| 200 (body) | MMMEE | XxxError | 权限不足 | AC-0X |

---

## 7. Service 层逻辑

> 描述核心业务逻辑的流程和职责划分，不写具体实现代码。
> Service 文件位置：`{module}/domain/services/{service_name}.py`

### 核心方法

| 方法 | 输入 | 输出 | 职责 |
|------|------|------|------|
| `create_xxx` | CreateDTO + UserPayload | Entity | 创建 + OpenFGA 授权 |

### 权限检查

> 资源操作必须通过 `PermissionService.check()` 检查权限。
> 资源创建必须通过 `PermissionService.authorize()` 写入 OpenFGA owner 元组。
> 禁止直接查询 `role_access` 或 `group_resource`（WEB_MENU 类型除外）。

### DAO 调用约定

> DAO 方法为 `@classmethod`：
> - 同步：`XxxDao.get_xxx()` / `create_xxx()` / `update_xxx()` / `delete_xxx()`
> - 异步：`XxxDao.aget_xxx()` / `acreate_xxx()` / `aupdate_xxx()` / `adelete_xxx()`

---

## 8. 前端设计

### 8.1 Platform 前端（如适用）

> 路径：`src/frontend/platform/src/`

**页面路由**: `/xxx` → `pages/XxxPage/`

**组件树**:
```
XxxPage/
├── index.tsx          # 页面入口
├── components/        # 页面级组件
└── ...
```

**状态管理**: Zustand store（`src/store/xxxStore.tsx`）

**API 调用**: `src/controllers/API/xxx.ts` → 封装函数 → 组件调用

**i18n**: 键前缀 `<module>.xxx`

### 8.2 Client 前端（如适用）

> 路径：`src/frontend/client/src/`
> 路由基础路径：`/workspace`

**页面路由**: `/workspace/xxx`

**状态管理**: Zustand atoms（`src/store/xxx.ts`）

**API 调用**: `src/api/xxx.ts`

---

## 9. 文件清单

列出本特性将新建或修改的所有文件。

### 新建

| 文件 | 说明 |
|------|------|
| `src/backend/bisheng/{module}/domain/models/{entity}.py` | ORM + DAO |
| `src/backend/bisheng/{module}/domain/services/{service}.py` | 业务逻辑 |
| `src/backend/bisheng/{module}/api/endpoints/{endpoint}.py` | API 端点 |
| `src/backend/bisheng/common/errcode/{module}.py` | 错误码 |

### 修改

| 文件 | 变更内容 |
|------|---------|
| `src/backend/bisheng/{module}/api/router.py` | 注册新路由 |
| `src/backend/bisheng/api/router.py` | 注册模块路由（如新模块） |

---

## 10. 非功能要求

- **性能**: <响应时间、吞吐量要求>
- **安全**: 权限控制（PermissionService 五级检查链路）、数据隔离（tenant_id）
- **兼容性**: <与现有功能的兼容要求>

---

## 相关文档

- 版本契约: [features/v2.5.0/release-contract.md](../release-contract.md)（写 spec 前必须先阅读）
- 架构文档: `docs/architecture/`
- PRD: `docs/PRD/`
