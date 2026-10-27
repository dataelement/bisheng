# 验证

- Feature ID: `079-unreadable-sync-file-cleanup`
- Updated: `2026-10-20`
- Status: `MANUAL_VERIFY_REQUIRED`
- 本地 T001–T003 完成。未暂存、提交、推送、部署或写线上数据；没有 Schema、依赖、运行配置变更。

## 证据

| Evidence | Command / Step | Result | Scope |
|---|---|---|---|
| E-001 | 初始损坏 PDF 接点回归；修正测试模型为真实 detached ORM 后执行新测试 | 原接点未抛专用错误；事务回归仍保留文件，1 failed / 8 passed，见 `/tmp/unreadable-sync-red.log` | 原问题复现；第一轮测试另有 transient 模型造成的主键冲突，已修正测试，不作为业务证据 |
| E-002 | 新原件及事务测试集 | 29 passed，见 `/tmp/unreadable-sync-module.log` | 加密 PDF、真实 OLE 目录包装、ZIP/XML 损坏、普通上传、失败类型、引用/版本/审批保护、回滚、重复及陈旧结果 |
| E-003 | 正式 `addEmbedding` → 真实原件校验 → 真实最终状态 Hook → SQLite 删除与清单；共享与旧存储参数化 | 2 passed，见 `/tmp/unreadable-sync-formal.log`；并入 E-005 | 首轮受项目 MagicMock 配置影响未到原件校验，换成真实 KnowledgeConf 后通过；业务代码未因测试改写 |
| E-004 | 对 4 项扩展失败加载 HEAD 版原有模块后单独执行；临时文件在 `/tmp/unreadable-sync-head`，未替换工作区 | 4 failed，与修改后相同，见 `/tmp/unreadable-sync-baseline.log` | 确认 2 项业务域旧断言、1 项审计责任人字段断言、1 项本机 SciPy Mach-O 加载失败为原有问题 |
| E-005 | 下方最终回归命令 | **160 passed, 4 deselected**, 6 warnings，exit 0，8.22s；`/tmp/unreadable-sync-final.log` | 当前代码及最终测试状态；包含真实标签/产物删除、权限失败保留任务与对象、恢复后只执行未完成阶段、真实仓储对象引用检查及后台保留分支 |
| E-006 | 新增 5 个 Python 文件 Ruff check/format；全部 11 个 Python 变更与 HEAD 按诊断类型和内容对照；py_compile；逐文件 arch-guard；git diff --check | 新文件 lint/格式通过，无新增 Ruff 诊断，编译和架构守卫通过，diff 无空白错误；`/tmp/unreadable-sync-lint-baseline.json` | 旧文件已有诊断保留，未称整个旧模块 lint 全绿 |

## 最终回归命令

工作目录 `src/backend`，使用项目现有 Python 3.10 虚拟环境：

```bash
.venv/bin/python -m pytest \
  test/knowledge/test_unreadable_sync_file_cleanup.py \
  test/knowledge/test_source_file_validation.py \
  test/knowledge/test_background_jobs.py \
  test/knowledge/test_knowledge_file_parse_lifecycle.py \
  test/knowledge/test_shared_space_direct_ingestion.py \
  test/knowledge/fulltext/test_fulltext_parse_lifecycle.py \
  test/knowledge/pdf/test_pdf_artifact_deletion.py \
  test/open_endpoints/test_filelib_sync.py \
  test/open_endpoints/test_filelib_sync_from_staged_file.py \
  test/open_endpoints/test_filelib_sync_audit.py \
  -k 'not (test_unbound_business_domain_is_rejected or test_business_domain_requires_portal_space_and_code_bindings or test_production_router_reaches_sync_handler_for_missing_params or test_write_upload_success_calls_ainsert_v2)' \
  -q --disable-warnings --tb=short
```

## 验收覆盖

| Acceptance | Status | Evidence |
|---|---|---|
| AC-01 原件明确分类 | PASS | E-002/E-005 真实加密 PDF、OLE 包装及损坏 ZIP/XML；有效 PDF/XLSX 不触发 |
| AC-02 保留普通上传和其他失败 | PASS | E-002/E-005 无来源、超时、普通失败码即使带 encrypted 字符串也不删；本地 I/O 和预算不足不判损坏 |
| AC-03 关联及快照保护 | PASS | E-002/E-005 历史、分享、收藏、纠错、审批；对象/来源/租户/状态已变不写回陈旧结果 |
| AC-04 事务及幂等 | PASS | E-005 文件/V1/文档/标签/产物、清单和 outbox 同事务；outbox 故障回滚；重复结果不复活、不新增清单 |
| AC-05 诊断与后台补偿 | PASS | E-005 失败原因和外部文件号保留在清单，原审计代码未修改；权限失败时对象不删，恢复后完成、重复任务不执行；既有删除失败/引用保护回归通过 |

## 自审和未验证项

- 无新增删除接口或权限授予，只有接口来源 + 专用失败码 + 原件/状态快照匹配才能走清理。所有新查询均使用 ORM 和既有租户注入，没有手工 tenant WHERE、原生 JSON SQL 或跨租户绕过。
- 不调用版本级联删除；任何已分发或历史关联均保留。审计和审批表不在删除目标中；仅删除文件标签关联，不删除全局标签定义。
- 清单与删除同事务；后台先确认源记录已消失才清理，权限步骤失败不推进对象删除。后台重试预算沿用既有 8 次，耗尽为 dead，可使用既有维护能力人工恢复；不承诺无限重试。
- 真实 MySQL/DM8 行锁和并发、真实 ES/Milvus/OpenFGA/MinIO 与大文件性能为 **MANUAL_REQUIRED**。SQLite 和受控外部替身不代表线上验收。无前端业务变更，未运行前端构建或浏览器验收。
- 部署需更新解析 worker 和默认后台 worker。验收时分别经接口上传有效、加密、损坏文件，确认失败记录消失、原审计仍在、后台 delete_file 终态及 outbox 删除完成；模拟权限/存储故障，验证恢复后收敛；普通上传及暂时性失败应保留。
- 无法可靠识别的格式、老式 DOC/PPT 专有加密和超出 Office 校验预算的文件保留原流程。保留对象被其他文件引用时不删；不会恢复同步入口在此前按既有规则替换的旧文件。
- 代码回退只能停止后续自动清理，不能恢复已经删除的记录和已经清理的对象；本次没有线上删除。
