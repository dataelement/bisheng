# Tasks: 文档知识库外层列表展示文件解析异常

**关联规格**: [spec.md](./spec.md)
**版本**: v3.0.0-beta1

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | 🔲 草稿 | Small feature，与实现同批落地 |
| design.md | 🔲 草稿 | 接手时的第一入口 |
| tasks.md | ✅ 已拆解 | 4 Wave / 7 项 |
| 实现 | ✅ 已完成 | 7 / 7 完成 |

---

## 开发模式

按 Wave 组织。后端 DAO / Service 先写测试再改实现。前端用组件测试覆盖标签与筛选。

---

## Tasks

### Wave 1 — 常量与 DAO

- [x] **T001**: 异常状态常量 + 批量 EXISTS + 列表 EXISTS 筛选 + 复合索引声明
  **文件**: `src/backend/bisheng/knowledge/domain/models/knowledge_file.py`,
           `src/backend/bisheng/knowledge/domain/models/knowledge.py`
  **逻辑**: `ABNORMAL_FILE_STATUSES={3,6,7}`；`async_exists_abnormal_files_batch`；`generate_all_knowledge_filter(has_abnormal=True)` 追加 EXISTS；`KnowledgeFile` 声明 `ix_knowledgefile_kb_status_type`
  **覆盖 AC**: AC-03, AC-04, AC-06
  **依赖**: 无

- [x] **T002**: Alembic 复合索引
  **文件**: `src/backend/bisheng/core/database/alembic/versions/v3_0_0_beta1_f064_kb_file_abnormal_index.py`
  **逻辑**: `down_revision` 接当前单头；DDL-only；`index_exists` 幂等；MySQL/DM8 可建 `(knowledge_id, status, file_type)`
  **依赖**: T001

### Wave 2 — Service / API

- [x] **T003**: 列表组装与筛选参数测试
  **文件**: `src/backend/test/knowledge/test_kb_list_file_abnormal.py`
  **逻辑**: 批量 EXISTS 空入参；文档库打标 / QA 不查文件表；仅文件夹或 PROCESSING 不进异常集；`has_abnormal=true` 的 SQL 含 exists；QA+仅异常空页
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-06, AC-07
  **依赖**: T001

- [x] **T004**: Service + GET `/api/v1/knowledge` 接线
  **文件**: `src/backend/bisheng/knowledge/domain/services/knowledge_service.py`,
           `src/backend/bisheng/knowledge/api/endpoints/knowledge.py`,
           `src/backend/bisheng/knowledge/domain/models/knowledge.py`（`KnowledgeRead`）
  **逻辑**: 可选 `has_abnormal`；QA+true 空页；`aconvert_knowledge_read` 只对 `type=0` 批量填 `has_abnormal_files`；不改 v2 入参
  **覆盖 AC**: AC-01, AC-02, AC-04, AC-07, AC-08
  **依赖**: T001, T003

### Wave 3 — Platform

- [x] **T005**: 外层列表列、标签、筛选、i18n
  **文件**: `src/frontend/platform/src/pages/KnowledgePage/KnowledgeFile.tsx`,
           `src/frontend/platform/src/pages/KnowledgePage/components/FileAbnormalStatusCell.tsx`,
           `src/frontend/platform/src/controllers/API/index.ts`,
           `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/knowledge.json`
  **逻辑**: 列顺序名称 / 更新时间 / 创建人 / 文件状态 / 操作；红点+「异常」；`TableHeadEnumFilter` 的 `all`/`abnormal`；`filterData({ has_abnormal })`；三语文案
  **覆盖 AC**: AC-01, AC-02, AC-03
  **依赖**: T004

- [x] **T006**: 异常行进入详情预筛
  **文件**: `src/frontend/platform/src/pages/KnowledgePage/KnowledgeFile.tsx`,
           `src/frontend/platform/src/pages/KnowledgePage/components/Files.tsx`
  **逻辑**: 异常行跳 `/filelib/:id?fileStatus=abnormal`；内层 `useTable` 初始 `status=[3,6,7]` 并点亮筛选
  **覆盖 AC**: AC-05
  **依赖**: T005

### Wave 4 — 前端测试与回归

- [x] **T007**: 前端列表测试 + 既有列表回归
  **文件**: `src/frontend/platform/src/test/f064KbListFileAbnormal.test.tsx`
  **逻辑**: 有/无标签；筛仅异常调用 `filterData`；异常行导航带 `fileStatus=abnormal`。不破坏 F051 懒加载测试。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-05
  **依赖**: T005, T006

---

## 实际偏差记录

（实现中如有偏离，只留一行指针，论证回写 design.md。）
