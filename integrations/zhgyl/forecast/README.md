# 采购需求预测 v0.8.0

2026-11-24：为完整报告30秒目标优化真实原生Skill链路。当前数据、预测API和SQLite历史源仍模拟，专用NL2SQL待接入；解释由真实平台大模型生成。该版本已在 D 测试环境验证。测试记录保存在内部项目档案。

## 执行路径

1. 用户明确确认型号、客户及月份后创建冻结运行。入口不会自动分析。
2. 平台原生任务选中并实际读取 `procurement-forecast-fast` Skill。场景显式绑定专用模型。
3. 原生 API 工具的 `prepare` 内部依序执行预测适配器 `forecast` 和历史适配器 `history`，保留两动作各自回执；API裸0仍走历史分支，预测数量0保持可预测，服务错误及时停止。
4. Agent根据本次完整事实撰写简洁解释，原生工具 `finalize` 检查范围、证据引用、合同目标和不可修改数值。
5. 服务端后台独立读取当前用户的真实任务及工具记录，核验Skill正文和forecast/history/finalize三个动作回执，生成完整HTML/Markdown/JSON。不依赖浏览器继续轮询才写报告。
6. 报告完成后调用原生终止接口停止无用的任务尾部。报告完成与原生任务completed分开；证据保留核验时实际状态及 `completion_gate=all_business_actions_verified`，最终任务通常显示terminated，不能伪称原生任务自然completed。

## 本轮改动

专用原生模型配置禁用冗长推理；Skill正文包含正常执行必需合同，无需重复读参考文件；两次业务工具请求替代三次Agent往返；完整月度数据使用带列名的紧凑数组传输，首回执小于平台截断预览，报告原值不变；每个运行独立锁，避免慢HTTP堵住其他查询；失败及时结束等待。

28秒后台业务预算为页面前置请求和展示留余量，页面从点击起30秒超时并终止本次任务。超时/缺证据不生成已核验报告；单纯及时超时不算性能达标。发布报告时再次检查绝对deadline，避免晚到渲染落盘。正常报告必须在真实测试中完整生成才计成功。

月度预测、量价趋势、交付、客户变化、当前订单、计划市场、物料/客户/月度三维、合同建议及完整导出均保留。合同建议需业务复核。

## 接口接入位置

预测：`FORECAST_API_BASE` → `ForecastGateway`，保留裸0/结构化有效零值/错误的区分。

历史：`FORECAST_HISTORY_URL` → `HttpHistoryAdapter`，替换当前 `MockHistoryAdapter`。正式NL2SQL必须由真实授权服务执行并回传完整记录、查询ID、数据来源和精确范围；不能将当前模拟SQLite统计称为原生NL2SQL。

`POST /api/skill-execute` 接受 `request_json`，其中包含本次run_id/token/action，finalize增加explanation。prepare首receipt中的公共run_id/Skill/CLI摘要适用于两个subactions；各子动作保留自身action及action_sha256。独立核验只读取实际绑定原生工具的返回，不信任提示词/自报完成/客户端转录。旧三动作接口保留；旧 `/api/analyze` 和 `/api/explanation` 仍停用。辅助CLI不参与正常原生执行。

## 验证

`python3 -m unittest discover -q`；87项协议、报告、并发、超时与安全回归检查。真实Skill测试另有独立任务回执及计时记录，本地fixture不能代替性能证据。
