# Tasks: <特性名称>

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | 🔲 草稿 | 用户确认后改为 ✅ 已评审 |
| tasks.md | 🔲 草稿 | 拆解完成后改为 ✅ 已拆解 |
| 实现 | 🔲 未开始 | 0 / N 完成 |

---

## 开发模式

**后端 Test-First（务实版）**：
- 理想流程：先写测试（红），再写实现（绿）
- 务实适配：当前项目测试基础薄弱（无 conftest/fixtures），第一个 Feature 的首个
  测试任务需包含 pytest 基础设施搭建（conftest.py、db fixture、mock helpers）
- 如果某任务的测试编写成本极高（如需要完整的 Milvus/ES mock），可标注
  `**测试降级**: 手动验证 + TODO 标记`，但必须在「实际偏差记录」中说明

**前端 Test-Alongside（暂缓版）**：
- Platform 和 Client 前端当前无自动化测试框架
- 前端任务暂用「手动验证」替代自动化测试，每个任务附验证步骤描述
- 一旦 Feature `000-test-infrastructure` 完成，后续 Feature 恢复自动化测试要求

**自包含任务**：每个任务内联文件、逻辑、测试上下文，实现阶段不需要回读 spec.md。

---

## Tasks

### 基础设施（无测试配对）

- [ ] **T001**: 数据库 ORM 模型 + DAO
  **文件**: `src/backend/bisheng/{module}/domain/models/{entity}.py`
  **逻辑**: 定义 SQLModel 表（继承 SQLModelSerializable，含 tenant_id/create_time/update_time），
  编写 DAO classmethod（get_xxx/aget_xxx/create_xxx/update_xxx/delete_xxx）
  **依赖**: 无

- [ ] **T002**: 错误码定义
  **文件**: `src/backend/bisheng/common/errcode/{module}.py`
  **逻辑**: 定义 MMMEE 错误码类，继承 BaseErrorCode，在 release-contract.md 注册模块编码
  **依赖**: 无

### 后端 Domain Service（Test-First 配对）

- [ ] **T003**: {Module}Service 单元测试
  **文件**: `src/backend/test/test_{module}_service.py`
  **逻辑**: 测试核心方法，mock DAO 层
  **测试**: `test_create_success` → AC-01, `test_permission_denied` → AC-02
  **覆盖 AC**: AC-01, AC-02
  **基础设施**: 如 conftest.py 不存在，本任务一并创建基础 fixture
  **依赖**: T001

- [ ] **T004**: {Module}Service 实现
  **文件**: `src/backend/bisheng/{module}/domain/services/{service}.py`
  **逻辑**: 业务逻辑，调用 DAO + PermissionService
  **测试**: T003 全部通过
  **覆盖 AC**: AC-01, AC-02
  **依赖**: T001, T003

### 后端 API 层（Test-First 配对）

- [ ] **T005**: API 端点集成测试
  **文件**: `src/backend/test/test_{module}_api.py`
  **逻辑**: TestClient 测试 HTTP 端点，覆盖 happy path + 主要 error path
  **覆盖 AC**: AC-01, AC-02
  **依赖**: T004

- [ ] **T006**: API 端点 + Router 注册
  **文件**: `src/backend/bisheng/{module}/api/endpoints/{endpoint}.py`,
           `src/backend/bisheng/{module}/api/router.py`
  **逻辑**: FastAPI endpoint 定义，UserPayload 认证注入，委托 Service 处理，
  UnifiedResponseModel 响应包装。在 api/router.py 注册（如新模块）
  **测试**: T005 全部通过
  **覆盖 AC**: AC-01, AC-02
  **依赖**: T004, T005

### 前端 Platform（手动验证）

- [ ] **T007**: Platform 页面实现
  **文件**: `src/frontend/platform/src/pages/{Page}/index.tsx`,
           `src/frontend/platform/src/controllers/API/{module}.ts`
  **逻辑**: 组件结构、API 集成、状态管理（Zustand）、i18n
  **覆盖 AC**: AC-01, AC-02
  **手动验证**:
  - 打开 http://192.168.106.114:3001/xxx
  - 执行 <操作>，验证 <预期结果>
  - 检查错误场景：<描述>
  **依赖**: T006

### 前端 Client（手动验证，如适用）

- [ ] **T008**: Client 页面实现
  **文件**: `src/frontend/client/src/pages/{page}.tsx`,
           `src/frontend/client/src/api/{module}.ts`
  **逻辑**: 组件结构、API 集成、状态管理（Zustand）
  **覆盖 AC**: AC-03
  **手动验证**:
  - 打开 http://192.168.106.114:4001/workspace/xxx
  - 执行 <操作>，验证 <预期结果>
  **依赖**: T006

### Worker 异步任务（如适用）

- [ ] **T009**: Celery 任务定义
  **文件**: `src/backend/bisheng/worker/{module}/tasks.py`
  **逻辑**: 异步任务实现，调用 Domain Service
  **约束**: 任务参数中包含 tenant_id，Worker 执行前恢复 current_tenant_id ContextVar
  **覆盖 AC**: AC-04
  **依赖**: T004

---

## 实际偏差记录

> 完成后，在此记录实现与 spec.md 的偏差，供后续参考。

- **偏差 1**: <描述实际做了什么，以及为何偏离原计划>
