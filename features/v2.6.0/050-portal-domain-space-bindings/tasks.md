# Tasks: 门户业务域知识空间多绑定

**关联规格**: [spec.md](./spec.md)
**版本**: v2.6.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已确认 | 用户已确认字段、同步策略和 UI 形式 |
| tasks.md | ✅ 已拆解 | 按本次最小闭环拆解 |
| 实现 | ✅ 已完成 | 8 / 8 完成，Portal 后端测试受本地环境限制未执行 |

---

## Tasks

- [x] **T001**: BiSheng 数据模型与迁移
  **文件**: `src/backend/bisheng/knowledge/domain/models/knowledge.py`, `src/backend/bisheng/core/database/alembic/versions/*.py`
  **逻辑**: 新增 `business_domain_codes` JsonType 字段，迁移新增可空列并回填知识空间空列表。
  **覆盖 AC**: AC-02, AC-03, AC-04

- [x] **T002**: BiSheng 同步请求/响应 DTO
  **文件**: `src/backend/bisheng/knowledge/domain/schemas/knowledge_space_schema.py`
  **逻辑**: 定义批量同步请求项、请求体和响应体；空间响应透出 `business_domain_codes`。
  **覆盖 AC**: AC-02, AC-03, AC-04

- [x] **T003**: BiSheng 同步服务与 API
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`, `src/backend/bisheng/knowledge/api/endpoints/shougang_portal.py`
  **逻辑**: 批量校验并更新空间业务域编码，接口返回更新数量。
  **覆盖 AC**: AC-02, AC-03, AC-04

- [x] **T004**: BiSheng 后端测试
  **文件**: `src/backend/test/knowledge/test_shougang_portal_business_domain_codes.py`
  **逻辑**: 覆盖多编码同步、清空、接口响应、空间列表默认空列表。
  **覆盖 AC**: AC-02, AC-03, AC-04

- [x] **T005**: 门户后端字段透传
  **文件**: `backend/app/schemas/portal_config.py`, `backend/app/services/portal_config_service.py`, `backend/app/api/routes/admin_config.py`
  **逻辑**: `SpaceOption` 增加 `business_domain_codes`，`/space-options` 透传。
  **覆盖 AC**: AC-04

- [x] **T006**: 门户后端强一致同步
  **文件**: `backend/app/api/routes/admin_config.py`, `backend/app/services/portal_config_service.py`
  **逻辑**: 保存业务域配置前全量计算空间绑定编码，先同步 BiSheng 成功后再保存；失败不落库。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-05

- [x] **T007**: 门户前端多选 UI
  **文件**: `frontend/src/api/adminConfig.ts`, `frontend/src/utils/adminDomains.ts`, `frontend/src/pages/AdminPage.tsx`
  **逻辑**: 草稿改为 `spaceIds`，编辑弹窗改为分组复选列表 + 已选标签，保存输出多个 `space_ids`。
  **覆盖 AC**: AC-01, AC-04

- [x] **T008**: 门户测试与回归验证
  **文件**: `backend/tests/test_admin_config_api.py`, `frontend/tests/adminDomains.test.ts`, `frontend/tests/adminDomainSpaceOptions.test.ts`
  **逻辑**: 覆盖多选校验、强一致失败不落库、空间字段透传。
  **覆盖 AC**: AC-01, AC-04, AC-05

---

## 实际偏差记录

- Portal 后端目标用例已补充，但当前 Portal 仓库本地 Python/uv 环境缺少 `pytest`，未能执行 `backend/tests/test_admin_config_api.py`。
- Portal 前端整体 `npm test` 在执行目标用例前被既有 `tests/adminQaTemplates.test.ts` 类型错误阻断，本次改用临时编译目录执行相关前端单测。
