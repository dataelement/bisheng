# 需求说明 Requirements: 系统字典路由启动修复

## 元信息 Metadata
- Feature ID: `049-dictionary-router-startup`
- Status: `implemented`
- Mode: `bug-fix`
- Created: `2026-07-28`
- Updated: `2026-07-28`
- Source request: 修复后端启动时 dictionary 路由触发的 `Prefix and path cannot be both empty`

## 问题与复现 Problem and Reproduction

`bisheng.dictionary.api.router` 使用带 `/dictionaries` 前缀的父路由包含一个空前缀子路由，
而子路由的创建和列表操作使用空路径。FastAPI 在 `include_router()` 阶段只组合本次传入的前缀
与子路由路径，两者均为空时抛出 `FastAPIError`，导致应用导入和 Uvicorn 启动失败。

稳定复现：

```bash
cd src/backend
uv run python -c 'from bisheng.dictionary.api.router import router'
```

## 范围 Scope

### 包含 Includes
- 修复 dictionary 路由的 FastAPI 注册方式。
- 保持集合接口精确路径为 `/api/v1/dictionaries`，不增加尾斜杠。
- 增加最小路由契约回归测试。

### 不包含 Excludes
- 不修改字典业务逻辑、请求响应结构、权限或数据库。
- 不修改其他模块路由。

## 需求列表 Requirements

### REQ-001: 字典路由可注册且路径兼容
系统 SHALL 在应用启动时成功注册 dictionary 路由，并保持现有集合接口路径不变。

#### 验收标准 Acceptance Criteria
- `AC-REQ-001-01`: WHEN 导入并注册 dictionary 路由 THEN 系统 SHALL 不抛出 `FastAPIError`.
- `AC-REQ-001-02`: WHEN 检查注册后的路由 THEN 系统 SHALL 同时存在 `GET /api/v1/dictionaries` 和 `POST /api/v1/dictionaries`.

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-001-01, AC-REQ-001-02 | V-AC-REQ-001-01 | automated test | `test/dictionary/test_dictionary_router.py` |

## 风险 Risks
- 将空路径改为 `/` 会改变尾斜杠契约，因此本次只调整前缀挂载位置。
