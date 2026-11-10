# 模型审计开发交付进度

日期：2026-10-14。核心功能与本机双端联调已完成；发布验收 PARTIAL。未提交、推送、合并或部署。

## 当前实现

服务端与客户端均位于各自 `feat/3.0.0-dsh-audit` 工作树。服务端完成 **65/70** 个任务，客户端 C001 至 C009 完成，C010 正式 UI 验收部分待执行。原首批 17/70 记录已被本阶段取代。

模型统一接口输入/输出 → 有界异步队列 → SQL 元数据及 AES-GCM MinIO 原件 → 管理查询、按会话请求卡片、按需原文读取及查看留痕已接通。按租户 OFF/METADATA/CONTENT，默认 OFF；模式读取失败 OFF。审计失败不失败或重放模型调用，接受明确的审计缺口。

超管与租户管理员按历史记录所属租户查看元数据及原文，只有超管变更模式。客户端仅传能力协商支持的 conversation_id/request_kind；无关联不拒绝业务，无源消息 ID、补报、气泡重建、安全围栏或过期删除。

## 完成验证

- 服务端定向：103 passed、2 skipped、1 deselected；最新真实 MySQL/Redis/MinIO HTTP 验收 1 passed。
- 最新客户端代码到冻结服务端：1 passed（830ms），7 次无重放；四次会话顺序、大小写/尾空格隔离、未关联、原文完整及 audit_context 剥离通过。
- Platform 5 文件 22 项通过；全前端类型检查、三语校验、Platform 构建、修改文件静态检查通过。实际桌面页面验证默认无原文、单次展开、四次请求顺序。
- 正常三模式小样本 30 次：开启模式 20/20 元数据，CONTENT 10/10 完整；不是生产覆盖率或 SLA。

## 未冻结为发布完成的任务

T063：真实 DM8/完整共享故障矩阵；T064/C010：正式 JWT/OpenFGA/Gateway/供应商/Electron/Fork/并行 Agent/Windows；T065/T066：并发长流及故障分类量化；T068：全面门禁。全 DSH 的 7 个失败与干净基线相同，Platform 全量 ESLint 的 93 个 error 亦与基线一致，未用 suppression 掩盖。

开发基线为 eb41b17868dfd706b93fc4df27d8d09ed10960ee，本地发布线引用已前移至 e058f58eb8d03cf582725d31e194eeeb16fce205，尚未同步；合并前须同步后回归。不把本阶段当成 beta2 发布声明。

详细命令、样本与限制见 [验证结果](./validation-results.md)、[AC 验收](./audit-acceptance.md)、[实现评审](./implementation-review.md)；安全启用/回退见 [运行说明](./audit-rollout.md)。临时测试实例结束后整体清理，仅保留源码、报告、合成请求编号和页面截图，不保留凭证。
