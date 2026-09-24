# 默认个人库创建修复验证

Date: `2026-09-09`
Status: `MANUAL_VERIFY_REQUIRED`
Runtime: `src/backend/.venv/bin/python`, Python 3.10.19。复用既有依赖, 未安装或修改依赖。

基线 HEAD: `89672f15a`。最终 guard SHA-256: `dfb488462c3399f55718e64b91fa209478c99315954a5959523cb0acb00fe406`; 新测试 SHA-256: `d78bad141f67355ef46e9a1c54977d09c654ad0bf603143b8d838226ad3038b6`。

## 证据

命令工作目录为 src/backend, 除另注明外。

| ID | 命令/步骤 | 结果 | 范围 |
|---|---|---|---|
| E-001 | 新并发测试在原实现上运行 | FAIL, 12 次创建, 预期 1 次 | 12 个独立 Service/请求同时完成首次空查询, 稳定复现并发重复创建 |
| E-002 | `.venv/bin/python -m pytest test/knowledge/test_personal_default_space_creation.py -q --tb=short`, 接入保护后 | 1 passed | 相同并发场景只创建 1 个库, 12 个请求返回 ID 200 |
| E-003 | `.venv/bin/python -m pytest test/knowledge/test_personal_default_space_creation.py test/test_personal_default_space.py test/test_knowledge_space_service.py::test_system_personal_spaces_are_created_with_private_auth_type -q --tb=short` | 20 passed | 新文件 14 项, 旧创建/命名/身份及私有权限参数 6 项 |
| E-004 | 下方相关回归命令 | 166 passed, 7 failed | 默认库、收藏、归属、同步、迁移脚本、锁协议 |
| E-005 | 独立子进程用导入器从 `git show HEAD:<path>` 加载原 knowledge_space_service / knowledge model / knowledge_space errcode, 仅运行 E-004 失败的 7 项 | 7 failed, 与当前相同 | 没有还原或覆盖工作区文件。输出 `/tmp/personal-default-baseline-tests.txt` |
| E-006 | 新增 guard 和测试 `ruff check`、`ruff format --check`; 对所有本次修改的旧文件分别比较 HEAD/当前内容的 Ruff JSON 诊断 | PASS, 新增诊断 0 | 旧文件已有 258 条 lint 诊断, 未顺手全量格式化 |
| E-007 | 对本次 7 个代码/测试文件执行 `python -m py_compile`; 仓库根 `git diff --check`; 新旧 Service 的 `scripts/arch-guard.sh` | PASS | 语法、diff 和架构检查 |

相关回归命令:

```bash
.venv/bin/python -m pytest \
  test/knowledge/test_personal_default_space_creation.py \
  test/test_personal_default_space.py \
  test/test_favorite_service.py \
  test/test_personal_spaces_owner_scope.py \
  test/test_personal_space_protection.py \
  test/scripts/test_move_department_files_to_personal.py \
  test/open_endpoints/test_filelib_sync.py \
  test/open_endpoints/test_filelib_sync_dynamic_folder.py \
  test/knowledge/test_knowledge_migration_repository.py::test_global_lock_uses_token_cas_for_renew_and_release \
  test/test_knowledge_space_service.py::test_system_personal_spaces_are_created_with_private_auth_type \
  -q --tb=short
```

## 旧失败记录

- `test_rename_file_notifies_when_name_changed`, `test_rename_file_no_notify_when_name_unchanged`: 原入口的写冻结查询缺少数据库替身, MagicMock database_url 导致 ValueError。
- `test_delete_personal_space_is_rejected`, `test_delete_personal_space_with_force_bypasses_guard_and_skips_notification`: 同样缺少原写冻结查询替身。
- `test_grouped_personal_spaces_only_current_user_owned`: 原实现返回 `{117}`, 测试期望 `{117,149}`。
- `test_unbound_business_domain_is_rejected`, `test_business_domain_requires_portal_space_and_code_bindings`: 原实现记录 warning 后继续, 旧断言期望抛异常。

## 验收覆盖与限制

| AC | 证据 | 结论 |
|---|---|---|
| AC-01 | E-001/E-002/E-003/E-004 | 本地回归 PASS; 并发屏障确认原 bug 消失 |
| AC-02 | E-003/E-004 | PASS; 独立 tenant/user key; 已有库不依赖 Redis; SQLite 实际查询开启 reverse_unordered_selects 后仍选最小 ID |
| AC-03 | E-003/E-004 | PASS; fakeredis 执行真实 SET NX EX 和 Lua; 等待/IO 超时、断连、长操作续期、锁被替换、取消、创建/释放失败 |
| AC-04 | E-003/E-004 | PASS; 指定 owner 入口失败后身份恢复、原创建参数、同步和迁移脚本调用 |

未执行真实 Redis 集群/主从切换、多进程部署、MySQL/DM8 或生产创建。所有业务创建数据均为替身或隔离 SQLite, 没有处理线上 297 个用户的存量库。

部署时必须更新全部可能创建默认库的 API/同步/脚本实例。旧实例仍运行旧逻辑时不能宣称保护已完整生效。Redis 主从切换丢锁、进程暂停超过 TTL、创建中断后库记录与归属不完整, 仍需后续数据库唯一绑定/事务修复; 本次不宣称数据库级唯一性。

## 实现审阅

T001-T003 完成。范围内未发现阻塞交付问题; 未修改迁移锁底座, 新 guard 使用独立 key。已有库查询稳定排序, 创建只在获锁且二次查询缺失后执行。没有自动清理、数据迁移、Schema/配置变更、提交或推送。
