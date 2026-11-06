# F088 独立设计审查

日期：2026-10-22。审查者：独立 agent `review_error_contract_design`。结论：**NEEDS_FIX**。

审查范围：spec/design/tasks/discovery/候选清单、SDD design 清单、release-contract、constitution；静态核对两端请求拦截器、React Query 4.44.0 查询工厂与配置回归、保存/刷新/发布链、登录和技能导入的实际调用。未改产品代码、安装依赖或重跑测试。主 agent 随后核读关键证据，确认下列问题应在设计确认前解决。

## 1. 高：分批切换缺少明确兼容协议

位置：[design.md:42](./design.md#决策-3分批迁移最终取消业务包装层吞错)。当前方案先标准化底层再逐批迁移，但仅保留旧包装层无法保护字段与 resolve/reject 同时变化的活跃链路。

- `src/frontend/platform/src/pages/LoginPage/login.tsx:185` 仍依赖数字 `error.code === 10601`。新模型的 code 只用于 transport 字符串；若先切底层，密码过期重置分支失效。
- `src/frontend/client/src/api/skillCenter.ts:121` 将 11053 恢复为“尚未导入”。底层先 reject 会使恢复分支不可达，`src/frontend/client/src/components/Skills/SkillUploadDialog.tsx:126` 在创建前的检查中退出。
- 同上传页第 73 行通过 `instanceof SkillRequestError` 及旧字段识别重名覆盖。新模型先切换而未同步转换时，该分支失效。

影响：违反 AC-14、AC-20；文档中的“逐批”不能保证每批业务可用。

建议：明确入口切换与哪些完整调用链必须同批迁移，或者给出临时按请求切换/适配合同；列出密码过期、未导入、新建和重名覆盖的兼容测试。不能以候选引用清单替代该切换规则。

## 2. 中：解码二进制错误后缺少传入共同模型的通道

位置：design.md 第 99 行的 normalizeApiError 接口、第 132 行的二进制处理约定。

触发：HTTP 错误携带 JSON Blob/ArrayBuffer。设计要求共同包不读取二进制、原 response/cause 保留，同时提取业务码和附加信息；目前接口只有 cause、message、response，没有独立的已解码 envelope 输入。

影响：改写 response.data 会损坏原始证据，改用解析结果作为 cause 又丢失原异常；当前合同不足以同时满足这些要求。`src/frontend/client/src/api/messageExport.ts:89` 已有实际本地解码路径，不能把二进制错误视为没有调用方的假设分支。

建议：增加独立解析结果输入，明确其与原 cause/response 的提取优先级。验证 HTTP 200 及非 2xx 二进制错误，断言业务码、附加信息、原异常、原 response 和原二进制引用同时保留。

## 其他结论与限制

- React Query v4 的 refetch/mutateAsync、失败 null 缓存及既有离线配置的处理方向合理，未发现 constitution 冲突。
- 这是设计审查，不代表实现、全量活跃调用审计或回归测试已完成。
- 先前 design-review.md 是作者清单自审；本独立审查发现新增缺口，因此当前不得以该自审 LGTM 视为设计可直接确认。
- 本轮仅记录问题，未修改已提出的设计方案；后续修订需逐项标明处置并保持 spec 不变。
