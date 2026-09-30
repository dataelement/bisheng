# 验证记录 Verification

**Feature ID**: `057-domain-bindable-spaces-perf`  
**Status**: VERIFIED  
**Updated**: 2026-07-16

## 自动化验证

| 验证项 | 命令 | 结果 | 覆盖 |
|---|---|---|---|
| BiSheng 专项测试 | `cd src/backend && ./.venv/bin/python -m pytest test/knowledge/test_shougang_portal_business_domain_codes.py -q` | PASS：9 passed | AC-REQ-001-01、AC-REQ-001-02、AC-REQ-002-01..04 |
| 门户候选空间与降级 | `cd backend && ./.venv/bin/python -m pytest tests/test_admin_config_api.py -q -k 'space_options or endpoints_fail_soft_when_bisheng_is_unauthorized'` | PASS：2 passed，57 deselected | AC-REQ-003-01、AC-REQ-003-02 |
| 门户业务域保存回归 | `cd backend && ./.venv/bin/python -m pytest tests/test_admin_config_api.py -q -k 'post_admin_domains'` | PASS：9 passed，50 deselected | 有效空间校验与业务域同步回归 |
| BiSheng 局部 Ruff | `cd src/backend && ./.venv/bin/ruff check bisheng/knowledge/domain/schemas/knowledge_space_schema.py test/knowledge/test_shougang_portal_business_domain_codes.py` | PASS | 新增 DTO 与测试 |
| Python 编译 | `python -m py_compile`（两端改动 Python 文件） | PASS | 语法与导入 |
| 差异检查 | 两个仓库分别执行 `git diff --check` | PASS | 空白与补丁格式 |

## 未通过或未运行项

- `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py` 的全文件 Ruff：FAIL，报告 78 项已有问题（历史 import 顺序、中文标点规则、旧代码静态错误等），不由本功能引入；本次没有修复范围外问题。
- BiSheng 服务端完整测试集、门户完整 `test_admin_config_api.py` 与前端测试：NOT_RUN。本功能定向回归已覆盖接口和业务域保存路径；完整门户套件此前存在与本功能无关的 QA 展示测试问题，未扩大修复范围。
- 真实 MySQL/DM8：MANUAL_REQUIRED。本功能无迁移，仅使用现有 scope 与 knowledge DAO；应在 CI 对两种数据库执行定向测试。

## 人工验证步骤

1. 使用 BiSheng 超管调用 `GET /api/v1/knowledge/shougang-portal/spaces/domain-bindable`，确认只返回已发布的公共、部门空间。
2. 使用非超管调用同一接口，确认返回未授权响应。
3. 使用门户管理员打开业务域新增或编辑弹窗，确认候选空间能加载且不出现个人、团队、未发布空间。
4. 让 BiSheng 专用接口返回错误，确认门户弹窗显示空候选项而不会请求 `/api/v1/knowledge/space/grouped`。
