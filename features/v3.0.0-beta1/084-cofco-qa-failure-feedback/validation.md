# 开发验证记录

代码与定向回归已完成，真实环境部署验收待执行。无数据库升级或额外脚本。

## 已运行

后端按模块串行运行，共 **121 项通过**：

| 范围 | 数量 | 命令（src/backend 下） |
|---|---:|---|
| 安全元数据、真实 SDK 异常、供应方/存储边界、旧记录脱敏 | 46 | `.venv/bin/python -m pytest --confcutdir=test/common test/common/test_failure_context.py test/common/test_provider_failure_boundaries.py test/common/test_storage_failure_boundary.py -q` |
| 步骤转换、名称快照、租户/权限候选、终态、既有重试/降级 | 63 | `.venv/bin/python -m pytest --confcutdir=test/linsight test/linsight/test_failure_step_metadata.py test/linsight/test_knowledge_step_metadata.py test/linsight/test_stream_event_mapper.py test/linsight/test_resilience_middleware.py -q` |
| 日常实时/历史、部分答案、保存失败、真实 ToolNode 软失败 | 12 | `.venv/bin/python -m pytest --confcutdir=test/workstation test/workstation/test_daily_failure_feedback.py test/workstation/test_agent_tool_error_handling.py -q` |

为避免单测导入时启动 worker/依赖配置，部分模式服务测试隔离加载生产函数体，只替换外部协作者；步骤转换与原有模型重试直接运行真实模块。这不能代替完整应用和真实中间件验收。既有 create_react_agent 产生 1 条弃用警告。

变更 Python 文件完成 Ruff 格式化；按 HEAD 的诊断内容比较无新增 Ruff 问题，旧文件已有诊断未全部清零。架构检查无 VIOLATION，仅保留 linsight Endpoint 旧 DAO 导入警告。

## 独立审查已修复

- 成功知识库结果与失败提示并存，错误元数据不计入结果数。
- 日常/任务业务错误继续按已登记错误码翻译；缺少版本 ID 的提交失败留在当前页面。
- 非 JSON 的 HTTP 错误不冒充网络故障；仅明确设备/传输证据生成网络元数据。
- 任务启动异常先查询已有版本；后台会话错误写回自身版本，不受当前选中会话影响。
- 实时限流继续保留执行、尝试、恢复对象、模型和状态字段。
- 日常/任务历史在响应时裁剪旧原始异常和附件错误；部分答案和资源快照保留。

## 待执行

未运行本地前端测试、类型检查、lint 或构建（按项目约定由镜像 CI 执行）。新增前端测试已编写。

未升级 105，也未运行真实应用/中间件/浏览器 E2E。参见 e2e-checklist.md；不得将定向单测结果当成场内验收通过。

## 同名分支同步复核（2026-11-05）

推送时发现远端已更新到 52472e0c6。仅将尚未发布的本地提交 rebase 到同名 1111 分支，自动完成，无冲突；range-diff 确认本次补丁等价。客户配置、授权模型保持不变，三语 translation.json 无重复 key。

同步后重新运行原 121 项定向回归，全部通过；另验证远端新加入的模型输出截断保护，11 项通过。该新增测试直接收集会因缺少 BS_MILVUS_CONNECTION_ARGS 而中止；隔离验证仅从生产 AST 加载 TaskExecutionError 类，实际 middleware/classifier 与测试逻辑保持原样，避免加载完整应用配置。完整后端/中间件联调仍未执行。
