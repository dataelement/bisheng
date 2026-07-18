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
| [`PRD/`](PRD/) | 现行迭代的产品 PRD 与技术方案(按 `{版本} {主题} PRD/` 组织) |
| [`observability/`](observability/) | BS_METRIC 指标日志契约(监控团队解析依据) |
| [`私有化部署/`](私有化部署/) | 部署文档 |
| [`blog/`](blog/) | 设计科普(如"企业权限体系的前世今生") |
