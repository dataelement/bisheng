# Code Review Report

**Feature**: F025 数据集迭代（2026-11-26）

**Review scope**: 本轮目录、显式转换、任务临时上传、旧入口兼容及配置；不复评历史 FT 功能是否已完成目标环境验收。

**Base**: `3b7cc045a1895ebc7c709e8a2186296d4f676f16`（当前微调分支模型名修复后）

**Changed files**: 65，包含三语与路由 scope 生成产物。

**Review method**: 主 agent 按项目 `/sdd-code-review` 七维清单本地复核；非独立外部审计；此记录不代表分支合并或环境部署。

## Summary

| Dimension | High | Medium | Low | Status |
|---|---|---|---|---|
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 1 | 0 | PASS_WITH_WARNINGS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync (design.md) | 0 | 0 | 0 | PASS |

## 复核证据

- 边界：分类由实际内容确定；旧格式转换严格保留 system/history/input，未知字段报位置；单一数据源、上传大小、媒体路径/清单白名单沿用；SQL 分页与总数同条件。DDL 单 head 且可重复升级，升级默认值/唯一上传约束及 downgrade 保留原行有 SQLite 测试。
- 权限：管理路由复用数据集菜单准入；候选与临时上传复用模型菜单；严格租户 Repository 查询。目录管理预览不额外要求模型菜单。Redis 凭证带 tenant/user，错误租户版本关联不能进入候选或计数，普通菜单用户允许/拒绝配对通过。新媒体响应 private/no-store/nosniff。
- 并发：目录/版本同事务；版本目录关联与任务上传 ID 唯一。临时重试配置快照不包含凭据；重复和唯一冲突返回任务前重查当前服务归属，FT 不重复创建。目录软删除保留历史引用和防止登记复活。
- 泄漏：源凭据只在请求中使用；沿用专用解析与错误脱敏；报告和计划不存密码。浏览器 url/report 不能作为授权或校验依据；归属失败不返回目标数据。无新增凭据、FT 认证或日志明文。
- 测试：本轮关联前端 34 项通过；后端 313 项通过，含隔离 HTTP 流程。数据库和对象存储替身边界、真实协议/登录/GPU 未覆盖项均明确记录。QA 用例保持待执行。
- 分层：新增 ORM 查询只在 Repository；纯转换无外部 I/O；Service 编排存储和连接器，路由调用 Service。Client 只同步生成错误码，无 Worker/FT/LlamaFactory 改动。
- 文档：design 的决策 6/10—12、模型/路由/职责、依赖、租户查询与代理陷阱和修订历史已更新；任务与验证/升级清单一致。

## Findings

### 已修复

- COUNT 关联查询未总能被自动租户过滤发现：候选列表/数量统一使用官方 `build_tenant_filter_clause`，补充错误租户关联负向测试。
- 用版本外连接枚举目录会隐藏无版本的 legacy 项：改为目录 SQL 分页后按页查版本。
- 新持久上传未命中旧大文件 location：三种部署配置同步扩展既有规则，未扩展产品需求。
- 上传响应来自尚未持久化的中间对象导致 tenant/type 不准确：响应改读已保存目录对象，现有 QA/普通用户回归通过。
- 新鉴权媒体路由响应补齐 private/no-store/nosniff，与现有版本媒体保持一致。

### MEDIUM

- [Baseline test harness] 扩大前端回归出现 1 个未处理异常：`knowledgeModelRetention.test.tsx` 的 `@bisheng/ui` mock 缺少 `LoadingIndicatorProvider`。在基线 `3b7cc045` 的原始前端归档中独立运行亦复现，因此不在本迭代修改。不能将该扩大回归报告为全绿；本轮关联 34 项及 typecheck/lint/build 已通过。

## Overall: PASS_WITH_WARNINGS

本轮未发现未解决的阻断性代码问题。真实部署、浏览器及 MySQL/DM8/GPU 联合验收仍为 T051，未执行不作为本地通过结论。应用合入和上线还需遵循目标分支流程；本次仅交付源码。
