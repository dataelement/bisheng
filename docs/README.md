# BiSheng 文档导航

> 找文档从这里开始。原则:**规范看根目录、架构看 `architecture/`、功能文档看 `../features/`**。

## 规范(开发前必读)

| 文档 | 内容 |
|------|------|
| [`constitution.md`](constitution.md) | 架构铁律 C1–C7(双 DB / 多租户 / 权限 / 分层 / 错误码 / 安全)——不可违反 |
| [`SDD-Guide.md`](SDD-Guide.md) | 开发流程总纲:流程分级、★ 暂停点、偏差处理、测试分层、harness 现状 |
| `../AGENTS.md` | 全局 agent 规则入口(各子项目规则按目录自动加载) |

## 架构(子系统深度)

[`architecture/`](architecture/) — 13 篇:总览 / 后端模块 / 工作流引擎 / RAG / Linsight / 双前端 / 数据模型 / 部署 / 开发指南 / 权限 ReBAC / 商业网关 / 多租户 / 游标分页 + 数据库表结构。子系统架构的唯一正文。

## 功能文档(SDD 产出)

[`../features/`](../features/) — 按 `v{X.Y.Z}/{NNN}-{name}/` 组织,每个功能含 `spec.md` / `design.md` / `tasks.md`(及按需 `testcases.md`,如 F025)。模板见 [`../features/_templates/`](../features/_templates/)。

## 接口 · 测试 · 部署 · 科普

| 目录 | 内容 |
|------|------|
| [`api/`](api/) | 接口文档(filelib 纯检索、知识空间/知识库接口) |
| [`qa/`](qa/) | 本地测试数据备忘(星辰公司组织结构与账号) |
| [`私有化部署/`](私有化部署/) · [`商业拓展套件gateway部署说明/`](商业拓展套件gateway部署说明/) | 部署文档 |
| [`blog/`](blog/) | 设计科普(如"企业权限体系的前世今生") |

## 历史(仅供追溯,非现行规范)

[`archive/`](archive/):
- `2.5 权限管理体系改造 PRD/` — v2.5 多租户/权限改造的完整 PRD、技术方案、运维手册(已实现,移此归档)
- `2.5-review-process/` — v2.5 权限/ReBAC review 过程文档、迁移排查、代码质量报告
- `cleanup-tasks/` — 各类"移除/清理"任务清单(org_sync、默认用户组)
- `legacy-sdd/` — 旧 SDD 的 spec/plan(达梦支持、文件解析调度等;现已被 `features/` + `SDD-Guide.md` 取代)
