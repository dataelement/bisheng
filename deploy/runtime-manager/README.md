# Docker 宿主访问隔离（F054）

这是宿主上的 root oneshot/timer，独立于非 root 的 runtime-manager 容器。需要宿主 Python 3.11 与已安装的 `runtime_manager` 包（含 docker SDK、httpx）、可访问的 Engine API、明确的 iptables 或 nftables 后端；不需要 Docker CLI。**不得将此单元放进 manager 容器运行。**

## 安装顺序

1. 预加载固定 digest 的 Python 运行镜像；canary 只用其标准库，不下载依赖。创建 IPv4 `--internal` bridge 应用网络和受控出口。使用独立构建网络时也列入 `network_names`，每个网络都必须能到达同一受控出口容器。未受保护的默认 bridge 构建会被拒绝。
2. 写 root-only `/etc/bisheng/runtime-host-isolation.json`（下面示例使用文档地址，需替换）：

```json
{
  "node_id": "docker-node-1",
  "network_names": ["bisheng-apps", "bisheng-build"],
  "proxy_container": "bisheng-egress-proxy",
  "canary_image": "dataelement/bisheng-app-python@sha256:<已交付的真实镜像摘要>",
  "host_targets": [["192.0.2.10", 22]],
  "firewall_backend": "iptables",
  "platform_base_url": "http://127.0.0.1"
}
```

`host_targets` 由管理员指定，必须确实监听，且同端口经应用 bridge gateway 可达；例如监听 0.0.0.0 的专用探测服务。canary 对该服务执行 host 允许、应用拒绝的配对检查。服务不监听不能充当隔离证据。镜像必须包含 `python`，使用 rootfs 只读、非 root、无挂载的临时实例；此探测不接触应用 SQLite/PVC。

3. 在宿主执行 `python -m runtime_manager.host_isolation --settings /etc/bisheng/runtime-host-isolation.json --describe`。该命令只读，输出实际 Engine ID、network ID、配置摘要及 descriptor。将完整输出按 node_id 存入 backend 的 `app_runtime.runtime_host_isolation_nodes` 或 `BISHENG_RUNTIME_HOST_ISOLATION_NODES` JSON 映射。网络/出口容器/IP/探测镜像或固定目标改变后重新生成并更新映射。后端旧报告随配置摘要变化立即失效。
4. backend 的 `runtime_service_keys` 增加单独 `roles=["host-isolation"]`、绑定该 node_id 的签名身份。manager 的身份保持 `roles=["manager"]`；两者不能共用 key。写 `/etc/bisheng/runtime-host-isolation.env`，只配置 `HOST_ISOLATION_KEY_ID`、`HOST_ISOLATION_SECRET`、`RTM_DOCKER_HOST`（如 socket proxy HTTP 地址；也可用宿主 socket）。密钥不写进 Git。Compose 已登记 `host-isolation-node-1`；其 secret 对应 `BISHENG_RUNTIME_HOST_ISOLATION_SECRET`，节点描述对应 `BISHENG_RUNTIME_HOST_ISOLATION_NODES`。宿主 `platform_base_url` 使用宿主可达的 nginx/backend 地址，不能使用仅在容器 DNS 内有效的 `backend` 主机名。
5. 配置 manager 的 `RTM_NODE_ID`、`RTM_PLATFORM_BASE_URL`、`RTM_PLATFORM_KEY_ID`、`RTM_PLATFORM_SECRET`，使其可使用已有 v2 内部签名客户端读取宿主证明。legacy 形态也需要这条证明读取配置；不改变 legacy 业务 API。
6. 执行 `bash deploy/runtime-manager/install-host-isolation.sh /opt/bisheng/runtime-manager/.venv/bin/python`。脚本验证包和配置后安装并运行单元；首次失败不会启用 timer。使用 `systemctl status` 和 `journalctl -u bisheng-host-isolation` 定位错误；不得只按进程存活认定隔离成立。

## 行为与恢复

- iptables 使用自有 INPUT/FORWARD 链，parent jump 放在前部；只允许精确 egress IP:3128 的 ORIGINAL TCP 和 ESTABLISHED REPLY，其他应用主动连接丢弃，不放开 backend 附件服务端口。
- nftables 使用自有 `inet bisheng_egress` 的 input/forward hooks。每次先检查完整事务、应用、读取结构，并做真实 allow/deny canary。不同工具版本的 read-back 不匹配会拒绝证明，不降级为只看链存在。
- timer 每 30 秒重新应用自有规则、修复漂移并探测；backend 报告有效期 60 秒，使用接收时刻、递增 revision 和一次性签名 nonce。不由 manager 心跳续期。
- 恢复失败时只停止实际 Engine 上、指定网络内的本模块托管实例；v2 还要求 node 标签匹配。停止后再次读取同一容器 ID 确认。未知停止状态继续按失败处理；不删除容器、卷、SQLite 或其他网络资源。
- 旧 canary 意外残留、宿主同时重启、nft 不同版本规范化和隔离漂移的实际恢复延迟仍需专用 Docker 环境验收；本轮只做规则/报告的定向本地验证，不宣称宿主实测通过。
- 报告失效拒绝新的 prepare/probe/preview/deploy/restore/迁移、执行领取及 ready/route 提交；停止/销毁/清理不因报告过期受阻。K8s 保持 F059 的 CNI 能力证明，不读取 Docker 宿主报告。

## 卸载与升级

升级先安装兼容的 host 工具和配置，再启动新 manager；缺少证明时新版 Docker 启动会明确失败。应用需要的代码包/依赖/离线镜像按原运行方案保留。

卸载先 `systemctl disable --now bisheng-host-isolation.timer`，确认 oneshot 已结束，再显式执行 `python -m runtime_manager.host_isolation --settings /etc/bisheng/runtime-host-isolation.json --remove`；该操作先通过签名报告作废 backend 准入，再确认本模块实例已停止，最后只移除自有 jumps/chains/table；无法作废报告时保留规则并退出失败。最后删除这两个 systemd 单元并 daemon-reload。保留配置与证据供排障；不清应用数据、不清其他服务的防火墙规则。

每个 Docker Engine 只安装一个本单元，使用一个 node_id，并在 network_names 汇总该节点的应用与构建网络。独立 installer 不能共享自有链名。
