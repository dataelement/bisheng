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

## 116 真实主流程结果（2026-10-26）

- 修复源码：`df8757ba046f2997df4ec8c9d6e98e69bd44e141`；116 manager 与宿主工具使用同源实现。
- 实际 manager 镜像：`192.168.106.189:5443/vibe-release/bisheng-runtime-manager@sha256:d94d1ca4191ae981a75bd2c2ba7860340c0b5842288efa84b69a58a255ef6681`。以原固定发行镜像为基础，仅覆盖宿主隔离模块；私有测试发行，不能视为正式 Docker Hub CI 发行结果。
- host、manager、app-proxy 访问同一无凭据临时 HTTP canary 均返回 200；canary 已安全删除。宿主隔离周期服务 `Result=success / ExecMainStatus=0`，应用访问宿主发布地址及桥接网关的拒绝校验保留。
- 116 root 每小时的镜像清理会删除私有仓库镜像：仅排除 `192.168.106.189:5443/vibe-release/` 路径，保留其余规则。原配置已在目标主机 root-only 目录备份。
- 116 原 nginx 绑定配置缺少 `/apps/`；补齐至同网络 app-proxy 的反代，`nginx -t` 通过并平滑 reload。既有平台、Gateway API 和工作区映射保留。
- 测试应用 `e2e-vibe-docker-20261025`，ID `c0662e86c4414ff7b4265aff6ffe79cb`；部署 `ea3f7d60bdeb42b39e6e1ad54d7f5e01`，版本 `dbb691b5d9cf4d528933fb3d19decc86`。
- 通过实际 API 登录、上传静态应用包、准备、临时探活、审批实例 407、正式部署及路由访问。已授权专用测试超管通过正式审批 API 处理既有管理员待办；无直接修改审批状态。最终发布 `succeeded`、应用 `online`；入口返回 HTTP 200 且包含此次应用的正文标记。
- 档位 `light`：256 MiB、250 millicores；验证资源档位实际用于此次部署，未声称完成在线档位切换或升级/停止回归。
- 访问地址：[116 测试应用](http://192.168.106.116:3001/apps/e2e-vibe-docker-20261025/)。应用保留在线供查看，仍需正常平台身份授权；登录会话仅在进程内使用，临时发布密钥已回收。

### 临时容量配置及证据边界

经用户明确同意，`RTM_OVERCOMMIT_RATIO` 从 `0.8` 临时升至 `0.95`，保留 `RTM_RESERVE_MB=2048`；最终查询剩余可调度约 3470 MiB。这是预算调整，不代表增加了物理内存。原 Compose 的 0.8 配置保留，临时 override 位于目标主机 `/opt/bisheng-vibe-release/f5db95eca/budget-temporary-116.yml`。

恢复原预算时，在 `/opt/server/bisheng-test` 执行以下命令（不加载临时 override）：

```sh
docker compose -f docker-compose.yml --profile app-runtime up -d --no-deps runtime-manager
```

本次验证仅覆盖上述一个 Docker 静态应用包上线主流程和修复所需定向检查；没有运行全量测试，没有补做 arm64、升级、停止或 K8s 回归。189 此前通过的主流程结果不作为本次 Docker 修复的替代证据。服务器脱敏事件证据保留在 `/opt/server/bisheng-test/bisheng/data/vibe-release-20261025/e2e-vibe-docker-20261025.json`；该目录的其他文件可能含测试账号信息，不纳入代码仓库。
