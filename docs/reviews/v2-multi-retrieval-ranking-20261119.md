# Code Review Report

**Feature**: 3.1.0-beta1 v2 多库检索排序修复
**Review scope**: `RetrievalEngine.retrieve_many`、回归用例、接口文档与 F052 设计同步
**Base branch**: `origin/feat/3.1.0-beta1`，`065914f440`
**Changed files**: 6（含本报告）
**Workflow**: 按用户已明确指定的修复范围执行轻量 bugfix；无请求/响应字段、权限规则或数据库变更。按 `.claude/skills/sdd-code-review/SKILL.md` 七维度自行审查。

## Problem and behavior

`POST /api/v2/filelib/retrieve` 经统一门面调用引擎；原来各库分别 RRF 后按库顺序拼接，再截取 `top_k`，导致前库弱相关结果占满名额。

多库调用现保留原始分数，在逐库完成标签/成功主版本/可见性过滤后，用已有 `MultiRetriever` 分别形成跨库的 Milvus、ES 排名，再复用 `KnowledgeRetrieverTool._rrf_rerank` 做一次 RRF 融合与文本去重。之后应用每库独立 `max_content`，门面最后截取 `top_k`。不复制排序/RRF 算法、不新增模型依赖或分数校准。

单库调用沿用原检索路径。共享门面的 MCP、托管运行期、SDK 随同获得修复；平台聊天与工作台的原入口行为保留。原搬迁等价测试改为分别覆盖单个知识空间和单个文档库；多库行为由使用真实排序与 RRF 组件的新用例验证。

## Summary

| Dimension | High | Medium | Low | Status |
|---|---|---|---|---|
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 0 | 0 | PASS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync (design.md) | 0 | 0 | 0 | PASS |

## Evidence

- 在内存中载入基线 `retrieval_engine.py`，使用相同原始分数样本验证排名（为隔离排序问题，该次基线探针将结果层文件许可设为全通过）：两项失败、一项通过。失败分别是 `[弱库, 强库]`、`top_k=1` 返回弱库，以及逐库拼接 `A,B,C` 与已有工具链 `B,A,C` 不一致。该过程未改写基线/修复代码文件。
- 新增 16 项回归：两种库顺序下后库胜出、v2 端点与门面前 K、与真实工作流工具链一致、混合空间/文档库、源库与原文档元数据保留、过滤在融合前执行、空结果扩量、成功库不重复检索、每库限长、标签透传/空命中、权限故障、库级拒绝、空范围、单库路径、搜索失败取消同级任务、执行身份透传。
- 合并运行 15 个相关测试文件：**185 passed**。包含 F052 门面与端点、F118 调用身份/成功主版本资格、F029 文件过滤与原聊天/工作流消费者回归。外部传输使用可控替身，核心 `MultiRetriever`、RRF、门面与端点映射使用真实实现。
- 三个 Python 变更文件 `ruff format` / `ruff check` 通过；`scripts/arch-guard.sh` 无输出；`git diff --check` 通过。
- 检索任务只在单个请求中共享两路结果；索引过滤顺序准备，结果层数据库过滤由请求内锁串行执行；任何搜索/权限异常原样上抛并取消、等待同级任务，避免请求仓储关闭后仍有任务使用它。
- `docs/api/filelib-retrieve.md` 与 F052 `design.md` 的 D5、数据流、已知坑、依赖与验证已同步。

## Limits

未执行真实 Milvus、Elasticsearch、OpenFGA 环境联调或部署。原始分数比较与文本去重沿用现有多库工具，未新增跨模型/索引分数校准，也未改动其并列分数排序规则。`max_content` 沿用原工具的整块保留截止条件。

## Overall: PASS
