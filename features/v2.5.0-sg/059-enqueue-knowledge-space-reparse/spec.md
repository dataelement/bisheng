# F059：知识空间文件重解析任务入队脚本

## 状态

- Status: `implementation complete; automated verification passed`
- Date: `2026-07-28`
- Detailed requirements: [requirements.md](./requirements.md)
- Detailed design: [design.md](./design.md)
- Release contract: [../release-contract.md](../release-contract.md)
- Tasks: [tasks.md](./tasks.md)
- Verification: [verification.md](./verification.md)

## 目标

新增独立运维脚本 `enqueue_reparse_knowledge_space_files.py`，完整复用
`reparse_knowledge_space_files.py` 的候选文件筛选语义，但不在本地进程执行解析。
显式传入 `--apply` 后，脚本将仍符合条件的文件切换为 `WAITING`，清理重解析相关字段，
并携带文件所属 `tenant_id` 把 `retry_knowledge_file_celery` 发布到
`knowledge_celery`。

## 核心契约

1. 新脚本默认 dry-run；未传 `--apply` 时不修改数据库、不发布消息。
2. 保留原脚本的空间、目录、文件、空间级别和状态筛选语义；直接复用候选收集实现。
3. 发布前按文件重新读取最新记录；状态漂移、记录删除、目录或非知识空间记录均跳过，不覆盖。
4. 合法文件在发布前持久化为：
   - `status=WAITING`
   - `remark=""`
   - `simhash=None`
   - `similar_status=0`
5. 每个任务使用 `retry_knowledge_file_celery.apply_async`，显式指定：
   - `args=[file_id]`
   - `queue="knowledge_celery"`
   - `headers={"tenant_id": file.tenant_id}`
   - 发布期间临时设置同值 `current_tenant_id`，并在 `finally` 中恢复，防止 Celery publish
     signal 覆盖 header 或把租户上下文泄漏到下一文件。
6. 单文件发布异常时恢复上述四个字段的原始快照，继续处理其他文件；恢复失败同时报告两个错误。
7. 任一发布/补偿失败时最终返回非零退出码；合法跳过不是失败。
8. “成功”仅表示 broker 接受任务，不等待或宣称 worker 已解析完成。
9. 不修改原脚本、worker task、Celery 路由、数据库 Schema、API 或前端。

## CLI 摘要

```bash
cd src/backend

# 默认 dry-run
PYTHONPATH=./ .venv/bin/python scripts/enqueue_reparse_knowledge_space_files.py

# 显式发布全部默认状态候选
PYTHONPATH=./ .venv/bin/python scripts/enqueue_reparse_knowledge_space_files.py --apply

# 按空间、目录、文件和空间级别过滤
PYTHONPATH=./ .venv/bin/python scripts/enqueue_reparse_knowledge_space_files.py \
  --space-id 10 \
  --folder-id 20 \
  --file-id 101 \
  --space-level department

# 显式选择状态
PYTHONPATH=./ .venv/bin/python scripts/enqueue_reparse_knowledge_space_files.py \
  --status failed \
  --status timeout \
  --apply
```

继续支持原脚本的 `--include-inflight` 与 `--only-inflight`，但两者可能与正在执行的任务重复，
必须保持显式 opt-in 并输出风险提示。原脚本的 `--concurrency` 是本地解析参数，不属于筛选条件，
新脚本按候选顺序逐文件发布，不提供该参数。

## 交付边界

- 新增：
  - `src/backend/scripts/enqueue_reparse_knowledge_space_files.py`
  - `src/backend/scripts/enqueue_reparse_knowledge_space_files.sh`
  - `src/backend/test/knowledge/test_enqueue_reparse_knowledge_space_files_script.py`
- 修改：
  - `src/backend/scripts/README.md`，仅追加新脚本说明并保留工作区已有修改。
- 不修改：
  - `src/backend/scripts/reparse_knowledge_space_files.py`
  - `src/backend/bisheng/worker/knowledge/file_worker.py`
  - Celery 配置、数据库模型和迁移。

## 验证摘要

- 复用并执行现有候选筛选回归。
- 新增测试覆盖 dry-run 无副作用、成功状态转换、筛选后状态漂移、跨租户 header、
  发布失败恢复、恢复失败双错误、继续处理、摘要和退出码。
- 执行定向 pytest、Ruff、compileall、shell 语法检查、CLI `--help` 和 `git diff --check`。
- 自动化验证不执行真实 `--apply`，不连接真实 broker、worker、Milvus 或 Elasticsearch。

## 一致性与运维风险

- 数据库提交和 Celery 发布不是原子操作。发布调用抛错时脚本会恢复字段，但 broker
  “已接受、客户端未收到确认”的不确定窗口无法由本脚本消除。
- 发布成功但 worker 未运行时，文件会保持 `WAITING`，直到队列被消费。
- 大范围执行会产生大量任务；运维人员必须先保存并检查 dry-run 输出。
- 显式选择执行中状态可能造成重复解析。

## Review Gate

- [x] Spec Discovery 已完成，筛选范围、worker 入口、完成定义和失败策略已确认。
- [x] Requirements 中每个 AC 均有验证方法。
- [x] Design 覆盖多租户、状态竞争、失败补偿和非原子边界。
- [x] 文件范围不修改原脚本、worker、Schema、API 或前端。
- [x] 用户已于 2026-07-28 确认规格。
- [x] 用户已授权在确认范围内快速生成任务并实施。
- [x] T001～T004 已完成，自动化验证证据记录在 `verification.md`。
