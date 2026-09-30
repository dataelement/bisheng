# 知识库任务精简：验证记录

## 状态

- Feature ID: `knowledge-task-consolidation`
- Date: `2026-09-23`
- Local status: `VERIFIED`
- Release status: `MANUAL_VERIFY_REQUIRED`
- 实现：T001–T004 均完成本地代码与回归；未提交、未部署、未清理队列。

最终本地结果：139 项相关测试通过，6 条现有第三方依赖警告；目标文件 Ruff 检查和 git diff --check 通过。AST 枚举知识库 Worker 定义从实施前 53 个降为 49 个，不包含 telemetry 目录。

## 证据 Evidence

| ID | Code State | Command / Step | Result | Scope |
|---|---|---|---|---|
| E-001 | 实施前工作区 | 九个目标测试文件基线，日志 /tmp/knowledge-task-baseline.log | PASS，113 项 | 基线，不覆盖后续新增行为 |
| E-002 | 新测试、旧推荐池实现 | test_portal_recommendation_worker.py -k 'pool_request or pool_producers' | 4 项预期失败 | 证明新增请求身份/内联行为原来不存在 |
| E-003 | T001 实现 | 推荐 Worker 与 Redis 仓储定向测试 | PASS，26 项 | 内联、上下文复用、过期跳过、已完成/被取代请求 |
| E-004 | T001 原子仓储实现 | test_portal_recommendation_redis_repository.py -k pool_request_lua | PASS，1 项 | Lua 实际执行于 fakeredis/Lupa；20 次并发领取同一请求仅分配一次 generation，旧代次拒绝激活、TTL、租户及损坏状态 |
| E-005 | T002 实现 | 标题、解析生命周期、处理租约、优先级投递、队列路由五组测试 | PASS，69 项 | 普通标题函数保留、解析路径和配置模板 |
| E-006 | T003 实现 | 热搜 Worker 与 API 两组测试 | PASS，18 项 | 手动/定时来源、不同重试策略、租户与实际任务名 |
| E-007 | T004 实现 | 推荐 Worker 与投影 service 两组测试 | PASS，34 项 | 批次、普通更新版本、SQLite 真实事务回滚与既有仓储版本行为 |
| E-008 | 四批最终生产代码 | 下方最终并集命令，日志 /tmp/knowledge-task-final-tests.log | PASS，139 项 | 含前面有效行为及新增批次投递失败/非法输入验证；以本证据为最终结果 |
| E-009 | 四批最终生产代码 | 目标文件 ruff check；git diff --check；AST 枚举；活动旧引用检索 | PASS；49 个任务定义 | 无旧入口活动引用、真实 Celery 注册与 Beat 一致性测试通过 |
| E-010 | 当前本地环境 | 检查 redis-server/valkey-server；docker image ls | MANUAL_REQUIRED | 未找到 Redis 服务二进制；Docker daemon socket 不存在，未启动或连接生产服务 |

E-008/E-009 的八个主要生产文件组合 SHA-256：`4522268f18aa29d26c3898915d1aea011309e53cea6a2644ac462f1acf0ef659`。顺序为 Worker portal_recommendation、portal_hot_search、file_title_worker、worker/__init__、core/config/celery_queues、portal_hot_search_admin_service、Redis 仓储 implementation、Redis 仓储 interface；逐文件按相对 src/backend 的路径字节与内容字节顺序拼接计算。测试之后仅更新 spec 文档。

## 最终回归命令

工作目录：`/Users/wenruli/code/project/bisheng/bisheng`。使用已有 Python 3.10 虚拟环境，未安装依赖。

```bash
src/backend/.venv/bin/python -m pytest \
  src/backend/test/knowledge/test_portal_recommendation_worker.py \
  src/backend/test/knowledge/test_portal_recommendation_redis_repository.py \
  src/backend/test/knowledge/test_portal_recommendation_projection.py \
  src/backend/test/knowledge/test_file_title_worker.py \
  src/backend/test/knowledge/test_knowledge_file_parse_lifecycle.py \
  src/backend/test/knowledge/test_knowledge_parse_processing_lease.py \
  src/backend/test/knowledge/test_knowledge_parse_priority_dispatch.py \
  src/backend/test/celery/test_knowledge_parse_queue_routing.py \
  src/backend/test/knowledge/test_portal_hot_search_worker.py \
  src/backend/test/knowledge/test_portal_hot_search_api.py \
  src/backend/test/celery/test_celery_beat_task_registration.py \
  -q --tb=short --disable-warnings
```

静态检查覆盖：三个目标 Worker、热搜管理 service、Redis 仓储接口/实现、队列路由，以及新增或扩展的推荐/热搜 Worker、Redis、Beat 注册测试。没有对未变更模块进行全量格式化。

## 验收覆盖

| Acceptance | Local status | Evidence | 发布前剩余验证 |
|---|---|---|---|
| AC-001 | PASS | E-008 | 真实 Broker 上确认正常每租户一条重建任务 |
| AC-002 | PASS | E-004, E-008 | Redis 实例/Cluster 原子性、连接超时、Worker 重投递，MANUAL_REQUIRED |
| AC-003 | PASS（本地边界） | E-008 | 带真实配置和池存储完成构建/激活冒烟 |
| AC-004, AC-005 | PASS | E-008, E-009 | 实际上传/重试后确认标题与解析结果 |
| AC-006, AC-007 | PASS | E-008 | 手动与定时触发真实执行；不将线程池 time_limit 当作强杀保证 |
| AC-008, AC-010 | PASS | E-008 | 实际批量业务观察投递大小与数量 |
| AC-009, AC-011 | PASS（SQLite） | E-008 | MySQL/DM8 锁、事务与并发联调，MANUAL_REQUIRED |
| AC-012 | PASS | E-009 | 无 |
| AC-013 | PASS（发布方案文档） | design.md 发布与回滚方案、本节操作清单 | 生产切换 NOT_RUN |

本地验证使用真实投影 service、SQLite 仓储事务和实际 Lua 解释执行；不代表真实 Redis、数据库方言、Broker 或生产多 Worker 场景已验证。沿用既有投影仓储版本机制，未新增持久化删除墓碑，也未宣称解决既有跨批并发的全部问题。

## 切换清单

最终删除的任务名：

- bisheng.worker.knowledge.portal_recommendation.prepare_pool_rebuild
- bisheng.worker.knowledge.file_title_worker.extract_knowledge_file_title_celery
- bisheng.worker.knowledge.portal_hot_search.trigger_portal_hot_search_rebuild
- bisheng.worker.knowledge.portal_recommendation.refresh_portal_recommendation_projection

仍沿用名称但参数改变的任务：

- rebuild_portal_recommendation_pools：原 generation/config_version/fingerprint 改为 request_id/requested_at。
- refresh_portal_recommendation_projection_batch：原 file_ids/projection_version/deleted 改为 events。

发布前需停止目标旧生产者，使用旧 Worker 排空以上六类旧格式消息（包括 reserved、active、scheduled/retry），再同步更新 Worker/API/Beat；不能只检查队列 ready 数量。回滚同样先处理新格式消息再同步退回。不执行整个 celery 队列 purge。详细顺序见 design.md。

推荐池请求上下文以 tenant/request_id 保存 7 天；超过该窗口的请求跳过。此窗口是新实现的明确边界，不等同于消息永久保留。

## 未执行项

- 真实 Redis/Cluster、Broker、MySQL、DM8 联调。
- 上传→解析→推荐/热搜结果的部署环境端到端冒烟。
- 生产消息盘点、排空、部署、回滚。
- Git 提交与推送。
