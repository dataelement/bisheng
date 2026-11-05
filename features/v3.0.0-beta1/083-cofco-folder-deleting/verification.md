# F083 状态功能验证记录

2026-11-05。本次状态功能已实现；loading 原因未复现，相关超时/列表刷新性能改动不在本次范围。验证时未部署，未删除客户/105业务数据；提交/推送状态以 Git 记录为准。

## 已通过

- 后端主要回归：212 passed，包含删除事务、完整授权、审批交接、未知提交、旧编号、并发核对、可见锚点/隐藏祖先、公开状态查询与实际 ASGI 路由。
- 协调者补充回归：26 passed，覆盖通用元数据单改/批改、真实附着 ORM 多行并发、跨空间 ID、状态筛选与总数、旧/新公共 DTO 脱敏、用户认证租户及真实 HTTP 状态/核对。该次与前一组部分重叠，不相加为总测试数。
- 修改/新增后端源码及补充测试 Ruff lint/format 通过；git diff --check 通过。架构守卫无 VIOLATION；两个 legacy endpoint 的 database.models 导入 WARNING 为既有路径，不是新引入。
- Client 三语 JSON/重复键/新增键一致性及差异空白检查通过。状态的前后端契约、权限及两轮独立代码复核发现的重要问题已修正；复核报告的结论为无遗留 Important/Critical。

本地测试配置复用 `/tmp/cofco-1111-unit-config.yaml`，测试只用独立的 SQLite 与受控的认证/权限边界；不是生产权限服务或双库行锁实测。

## 未验证

- 依用户约定，没有本地执行前端测试、lint、typecheck 或构建；仍由 CI/镜像质量门禁验证。
- 未做真实 MySQL/DM8 锁等待、驱动错误码、连接池争用与 UTC 时钟验收，SQLite 无法证明这些行为。
- 未做升级后真实浏览器慢删除、多标签页和移动端验收，步骤见 manual-checklist.md。
- 105 仍需更新后端以启用 `capabilities.folder_delete_status`；旧后端只使用第一阶段本页状态。完整体验需要新后端和新客户端。

## 更大范围探索性回归的已知失败

整知识模块探索性测试在中断前有 299 项通过、4 项失败，不能宣称全量回归通过。失败为既有外部样例/辅助方法问题：

1. `test/knowledge/rag/test_mineru.py::MineruTest::test_load`：另一开发机的硬编码 PDF 绝对路径不可用。
2. `test/knowledge/rag/test_paddleocr.py::PaddleOcrTest::test_load`：外部样例 PDF/解析前提不可用。
3. `test/knowledge/test_add_file_creates_document_v1.py::test_add_file_creates_document_and_v1`：既有调用引用不存在的 `preview_cache_key_for_split_rule`。
4. `test/knowledge/test_department_knowledge_space_upload_permission.py::test_department_space_upload_does_not_create_approval_request`：同一既有辅助方法缺失。

实施者核对 HEAD 中已存在相同样例路径/调用。未把这些无关问题混入本次业务修复。另一个 F046 schema 用例原错误使用 pending 执行态，已仅将测试输入修为 queued，使原资源类型映射断言可正常运行。

## 交付范围

复用已有文件夹 status 与 user_metadata；无表/字段/索引新增，无历史回填或迁移脚本。完整权限和审批/后台清理语义保留；OpenFGA 模型和数据未变。F048 适配器只将文件夹“删除中”映射为原 ACTIVE 权限事实，不改变授权结果。

## loading 诊断日志增量

仅补日志和来源标记，未修复或优化 loading。新增/相关后端聚焦验证 75 项通过，真实查询次数预算保持；独立复核无实质问题。Ruff lint/format 与 git diff --check 通过，未执行前端检查、部署或客户环境复现。详见 loading-log-guide.md。
