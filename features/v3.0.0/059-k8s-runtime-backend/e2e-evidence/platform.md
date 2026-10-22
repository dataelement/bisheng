# F059 K8s 平台业务验收（进行中）

结论：**尚未通过完整业务验收**。当前优先189 K8s；arm新增验证暂停。详见[结构化证据](./platform.json)。

| 现场步骤 | 真实结果 | 限制 |
| --- | --- | --- |
| 新Pod模板与创建事务 | k189r5首个prepare Pod已创建、调度并启动storage-guard/transfer | 不代表应用已上线 |
| 准备阶段 | precheck_build/16227，原ValueError遮蔽日志缺口 | 固定容器名单已补；原准备失败不能倒推为成功 |
| 停止与清理 | 同UID kubelet_terminal持久证明；该Pod、Secret、scratch PVC均cleanupcomplete且fresh API缺失 | 只证明该操作已注册资源，不声称全集群未知writer盘点 |
| 材料入口 | 专用TLS代理缺根路径，origin404/backend401；精确补路由后新连接401，平台env200 | 401只证明入口及拒绝，signed transfer待复验 |
| 旧k189r4 | 无持久create receipt，仍保留其操作和PVC | 不凭403日志/404或人工文件追认not_created |

## 当前运行候选

- manager/egress/admission：`d86e66a2d`，固定digest见JSON；backend四文件来自`709821ecb`，其余平台源码保持先前基线。
- Helm升级保持descriptor数据/UID、能力报告、CA、helper及profile revision 2；app-proxy未改。
- `709821ecb`完整amd64九镜像及bundle/SQLite烟测通过；`d86e66a2d`只更改K8s日志目标白名单，原生manager构建/导入烟测及245相关回归通过，不重标helper来源。

待完成：同app明确新attempt、Python完整发布、审批预览、HTTP/WebSocket/SDK/OBO/附件/SQLite，再扩展Node/static/image/source-image及故障升级；不将本地/原生Docker烟测算作K8s业务通过。
