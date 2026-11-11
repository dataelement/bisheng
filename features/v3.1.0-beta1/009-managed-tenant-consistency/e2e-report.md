# E2E 覆盖报告：F009 管理租户最小修复

术语说明：本文技术符号和英文状态值统一见[术语与缩写说明](terminology.md)；H为用户主属租户，M为当前管理目标租户。业务阅读可直接参阅使用中文全称的[影响范围与测试重点](../../../docs/reviews/managed-tenant-impact-test-focus-20261111.md)。

**整体状态：PARTIAL（测试资产完成部分，实际端到端未验收）**。本地执行结果为0通过/3跳过/0失败；跳过原因是无专用测试部署及临时token。未以管理员线上数据替代普通身份测试，也未用SQLite单元/worker替身测试冒称端到端。

## API和AC覆盖

| AC-ID | 本批范围 | HTTP状态 | 当前证据及下一步 |
| --- | --- | --- | --- |
| AC-01 | 纳入 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-02 | 纳入 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-03 | 纳入 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-04 | 纳入 | 已写，未运行（SKIP） | test_e2e_managed_tenant_consistency.py: foreign_affiliation_form；本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-05 | 纳入 | 已写，未运行（SKIP） | test_e2e_managed_tenant_consistency.py: foreign_affiliation_form；本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-06 | 纳入 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-07 | 纳入 | 已写，未运行（SKIP） | test_e2e_managed_tenant_consistency.py: foreign_affiliation_form；本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-08 | 纳入 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-09 | 部分 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-10 | 纳入 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-11 | 纳入 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-12 | 部分 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-13 | 部分 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-14 | 部分 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-15 | 纳入 | 已写，未运行（SKIP） | test_e2e_managed_tenant_consistency.py: management_scope/ordinary_identity；本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-16 | 纳入 | 已写，未运行（SKIP） | test_e2e_managed_tenant_consistency.py: management_scope；本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-17 | 部分 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-18 | 部分 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-19 | 纳入 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-20 | 纳入 | 已写，未运行（SKIP） | test_e2e_managed_tenant_consistency.py: management_scope；本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-21 | 纳入 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-22 | 纳入 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-23 | 纳入 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-24 | 纳入 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-25 | 纳入 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-26 | 纳入 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-27 | 纳入 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-28 | 纳入 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-29 | 纳入 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-30 | 纳入 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-31 | 纳入 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-32 | 部分 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-33 | 延期 | 延期，不验收 | 全程复制逐项幂等/自动续传专项，本批没有实现 |
| AC-34 | 部分 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-35 | 部分 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-36 | 部分 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-37 | 纳入 | 已写，未运行（SKIP） | test_e2e_managed_tenant_consistency.py: ordinary_identity；本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-38 | 纳入 | 已写，未运行（SKIP） | test_e2e_managed_tenant_consistency.py: management_scope/ordinary_identity；本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-39 | 纳入 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |
| AC-40 | 部分 | 尚无HTTP自动化覆盖，待集成 | 本地回归映射见tasks/verification；隔离环境按QA与手动清单执行 |

## 运行条件

文件：`src/backend/test/e2e/test_e2e_managed_tenant_consistency.py`；专用`e2e-f009-*`管理员/普通人员，`E2E_ADMIN_TOKEN`、`E2E_F009_USER_TOKEN`及`E2E_F009_FIXTURES` JSON（fixture_prefix、home_tenant_id、management_tenant_id、foreign_department_key、user_id）。沿既有API_BASE/auth helper，不硬编码token。代码只改变专用管理员M并finally恢复，不写业务数据；更完整故障注入与GET最终确认仍须补齐并执行，不宣称39项HTTP覆盖。

UI清单：[e2e-checklist.md](e2e-checklist.md)，覆盖除AC-33外本批可观察结果；29条八列QA用例保持独立参考。测试部署还需MySQL/DM8、FGA、Redis、broker、MinIO/Milvus/ES；真实锁并发/复制外部副作用无法由本地SQLite证明。T047保持未完成，合入前集中验收。
