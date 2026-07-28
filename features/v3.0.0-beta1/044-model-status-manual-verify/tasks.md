# Tasks: 模型状态手动验证

**关联规格**: [spec.md](./spec.md) · **设计真相**: [design.md](./design.md)
**版本**: v3.0.0-beta1

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 用户已确认 |
| design.md | ✅ 已评审 | 用户已确认；接手时第一入口 |
| tasks.md | ✅ 已拆解 | — |
| 实现 | 🟡 代码完成待验证 | 7 / 7 完成（需在有模型配置的环境人工验证）|

---

## 开发模式

- 后端 Test-First：探活写状态的分支可用 mock 覆盖（不打真实模型）。
- 迁移文件命名沿用现有惯例 `v3_0_0_beta1_f044_*.py`；**必须走 `dialect_helpers`**（C2 双 DB，DM8 不可选）。
- 前端手动验证。

---

## Tasks

### Wave 1 — 数据层

- [x] **T001**: 模型表新增「状态更新时间」字段 + 迁移
  **文件**: `src/backend/bisheng/llm/domain/models/llm_server.py`（`LLMModelBase` 加字段）
  `src/backend/bisheng/core/database/alembic/versions/v3_0_0_beta1_f044_llm_model_status_update_time.py`（新建）
  **逻辑**: 新增可空 DateTime 列 `status_update_time`（历史行为 NULL → 前端显示「—」）。**不得**用 `ON UPDATE CURRENT_TIMESTAMP`，由业务代码显式写入（design §3 决策 4）
  **约束**: C2 双 DB —— 用 `dialect_helpers`，禁 MySQL 专有语法；迁移需可在 MySQL 与 DM8 双跑
  **回滚方案**: `downgrade()` 直接 drop 该列即可——新增可空列、无数据回填、无其他表引用，回滚无损
  **覆盖 AC**: AC-05
  **依赖**: 无

- [x] **T002**: DAO 写状态时一并写时间
  **文件**: `src/backend/bisheng/llm/domain/models/llm_server.py`（`LLMDao.update_model_status` / `aupdate_model_status`）
  **逻辑**: 两个方法的 `values(...)` 增加 `status_update_time=当前时间`；保持既有签名与调用方兼容
  **覆盖 AC**: AC-03, AC-04, AC-05
  **依赖**: T001

### Wave 2 — 探活行为修正（Test-First）

- [x] **T003**: 探活状态写入单元测试
  **文件**: `src/backend/test/llm/test_model_status_verify.py`（新建）
  **逻辑**: mock 各类型模型客户端。用例：调用成功 → 写状态=正常且 remark 清空且时间刷新；调用抛异常 → 写状态=异常 + 原因 + 时间刷新；超时 → 按异常处理且原因含超时语义
  **覆盖 AC**: AC-03, AC-04
  **基础设施**: `test/llm/` 若不存在则新建（含 `__init__.py`），复用根 `conftest.py`
  **依赖**: T002

- [x] **T004**: `test_model_status` 补成功回写 + 超时
  **文件**: `src/backend/bisheng/llm/domain/services/llm.py`（`LLMService.test_model_status`）
  **逻辑**: ①成功分支补 `update_model_status(id, 0, '')`——现状只在失败写库，不改 AC-03 不成立（design §3 决策 3、§5 坑 1）；②整段探活加 30 秒超时上限，超时按异常处理
  **测试**: T003 全部通过
  **覆盖 AC**: AC-03, AC-04
  **⚠️ 回归点**: 该函数同时被「新增/更新服务提供方」调用，需确认保存模型配置的既有行为不被破坏
  **依赖**: T003

### Wave 3 — API 层

- [x] **T005**: 「验证单个模型」端点
  **文件**: `src/backend/bisheng/llm/api/router.py`（与 `/online` 同级新增）
  **逻辑**: 入参模型 ID；权限沿用同文件既有 `get_tenant_admin_user` 注入；取模型 → 调 `LLMService.test_model_status` → 回读并返回 `{status, remark, status_update_time}`。**不新增错误码**：验证失败是业务结果（状态=异常），接口本身返回成功
  **覆盖 AC**: AC-02, AC-03, AC-04, AC-06
  **依赖**: T004

- [x] **T006**: 模型列表响应带出状态更新时间
  **文件**: `src/backend/bisheng/llm/domain/services/llm.py` / 相关 schema（按现有模型列表返回结构补字段）
  **逻辑**: 列表接口响应中带 `status_update_time`（新增字段，向后兼容，其他消费方忽略即可）
  **覆盖 AC**: AC-05
  **依赖**: T001

### Wave 4 — 前端

- [x] **T007**: 模型管理页：更新状态按钮 + 时间列 + i18n
  **文件**: `src/frontend/platform/src/pages/ModelPage/manage/index.tsx`
  `src/frontend/platform/src/controllers/API/finetune.ts`（新增请求方法，走既有封装）
  platform locale 三语文件
  **逻辑**: ①行 hover 时状态右侧显示「更新状态」按钮（移出隐藏）；②点击 → loading 且禁用该行按钮 → 调 T005 → 用返回值就地更新该行状态/原因/时间 → toast「状态已更新」；③状态列右侧新增「状态更新时间」列，空值显示「—」；④按钮**不看 `online` 字段**（下线模型同样可验证，AC-06）
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06
  **手动验证**:
  - 找一个 API Key 配错的模型 → 点更新状态 → 变红、可看原因、时间刷新
  - 改对配置后再点 → **变绿**（这条同时验证 T004 的成功回写）
  - 已下线的模型 → 按钮可用且能出结果
  - 切 en / ja 检查新增文案
  **依赖**: T005, T006

---

## 实际偏差记录

> 只留一行指针，论证在 design.md。

- T006 无需改动：模型信息 schema 继承自表基类，新字段自动带出
- T004 行为修正的连带影响：`test_zhipu_provider.py::test_model_status_checks_llm_with_non_streaming` 原先靠"成功不写库"绕开 DB，改为成功也写库后需补 DAO mock（已修）
