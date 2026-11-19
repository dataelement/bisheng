# Code Review Report

**Feature**: cofco-1118 v2 多库检索排序 bugfix
**Review scope**: 该分支聊天服务纯检索路径、测试和接口/修复设计文档
**Base branch**: `origin/feat/cofco-1118-3.0.0-beta1`，`c48b535e2c`
**Changed files**: 7（含本报告）
**Workflow**: 按本分支 `.claude/skills/code-review/SKILL.md` 七维度自行审查；权限判定以当前 `docs/constitution.md` C4 为准。用户明确要求在本分支独立实现，无 cherry-pick 或跨线合并。

## Problem and behavior

原 `KnowledgeSpaceChatService.aretrieve_chunks` 将逐库 RRF 结果拼接后截取前 K，前库弱相关结果能占满名额。修复使用已有 `MultiRetriever` 分别形成向量/关键词两条全局分数排名，再做一次 RRF、每库独立限长、截取 K。

实现保留本分支空间/文档库权限、标签解析、两轮扩量和更新时间补齐。特别保留 F046 查询扩展、名称/正文 OLD 视图投影及原未发布/删除/主版本文件过滤，投影副本不会改写 native store 候选。v2 的操作人解析、schema 范围和 503/26030 权限故障映射不变。单库仍走原分派路径。

分支差异及技术决策见 [修复设计](../fixes/cofco-1118-v2-multi-retrieval-design-20261119.md)。中粮没有 beta1 的统一门面/引擎；本修复没有移入这些模块，Eplus 机器人和工作台排序实现没有改动。

## Summary

| Dimension | High | Medium | Low | Status |
|---|---|---|---|---|
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 0 | 0 | PASS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync | 0 | 0 | 0 | PASS |

## Validation

- 修复前直接在本分支跑排序样本：**2 failed, 1 passed**。`[弱库, 强库]` 的 `top_k=1` 错选弱库，`A,B,C` 拼接结果与已有多库工具 `B,A,C` 不一致；逆序仅碰巧选对。
- 新增 **19 项**本分支回归，核心排序/RRF使用真实组件。覆盖库顺序、混合资源类型、工作流链等价、标签/主版本与审批排除边界、查询扩展、真实 F046 名称投影、元数据不原地修改、每库预算、重试、执行 actor、v2 成功与原 503 映射、失败取消同级任务、单库及空范围。
- 初始四文件基线为 **31 passed, 5 failed**：旧 F029 visibility mock 缺失中粮异步投影 hook。按分支合并手册 §2.2 为测试补齐直通 `AsyncMock`，原权限/重试断言未放宽，生产单库方法未改。
- 最终将 **14 个相关文件合并运行**：**140 passed, 1 failed**，无新增失败。包含纯检索、v2/F046 边界、名称/引用、主版本、空间工作流、Eplus 排序/并发及工作台检索。
- 唯一剩余失败 `test/workstation/test_query_chunks_visibility.py::test_query_chunks_org_kb_init_failure_is_reported`：断言期待 provider 原异常 `embedding init failed`，当前分支返回脱敏诊断提示。在内存加载未修复的 `c48b535e2c` 聊天服务后重跑该工作台文件仍 **8 passed, 1 failed**，断言差异完全一致。该测试及工作台生产代码未改。
- 4 个 Python 变更文件 Ruff 格式/检查通过，架构守卫无违规，`git diff --check` 通过。没有前端或数据库改动。

## Limits

未部署，未执行真实 Milvus/ES/OpenFGA 联调。跨库原始分数比较、文本去重和并列规则沿用已有工具，未另加分数校准；每库限长沿用整块保留截止规则。

## Overall: PASS

本次修复无阻断项；扩展回归的上述 1 项基线失败如实保留，不能将本记录解读为整组选例全绿。
