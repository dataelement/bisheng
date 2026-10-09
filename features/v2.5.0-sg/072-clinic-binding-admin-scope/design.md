# 实现设计

## 当前链路与方案

`CreateKnowledgeSpaceDrawer → GET create-options/my-department-tree → get_my_department_tree_for_create → _clinic_visible_departments`。

创建与改绑通过 `_can_bind_clinic_department` 校验同一范围方法。复用此链路，不新增 API 或数据库查询入口。

- 当前租户活跃组织由既有 DAO 一次读取，剔除软删除记录。
- 在 `clinic_department_bind.py` 增加纯范围计算：保留已有授权组织路径子树并集；对班组或更下级授权沿 `parent_id` 链查找最近有效 `office`，只补入该科室 ID。
- 父链仅在已读取的当前租户有效组织中查找；遇到缺失父节点或循环即结束，不使用 `path` 猜测上级科室。
- 对合并结果复用既有公司/部门/科室裁剪、父节点重挂及 ID 去重。
- 服务统一返回裁剪后的范围，供下拉和非系统管理员绑定校验共用。
- 保留管理员资格、已绑定禁选、编辑排除当前绑定及知识库编辑权限校验。科室默认查看者授权流程保持。

## 文件计划与追踪

| 文件 | 职责 | Requirements |
|---|---|---|
| `src/backend/bisheng/knowledge/domain/services/clinic_department_bind.py` | 授权子树并集与最近科室查找 | REQ-1, REQ-2, REQ-4 |
| `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py` | 接入统一候选范围 | REQ-1–REQ-4 |
| `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py` | 同步接口说明，无接口变化 | REQ-2 |
| `src/backend/test/knowledge/test_knowledge_space_my_department_tree.py` | 下拉范围回归 | REQ-1, REQ-2, REQ-4 |
| `src/backend/test/knowledge/test_clinic_space_bind.py` | 创建允许与拒绝回归 | REQ-3 |
| `src/backend/test/knowledge/test_clinic_space_permissions.py` | 真实事务/Fake OpenFGA 改绑与编辑权限回归 | REQ-3 |

## 验证与回退

先运行已有相关基线，再加入失败用例，实施后执行同一相关回归集、定向 Ruff 和 diff 检查。复用现有模拟 DAO、SQLite 与内存 OpenFGA，测试不连接线上环境。

真实门户及线上部署验证单独记录；本地证据不代表线上生效。回退此次代码即可恢复后续绑定限制，无 DDL 或数据迁移。
