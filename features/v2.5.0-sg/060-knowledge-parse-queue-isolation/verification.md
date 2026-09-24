# Verification：知识文件解析队列隔离（F060）

**日期**: 2026-08-05  
**结论**: 代码、配置和定向回归通过；真实 Redis Worker 冒烟待发布环境执行。

## 验收证据

| 验收标准 | 结果 | 证据 |
|----------|------|------|
| AC-01～AC-06 | ✅ 通过 | 新增路由/YAML/source scan 契约测试；最终批次 26 项全部通过 |
| AC-07 | ✅ 通过 | 推荐、热搜、通知、投影、权限、课程、组织同步、迁移、解析重试和 PDF Worker 定向回归通过，tenant header 断言保留 |
| AC-08 | ⚠️ 静态通过 | 未执行 purge；默认 Worker 入口仍消费 `celery`。真实 Broker 消息观测留作发布门禁 |

## 已执行命令

- `PYTHONPATH=src/backend src/backend/.venv/bin/pytest ...`：四个互不污染的定向批次合计 **110 passed**。
- 使用真实 `celery.app.routes.MapRoute` 验证标题提取、首次解析、解析重试、QA、投影、PDF、工作流和审批共 8 个代表任务：通过。
- 导入 `bisheng.worker.config` 并断言运行时最终路由：通过。
- `python -m compileall` 覆盖队列配置、受影响 Worker/Service 和运维脚本：通过。
- `ruff check` 覆盖新增契约文件及路由核心/主要受影响文件：通过。
- `bash scripts/arch-guard.sh`：通过，无架构违规。
- `git diff --check`：通过。

## 基线问题与未执行项

- 对全部受影响 Python 文件执行整文件 Ruff 时报告 129 个既有问题，主要位于
  `knowledge_space_service.py`、`knowledge_imp.py` 和 `favorite_notify.py` 的未触及行；
  新增队列契约、契约测试及核心路由相关文件的定向 Ruff 已通过，本 Feature 未扩大范围清理历史 lint 债务。
- `test_file_title_worker.py` 的 4 个用例仍 patch 模块级
  `parse_knowledge_file_celery`，但生产实现已改为 `finally` 内延迟导入，因此该旧 mock 目标不存在；
  此问题在本次变更前的代码结构中已存在，未扩大范围修复。
- `test_pdf_artifact_deployment_contracts.py` 仍断言 `start_all_workers` 不包含
  `start_pdf`，而当前入口脚本明确包含它；该旧断言与当前实现不一致，未在 F060 中修改。
- 未连接真实 Redis/Milvus/ES/MinIO，也未启动生产 Worker。发布前需上传一个小文件并触发一个非解析任务，观察三个目标队列；不得清空存量消息。
