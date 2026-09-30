# Tasks：知识文件解析队列隔离（F060）

**关联规格**: [spec.md](./spec.md)  
**版本**: v2.5.0-sg  
**状态**: 已完成  
**开发模式**: 后端 Test-First；同一代码状态复用定向验证证据

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已确认 | 2026-08-05 用户确认 |
| tasks.md | ✅ 已拆解 | AC、文件和验证命令已映射 |
| 实现 | ✅ 已完成 | 6 / 6 完成；生产 Worker 冒烟保留为发布门禁 |

## Tasks

- [x] **T001 测试：建立队列路由与部署契约**
  - **文件**: `src/backend/test/celery/test_knowledge_parse_queue_routing.py`
  - **完成条件**: 参数化覆盖三个解析白名单、知识非解析任务、PDF、工作流、审批、旧宽泛配置规范化；检查五份 YAML 和生产 Python 显式投递点。
  - **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06
  - **依赖**: 无

- [x] **T002 实现：集中队列契约与最终路由构建**
  - **文件**: `src/backend/bisheng/core/config/celery_queues.py`, `src/backend/bisheng/core/config/settings.py`, `src/backend/bisheng/worker/config.py`
  - **完成条件**: 纯函数集中定义队列名和三任务白名单；默认/自定义旧路由均不能把非白名单任务投递到 `knowledge_celery`；PDF、工作流和审批路由保持不变。
  - **配对测试**: T001
  - **覆盖 AC**: AC-01, AC-02, AC-04, AC-05
  - **依赖**: T001

- [x] **T003 实现：统一运行配置**
  - **文件**: `src/backend/bisheng/config.yaml`, `src/backend/bisheng/config_3002.yaml`, `src/backend/bisheng/config_3003.yaml`, `docker/bisheng/config/config.yaml`, `docker/bisheng/config/config_dev.yaml`
  - **完成条件**: 四份受版本控制的配置和当前本地 `config.yaml` 显式声明三个解析任务进入 `knowledge_celery`，知识非解析 wildcard 进入 `celery`，原 PDF/工作流职责不变；本地 `config.yaml` 受 `.gitignore` 管理，不作为 CI fixture。
  - **覆盖 AC**: AC-01, AC-04, AC-06
  - **依赖**: T002

- [x] **T004 实现：迁移非解析显式投递点**
  - **文件**: 检索基线命中的知识、组织同步、权限、投影、推荐、热搜、通知和运维脚本生产文件
  - **完成条件**: 非解析任务显式 queue 全部改为 `celery`；任务参数、tenant headers、expires 和异常处理保持不变；解析重试入队脚本继续使用 `knowledge_celery`。
  - **覆盖 AC**: AC-02, AC-03, AC-07
  - **依赖**: T002

- [x] **T005 测试：更新既有队列断言并执行回归**
  - **文件**: 受影响的 `src/backend/test/knowledge/`, `permission/`, `shougang_portal_course/` 测试
  - **完成条件**: 仅将非解析队列期望改为 `celery`，tenant header 和业务结果断言不变；F059 解析重试测试仍断言 `knowledge_celery`。
  - **覆盖 AC**: AC-03, AC-07
  - **依赖**: T003, T004

- [x] **T006 文档与验证：登记不变量和证据**
  - **文件**: `features/v2.5.0-sg/release-contract.md`, `features/v2.5.0-sg/060-knowledge-parse-queue-isolation/verification.md`
  - **完成条件**: 登记队列所有权不变量；运行定向 pytest、受影响模块测试、Ruff/compileall、架构守卫和 `git diff --check`；如无 Redis 集成环境，明确保留人工 Worker 冒烟门禁。
  - **覆盖 AC**: AC-01 至 AC-08
  - **依赖**: T005

## 实际偏差记录

- 队列契约模块从规格初稿的 `worker/task_queues.py` 下沉为
  `core/config/celery_queues.py`，以避免配置模型导入 Worker 包造成循环导入；行为范围不变。
- 未连接真实 Redis 启动 Worker 或发布消息；相关验证作为发布前人工门禁记录在
  `verification.md`，实现阶段没有执行 purge 或写入外部数据。
