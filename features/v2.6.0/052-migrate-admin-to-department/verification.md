# Verification: F052-admin 账号组织迁移运维脚本

**Status**: VERIFIED（自动化与 CLI 冒烟）；真实维护环境写入需人工执行。  
**Updated**: 2026-07-10

## 失效的旧验证

此前“资源转移给接收人”的 7 项单元测试和相关 CLI 验证已因需求变更失效，不能用于证明当前规格通过；已由下列资源保留测试替代。

## 待执行验证

- `uv run pytest test/department/test_migrate_admin_to_department_script.py test/test_user_department_service.py test/test_user_tenant_sync_service.py`：PASS，21 passed。
- `uv run ruff check scripts/migrate_admin_to_department.py test/department/test_migrate_admin_to_department_script.py test/test_user_department_service.py test/test_user_tenant_sync_service.py`：PASS。
- `bash scripts/migrate_admin_to_department.sh --help`：PASS，确认不包含 `--transfer-to-user-id`。
- 未执行真实 `--apply`：维护窗口中验证资源 owner 未变化、主部门/叶子租户已变更、全局配置未变化、`failed_tuple` 已收敛。
