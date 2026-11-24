# Runner 网络（Linux host owner）

状态：产品对齐后恢复为**不限制内网出站**（与安全加固前沙箱策略一致）。helper 仍负责专用网创建与可选 verify/start。

## 契约

- Runner 可访问公网与内网（含 RFC1918 / 客户内网 DB、pip 镜像等）。
- 不再强制 DNS `223.5.5.5`，不再默认 DROP 私网 / 宿主 LOCAL。
- host root 运维仍拥有 firewall 与专网创建权限；runner 无 NET_ADMIN/NET_RAW。
- 固定专网 `bisheng-runner` / `br-bsrunner` / `172.30.166.0/24`；runner `.11` / `.12`。

## 部署顺序（仅 host root）

1. 停止两个 runner。
2. `RUNNER_INTERNAL_CIDRS=none bash docker/lib/runner-egress.sh plan` 审核（当前 plan 为放行规则）。
3. 同一变量 `... apply`。若曾应用过旧的「禁内网」策略，先 `... rollback` 再 apply（旧 chain 名 `BSRE6_DROP` 与现 `BSRE6_FWD` 不兼容）。
4. `... verify` 后 `... start`。`install.sh` 对 verify 仅警告、不中断安装。

## 与旧版差异

旧版（安全加固）禁止全部非公网、锁定 DNS、禁用任务 IPv6。现版按产品决定撤销上述限制；若客户环境仍需收紧，需另行配置，不在默认路径。
