# F132 需求发现：长期记忆

日期：2026-11-13。分支 `feat/v3.0.0/132-long-term-memory`，从 `origin/feat/3.0.0@741662475b` 创建。

## 为什么从 `feat/3.0.0` 拉

本功能要进两条线：主版本线（3.1、3.2……）和基于 3.0 的定制分支 `feat/v3.0.0/118-kunlian-integration`。创建分支时，定制分支等于 `feat/3.0.0` 加 10 个提交，`feat/3.0.0` 只比 `feat/3.1.0-beta1` 多 2 个提交。从 `feat/3.0.0` 拉，合入定制分支时只带本功能的提交，合入主版本线时走既有的 3.0 → 3.1 流向。

编号取 132：同版本下 130、131 已被占用。

## 需求来源

- 调研：`docs/PRD/memory 长期记忆/memory 方案调研（结构版）.md`
- 需求：`docs/PRD/memory 长期记忆/长期记忆 PRD.md` v0.2

需求发现以逐项采访的方式完成，结论全部记录在 PRD §7。本文件不重复，只列对规格口径有决定作用的裁定。

| 裁定 | 口径 | PRD 决策号 |
|---|---|---|
| 范围 | 日常模式、深度研究、助手、工作流四类场景，同一个版本交付 | D4、D17 |
| 隔离 | 一个用户只有一份记忆，四类场景通用，每条记忆带来源标记；不存在按应用隔离的记忆 | D9 |
| 写入 | 两条途径：用户明确要求时模型调用写入工具；会话安静后系统自动整理 | D3 |
| 读取 | 常驻记忆每轮带入；其余按需检索。工作流只通过记忆检索节点读取 | D7 |
| 形态 | 以条目为单元，长正文放详情，条目里存指针 | D1 |
| 开关 | 没有租户级开关；用户级默认开；助手与工作流的开关默认关；工作流开关在开始节点 | D5、D11、D15、D33 |
| 可见性 | 除用户本人外，任何角色对其记忆无任何操作 | D13 |
| 管理页 | 进本期，支持查看、编辑、新增、删除、清空 | D14 |
| 不支持的身份 | 记忆只对登录用户的会话工作。开放 API 的全部调用、免登录链接、没有会话的评测与调试运行都不使用记忆 | D12、D31 |
| 模型缺陷 | 模型声称已记下而未写入时，系统不补写，只暴露和计数 | D8 |

## 基线重核（2026-11-13，`feat/3.0.0`）

PRD 附录 A 的取证是在较新的代码上做的。在本分支上已重核下列各项仍然成立，行号以本分支为准，留给 design 引用。

- 工作流节点类型枚举 14 类，无记忆相关节点：`src/backend/bisheng/workflow/common/node.py:8-26`
- 开场白、历史聊天记录、预置问题在开始节点模板里：`src/frontend/platform/src/controllers/API/workflow.ts:197`、`:231`、`:237`
- 助手设置页存在：`src/frontend/platform/src/pages/BuildPage/assistant/editAssistant/Setting.tsx`
- 助手运行时带调用用户：`src/backend/bisheng/api/services/assistant_agent.py:211-215`
- 日常模式的工具组装与知识库检索工具：`src/backend/bisheng/workstation/domain/services/chat_service.py:803`、`:1268`
- client 个人设置"个人"分组现有账号、AI 助手接入、桌面端、通用四项：`src/frontend/client/src/pages/settings/settingsSections.ts`
- 工作流、工作台、深度研究的运行时读不到外部用户标识（全目录检索无命中）
- 详情层拟复用的工作区后端存在：`src/backend/bisheng/linsight/domain/services/workspace_backend.py:519`；deepagents 版本约束 `>=0.6.12,<0.7`

未在本分支重核、留给 design 阶段：知识库检索节点的参数控件形态、引用角标组件的复用方式。

## 尚未确定

- 目标版本号（PRD §7.3 Q1）。本目录按开发基线放在 `v3.0.0` 下。
