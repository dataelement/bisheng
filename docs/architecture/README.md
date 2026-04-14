# BiSheng 架构文档

BiSheng v2.4.0 是面向企业的开源 LLM 应用 DevOps 平台，基于 FastAPI + React + LangGraph 构建，采用 DDD 架构组织 15+ 领域模块，支持工作流编排、知识库/RAG、多 Agent 协作（Linsight）、MCP 集成、模型评测与微调。

## 仓库结构

```
bisheng/
├── src/backend/bisheng/           # FastAPI 后端主应用
├── src/backend/bisheng_langchain/  # LangChain 扩展包
├── src/frontend/platform/          # 管理端前端 (React)
├── src/frontend/client/            # 用户端前端 (React)
├── docker/                         # Docker Compose 部署
└── docs/                           # 文档
```

## 文档导航

| 文档 | 说明 |
|------|------|
| [系统架构全景图](./01-architecture-overview.md) | 运行时组件、请求数据流、技术栈、启动生命周期 |
| [后端领域模块总览](./02-backend-modules.md) | 15+ DDD 模块清单、分层约定、基础设施详解 |
| [工作流引擎](./03-workflow-engine.md) | LangGraph DAG 执行引擎、14 种节点类型、回调机制 |
| [知识库与 RAG 管道](./04-knowledge-rag.md) | 三阶段管道、双向量存储、文档处理流水线 |
| [Linsight Agent 与 MCP](./05-linsight-agent.md) | 自主任务框架、事件驱动、MCP 协议集成 |
| [双前端架构](./06-frontend-architecture.md) | Platform + Client 双应用、状态管理、组件库 |
| [数据模型与存储层](./07-data-models.md) | 24 个 ORM 模型、5 种存储引擎、DAO 模式 |
| [部署架构与配置](./08-deployment.md) | Docker Compose 编排、配置系统、开发环境 |
| [用户与权限体系](./10-permission-rbac.md) | 三层权限模型、RBAC、协作空间成员制、扩展分析 |
| [开发指南](./09-development-guide.md) | 环境搭建、模块约定、扩展点、测试 |
| [商业版 API 网关](./11-gateway.md) | Gateway 架构、SSO/OAuth 流程、内容安全、流控、开发环境 |

## 快速导航

- 想了解系统整体如何运行、各服务之间如何通信，请看 [系统架构全景图](./01-architecture-overview.md)
- 想了解后端代码的组织方式和各模块职责，请看 [后端领域模块总览](./02-backend-modules.md)
- 想了解工作流如何定义和执行、如何扩展自定义节点，请看 [工作流引擎](./03-workflow-engine.md)
- 想了解文档解析、向量化、检索的完整流程，请看 [知识库与 RAG 管道](./04-knowledge-rag.md)
- 想了解如何部署项目或搭建本地开发环境，请看 [部署架构与配置](./08-deployment.md)
- 想了解用户认证、角色权限、资源授权的完整机制，请看 [用户与权限体系](./10-permission-rbac.md)
- 想了解开发规范、如何新增模块或编写测试，请看 [开发指南](./09-development-guide.md)
- 想了解商业版网关（SSO/OAuth、内容安全、流控）的架构和开发方式，请看 [商业版 API 网关](./11-gateway.md)
