# 原生运行与解释合同

价格趋势 previous/current 为 null 时，必须写“缺少观测、无法计算”，不能写价格环比为0、均为0或没有变化。数量为0、缺失单价、不可计算的变化率是不同事实；不得合并成“数量与价格环比均为0”。

## 工具调用

任务提示绑定实际注册的 native_tool_key 与 forecast_execute 操作。只能调用该实际工具，不猜测 tool_type_<group>_<hash>，不动态搜索替代服务。参数为 `{"request_json":"一个JSON对象的序列化字符串"}`；对象字段严格为 run_id、token、action，以及 finalize 时的 explanation。prepare/forecast/history 不提交 explanation、查询范围或文件摘要；服务包装器补充可信的工件摘要后调用同一运行的动作接口。

正常运行读取 SKILL.md 后，调用 prepare → Agent解释 → finalize，共两次原生API请求。prepare内部按原合同执行 forecast/history 两个动作并返回各自原始成功回执；原三步接口保留供兼容检查。本合同用于接口维护，正常执行无需重复读取。失败即停止，不自动重试、递归创建任务、启动 CLI 或网络探测。原生执行不需要代码执行器网络、base-url、解释文件或本地输出文件。若实际工具 schema 与任务提示不一致，报告受阻，不能编造工具或把普通文本当作已调用工具。

平台可能两层封装 API 响应。只按实际字段读取并解析 JSON 数据，保留 run_id、action、state、facts_ref、action_sha256、skill_sha256、cli_sha256 等业务回执原值；原始返回不存在的值不能补填。history 的 facts 是本次业务事实，evidence_refs 是有效证据 ID，suggestion_targets 是可建议合同的固定目标，目标预测证据可能在 evidence_refs 或 prediction_refs。逐项读取完整月度预测、历史 summary/window/monthly、交付与客户统计、当前订单、计划市场、三维汇总，核对需要引用的原始证据；若返回内容截断而无法支撑解释，明确说明受阻。

响应中的工件摘要由服务包装器提供，用于对应候选包版本。摘要不证明 CLI 执行、Skill 已读取或真实数据已接入。最终验收须独立核验本次实际原生 API 工具调用、动作回执与 Skill 读取证据；当前 Agent 不能自报核验成功。

## Agent 解释 JSON

直接把以下六字段解释对象放入 finalize 的 explanation，无需落盘，所有文字须根据本次事实填写：

```json
{
  "headline": "本次主要结论",
  "body": "范围、量价、交付、客户、当前订单、计划市场与三维分析，区分观察和推断",
  "factors": [{"title": "因素或观察", "value": "事实值或观察结论", "detail": "证据口径和限制"}],
  "limitations": ["预测 API、数据和历史源为模拟；真实平台大模型解释仍需业务复核"],
  "influences": [{"title": "因素或观察", "detail": "事实、证据支持的影响及推断限制", "evidence_refs": ["本次有效证据ID"]}],
  "suggestions": [{"spec": "目标规格", "customer": "目标客户", "reason": "结合预测和业务证据解释预排合同理由", "evidence_refs": ["对应目标预测证据ID"]}]
}
```

headline/body 非空字符串；factors 为 title/value/detail 非空字符串对象数组；limitations 为非空字符串数组；influences 为 title/detail 非空字符串及非空 evidence_refs 字符串数组的对象数组。factors、limitations、influences 不能为空，证据有限时写实际观察和信息缺口，不补造影响原因。每项引用 ID 必须属于本次事实且不重复。

suggestions 为 spec/customer/reason 非空字符串及非空 evidence_refs 数组的对象数组，恰好覆盖每个 suggestion_targets 可预测物料／客户组合且不重复；无目标则为空。每项至少引用一个对应目标的预测证据，不能混入其他目标的预测 ID。数量、金额、期间由服务从目标填充，Agent 不提交 quantity/amount/period，不对不可预测项给合同量。

分析覆盖数量与价格趋势、交付履约、客户变化、当前订单、计划市场，以及物料／客户／月份维度。历史总量、上年同月和预测月度量的口径须区分，缺失项说明影响。裸 0 的 API 拒绝原因未披露即未知；历史稀疏仅是观察，计划市场未经验证不得当作确定因果。模拟数据、真实大模型、准确度未验证和业务复核等限制必须保留。

## 当前模拟适配与未来接入

当前链路：真实平台 Agent → 实际读取 Skill → 原生 API 工具 prepare → 按序执行模拟预测 API／模拟历史适配器（保留两动作回执）→ 真实大模型解释 → finalize 校验 → 独立原生核验。history 返回冻结模拟订单 SQLite 的记录与统计，不能称为真实订单或原生 NL2SQL。CLI 仅是离线接口检查辅助，不参与本次真实原生执行。

后续 NL2SQL/sales-db 真实接入需显式提供工具、权限、数据源、真实查询和证据回传合同，再替换历史适配器；不能猜测工具名或把 general-purpose 子代理改称 NL2SQL。保持运行范围、事实字段与证据语义稳定，真实数据接入和部署另行授权验证。此处不表示接入已经实现，也不阻断当前明确标注的模拟运行。

finalize 只校验解释并返回 pending/awaiting_native_verification；服务完成独立原生核验之前不能声称报告完成、构造下载链接或伪造 reports。工具错误与无历史／不可预测分开，停止依赖失败证据的结论；不自动重试或通过其他路径规避核验。

## 业务完成与30秒预算

服务核验当前用户的真实原生任务、Skill正文、绑定API工具及三个成功动作回执后，即完成业务报告；无需等待任务追加摘要。证据保留实际原生状态和 completion_gate=all_business_actions_verified。核验成功后通过原生终止接口停止余下生成，不把 terminated 伪称 native task completed。30秒预算包含取数、真实模型解释、核验与报告生成；超时只报告未完成，不能伪造完整报告。数据表、趋势、交付、客户、三维度和导出无删减。


预测量价仅使用本次独立预测API返回的原值。MAPE等模型质量指标并非预测成立的前置条件：未返回即未提供，不自行补值、推断质量达标或用模拟质量冒充正式评测；已返回的质量字段仍严格核验。正式来源与模拟来源按本次回执标记说明，不自行补充独立业务。
