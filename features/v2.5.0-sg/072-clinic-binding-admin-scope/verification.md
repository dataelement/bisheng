# 验证记录

- Date: `2026-10-09`
- Overall Status: `LOCAL_VERIFIED`
- Code State: 当前工作区的三个生产文件与三个科室测试文件；未提交、未部署。
- Runtime: `src/backend/.venv/bin/python`，Python 3.10.19。

## 实际证据

命令工作目录均为 `src/backend`，Git 检查在仓库根目录执行。

| Evidence | 执行 | 结果 | 日志 |
|---|---|---|---|
| E-001 | 四个相关测试文件的修改前基线 | PASS，29 passed，exit 0 | `/tmp/clinic-binding-baseline.log` |
| E-002 | 加入最近科室预期后、修改生产代码前运行三个相关测试文件 | 8 failed，32 passed，exit 1；失败为下拉缺少最近科室、创建及改绑被拒绝 | `/tmp/clinic-binding-red.log` |
| E-003 | 最终四个相关测试文件，包括 HTTP 接口契约 | PASS，46 passed，8 warnings，exit 0 | `/tmp/clinic-binding-final.log` |
| E-004 | 新范围模块及三个测试文件 Ruff check / format --check；三个生产文件 py_compile；本任务路径 git diff --check | PASS，exit 0 | 工具执行输出 |

最终相关回归命令：

```sh
.venv/bin/python -m pytest \
  test/knowledge/test_knowledge_space_my_department_tree.py \
  test/knowledge/test_clinic_space_bind.py \
  test/knowledge/test_clinic_department_bind.py \
  test/knowledge/test_clinic_space_permissions.py \
  -q --disable-warnings
```

静态检查命令：

```sh
.venv/bin/ruff check bisheng/knowledge/domain/services/clinic_department_bind.py test/knowledge/test_knowledge_space_my_department_tree.py test/knowledge/test_clinic_space_bind.py test/knowledge/test_clinic_space_permissions.py
.venv/bin/ruff format --check bisheng/knowledge/domain/services/clinic_department_bind.py test/knowledge/test_knowledge_space_my_department_tree.py test/knowledge/test_clinic_space_bind.py test/knowledge/test_clinic_space_permissions.py
.venv/bin/python -m py_compile bisheng/knowledge/domain/services/clinic_department_bind.py bisheng/knowledge/domain/services/knowledge_space_service.py bisheng/knowledge/api/endpoints/knowledge_space.py
```

## 验收覆盖

| Acceptance | Status | Evidence / 范围 |
|---|---|---|
| AC-1 | PASS | E-003：独立组织、部门+班组混合授权、上下级重叠授权与多班组同科室去重 |
| AC-2 | PASS | E-002/E-003：班组及未标记的班组下级沿父链获得最近科室，不包含兄弟科室 |
| AC-3 | PASS | E-003：真实 FastAPI 端点及审批创建校验；SQLite 事务/Fake OpenFGA 改绑，保持编辑权限拒绝、默认权限及失败恢复 |
| AC-4 | PASS | E-003：缺失父节点、循环、归档、软删除、下级误标科室安全结束；无组织管理员授权不扩大范围；当前租户查询、已有绑定及编辑排除当前库回归 |

## 验证边界

- HTTP 测试注册真实接口函数，使用真实服务校验，模拟已登录用户、组织 DAO、名称查重及模型配置；它不验证真实认证中间件、线上数据一致性或创建完整落库流程。
- 改绑集成使用 SQLite 真实事务与内存 OpenFGA；未执行真实 MySQL、DM8 或线上 OpenFGA 测试。本次无 SQL/Schema 改动。
- 真实门户浏览器与生产环境：`MANUAL_REQUIRED`。未启动完整服务、未部署、未修改线上数据。
- 发布后需用多组织管理员及班组管理员核对下拉、实际创建和改绑；核查兄弟科室不可选，以及非编辑者不能改绑。
- 创建资格的 OpenFGA 与 `department_admin_grant` 数据来源维持现状，本次不进行历史授权数据补齐。
- 回退此次代码可恢复后续范围限制；已创建库及授权不会自动撤销。
