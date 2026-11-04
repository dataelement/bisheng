# F112 应用发布说明 — 需求发现

## 1. 需求来源与确认

2026-10-27 用户提出：“应用发布有支持哪里可以加一下发布说明吗？类似功能发布文案这种”。

核对后提出：CLI 提交发布说明，随版本保存，在审批和版本记录中展示。
用户随后明确确认：“按这个方案增加应用发布说明，CLI 提交时填写，审批和版本记录里展示，按 SDD 流程推进，只做必要的定向验证。”

上述确认作为 SDD 的需求发现阶段确认。本轮编写正式规格并提交规格评审；不把需求发现确认视为正式规格或设计确认。

## 2. 静态核查基线

- 发版线：`origin/feat/3.0.0@e890280afb35cda0d78f6ec06b2e41af6856f7f9`，2026-10-27 fetch 后创建隔离工作树。
- 分支：`codex/112-vibe-release-notes`。
- 本轮只做源码与文档核对，未执行部署、Docker/K8s 或业务 E2E。

| 核查入口 | 已确认的现状 |
|---|---|
| `src/bisheng-cli/bisheng_cli/cli.py`、`commands/deploy.py` | deploy 没有发布说明选项；上传表单只有包、目标应用与结构变更确认 |
| `src/backend/bisheng/app_publish/api/endpoints/deploy.py` | 发布接收接口没有发布说明输入 |
| `src/backend/bisheng/app_publish/domain/schemas/app_manifest.py` | description 是应用介绍，未知声明字段被拒绝，不能直接往 YAML 写一个未支持的发布说明字段 |
| `src/backend/bisheng/app_publish/domain/models/app_deployment.py` | 发布尝试负责跨进程管线进度，没有发布说明资产 |
| `src/backend/bisheng/database/models/app_version.py`、`app_publish/domain/services/version_service.py` | 正式版本为只增不改的快照，尚无发布说明 |
| `src/backend/bisheng/app_publish/domain/services/publish_approval_service.py`、`app_publish_scenario_handler.py` | 审批内容先构建快照，再由场景适配为业务详情；目前不包含发布说明 |
| `src/frontend/client/src/components/approval/AppPublishDetailPanel.tsx` | 审批详情由 client 专用业务面板展示，不是 platform 版本列表 |
| `src/frontend/platform/src/pages/BuildPage/hostedApp/publish/VersionListCard.tsx` | platform 版本列表目前展示版本号、类型、时间和结果 |
| `src/backend/AGENTS.md` 的 CLI 包装合同 | backend 分发的是仓库内提交的 CLI wheel，仅改 CLI 源码不足以交付 |

F055 的“发布摘要”包括能力、档位和结构变更，不能视为已经支持开发者填写功能发布文案。F055 的审批和版本需求继续有效，本特性只追加发布说明。

## 3. 规格待确认的产品默认值

这些细节并非用户逐项指定，已写入 spec；2026-10-27 用户已一并确认正式规格：

1. 发布说明可选，旧 CLI 和未填写说明的调用继续可用；不增加交互式必答问题。
2. CLI 支持直接输入或读取 UTF-8 文本文件，二者互斥。
3. 最长 2,000 个 Unicode 码点，规范换行并去掉首尾空白，保留内部换行与缩进。
4. 作为纯文本展示，空值及历史版本显示“未填写发布说明”。
5. 提交后随本次发布冻结，不提供补写或编辑历史说明的入口。
6. 新 CLI 带说明连接旧平台时，不能静默丢弃说明，须在上传应用包前提示平台不支持。
7. 本期不做 Markdown 渲染、发布公告推送、公开发布日志或应用广场的更新提示。

## 4. 领域边界与定向验证计划

- F053 继续拥有 CLI 打包、分发和交互；F055 继续拥有发布输入、管线及应用发布审批场景；F054 继续拥有 AppVersion。F112 协调这些既有能力的增量，不转移领域所有权。
- 不把发布说明下发给 runtime-manager、app-proxy、egress-proxy 或应用容器。Docker 与 K8s 复用同一发布说明业务行为。
- 后续实现仅运行本功能涉及的 CLI、发布接收/跨进程保存/审批快照/版本读取定向测试、两处展示的组件验证及相关静态门禁。
- E2E 仅覆盖一条带说明发布到审批和版本记录的业务链路，并配对检查越权拒绝；不重跑容器编排全量、故障升级全量或基础设施全量回归。真实环境的写入范围在执行前结合当时授权与状态核对。

## 5. 阶段记录

| 阶段 | 状态 | 依据 |
|---|---|---|
| Spec Discovery | 已确认 | 用户 2026-10-27 明确“按这个方案”推进 |
| spec | 已确认 | 用户 2026-10-27 明确“确认规格，进入设计”；见 spec.md |
| design | 已确认 | 用户 2026-10-27 明确“确认设计，继续开发” |
| tasks / 编码 / 验收 | 实施中 | 见 tasks.md，按本功能定向验证收尾 |
