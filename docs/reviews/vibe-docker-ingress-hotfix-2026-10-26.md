# Docker 控制入口热修评审

实测根因：116 host→同一无凭据HTTP canary=200，manager/entry→canary=ConnectTimeout，主流程在precheck_probe失败。修复仅恢复受信控制入口，按 SDD Guide §1 hotfix 处理，不改变已确认发布/隔离合同。

| 维度 | 结果 |
|---|---|
| 边界 | 容器名称、运行状态、标签、实际网络、源地址和所属子网校验；未知/停止/应用主体拒绝 |
| 权限 | 只增加精确受信源到应用子网的FORWARD TCP；无INPUT放行、无应用源任意出口 |
| 并发 | 既有签名descriptor与60秒独立报告围栏；地址变更fail closed，同地址受信服务合法重建可恢复 |
| 信息泄漏 | 不新增凭据、响应或日志内容；canary不携带应用数据 |
| 定向测试 | 宿主隔离模块26 passed；iptables/nft规则范围、反向拒绝、动态发现和既有围栏；未跑全量 |
| 风格 | Ruff及定向架构守卫、diff check |
| 文档 | F054设计和Docker宿主安装说明同步；需更新宿主工具与manager，并重生成节点绑定 |

结论 PASS；真实116应用重试及allow/deny实证另行记录，不以单测代替。
