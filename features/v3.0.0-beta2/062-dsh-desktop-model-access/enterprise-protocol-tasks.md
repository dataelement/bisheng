# 企业协议执行任务

Design 已于 2026-10-16 获用户确认。实现依据 enterprise-protocol-spec.md 和 enterprise-protocol-design.md。

- [x] T1 Chat reasoning：声明、目录、schema、默认/显式档位验证及 SDK 参数。
- [x] T2 对话身份：Harness 参数、broker 白名单、服务端隔离、SDK 请求级头。
- [x] T3 图片恢复：真实 Session 卸载、重新派生及重试组合验证。
- [x] T4 原生 Responses：严格 schema、供应商 adapter、共享治理和计量。
- [x] T5 原生客户端：能力协商、公开 pi-ai transport、完整输出及加密回放。
- [x] T6 定向组合、完整 Desktop 回归、构建、契约文档与交付证据。

## 验证证据（2026-10-16）

| 范围 | 实际结果 |
| --- | --- |
| Desktop `npm run typecheck`、`npm run build` | 通过；macOS arm64 本地构建，不是安装包验收 |
| Desktop `npm test`，启用 `BISHENG_BACKEND_ROOT` | 220 文件、1895 通过、1 跳过；随后 SSE 跨分块修复后的全量 `npx vitest run` 为 220 文件、1896 通过、1 跳过 |
| Bisheng 定向 pytest | 136 通过、3 跳过；覆盖 enterprise_protocol、native_responses、model_service、models_api、model_snapshot、vision、protocol、model_access、cache_tokens |
| Ruff | 15 个涉及后端文件 format/check 通过 |
| 架构守卫 | 修改的 DSH 模块与 LLM 模块文件通过，无输出违规 |
| 两仓库 `git diff --check` | 通过 |

pytest 从 `src/backend` 使用 `.venv/bin/python -m pytest --confcutdir=test/dsh`，清除 HTTP 代理环境变量，`config` 指向仅含 `{}` 的临时 YAML；未连接真实企业配置或生产存储。不是整个后端项目的完整测试。

## AC 与组合覆盖

- AC-R1、AC-R2、AC-R3：现有高级参数声明解析、真实 BishengLLM 构造、请求级 Chat SDK 副本、非法档位准入前拒绝；跨仓库 HTTP 验证 Chat/native 默认 low 与显式 high 均到达真实 SDK 请求构造。
- AC-S1、AC-S2、AC-S3、AC-S4：受控头白名单和重复/非法值拒绝；摘要按租户、用户、模型、用途隔离；HTTP 组合中四次调用摘要一致。已核对锁定 Harness 的 compaction、session-title 入口均传递 sessionId 与独立 purpose。
- AC-I1、AC-I2、AC-I3：真实 Session 与 image-offload 插件记录卸载、重新派生和重试；重复 occurrence、最旧前缀、已卸载不重读、缺图/格式错误和取消路径。旧嵌套 tool-result 超限明确失败，锁定 Harness 不支持该结构的自动卸载。
- AC-P1、AC-P2、AC-P3：能力协商，真实 pi-ai parser、function 工具续轮、终结响应独有密文保存，真实 BlockAssembler + JSON 持久化往返，账户/内容变化丢弃旧加密回放。
- AC-P4、AC-P5：真实 FastAPI/schema/治理/SDK 与流式/非流式终态矩阵；缓存用量、未知用量、EOF、关闭前未启动、取消、未知事件/重复序号/大小限制及关闭供应商；SDK 解析前原始响应总量限制有实际 AsyncByteStream 回归。

HTTP 组合测试通过真实 Desktop serializer → loopback credential broker → Bisheng FastAPI/schema/service → 实际 OpenAI SDK；身份存储、配额存储和供应商 HTTP 为隔离替身。四次生成均完成结算。此层验证不等于真实供应商深度生效或生产配额验收。

## 未执行的验收

未提交、推送、部署或更新已安装应用。未验证真实供应商、Gateway/Sub2API 转发、安装包界面/重启、Windows 或 DM8；不保证缓存命中。依赖复用锁定 pi-ai 0.87.1，完整 Desktop 回归包含现有分发闭包检查，但不是原生安装包运行验证。

## 实际偏差记录

暂无推翻已确认设计的偏差。管理员声明接入已有高级参数编辑器；没有新增页面或数据库字段。旧嵌套工具图片恢复受锁定 Harness 限制，已采取显式不可恢复错误，避免无限重试。未完成的安装包、真实供应商或生产验收见上文，不能以本地组合测试替代。
