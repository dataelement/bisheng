# 制造部科室指标分析脚本

- Feature ID: `068-office-metrics-export`
- Status: `implemented-locally`
- Created: `2026-09-29`

本目录保存用户逐项确认后的统计口径及待实施方案。

1. [需求与验收](requirements.md)：组织范围、十三项指标、CSV 交付及异常边界。
2. [实现设计](design.md)：数据来源、精确去重、两级分母和文件结构。
3. [实施任务](tasks.md)：三个依赖明确的任务及共享验证检查点。
4. [验证记录](verification.md)：实际命令、测试结果和未验证边界。

业务需求及实施已在会话中授权；本地实现完成，真实环境对账尚未执行。只读运维工具不修改 release-contract 中既有运行时不变量。
