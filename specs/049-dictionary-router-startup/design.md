# 设计说明 Design: 系统字典路由启动修复

## 元信息 Metadata
- Feature ID: `049-dictionary-router-startup`
- Status: `implemented`
- Related requirements: `specs/049-dictionary-router-startup/requirements.md`
- Created: `2026-07-28`
- Updated: `2026-07-28`

## 根因 Root Cause

`dictionary/api/router.py` 当前通过 `APIRouter(prefix="/dictionaries")` 声明父路由，但调用
`router.include_router(dictionary_endpoint)` 时没有传入前缀。子路由自身前缀为空，集合端点路径
也为空，FastAPI 在包含阶段得到空的 `prefix + path` 并拒绝注册。

## 修复策略

父聚合路由改为无前缀，并在 `include_router(dictionary_endpoint, prefix="/dictionaries")`
时传入前缀。这样 FastAPI 在包含阶段能得到非空路径，最终被全局 `/api/v1` 路由包含后仍形成
精确路径 `/api/v1/dictionaries`。

## 文件结构计划 File Structure Plan
| Path | Action | Responsibility | Linked Requirement |
|---|---|---|---|
| `src/backend/bisheng/dictionary/api/router.py` | modify | 调整 dictionary 前缀挂载位置 | REQ-001 |
| `src/backend/test/dictionary/test_dictionary_router.py` | create | 验证路由可注册且集合路径兼容 | REQ-001 |

## 测试策略 Testing Strategy

使用一个 API 路由契约测试作为 V1 定向证据：将 dictionary 路由包含到 `/api/v1` 测试应用，
断言导入和注册成功，并检查 GET/POST 集合路径。该用例同时覆盖启动异常和尾斜杠兼容风险。

## 风险与回滚

- 无依赖、数据或 Schema 变化。
- 生产路由路径保持不变。
- 回滚仅需恢复路由文件及删除对应测试和规格。
