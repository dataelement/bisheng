# Runner 公网 IPv4 / 内网隔离（Linux host owner）

状态：离线实现，**未完成 Linux live 验证，不得据此宣告网络验收通过**。

## 明确契约与所有权

- 保留公网 IPv4 TCP/UDP，DNS 仅 223.5.5.5:53；禁止全部非公网、宿主本地地址（含公网地址）、部署额外内部公网 CIDR。拒绝 IPv4 非 TCP/UDP（包括隧道协议）。
- 不承诺公网 IPv6：任务 namespace all/default disable_ipv6=1，同时 host IPv6 INPUT/FORWARD 从专用桥全部 DROP；涵盖 ULA/link-local/metadata/mapped IPv6 的禁用路径，必须 live 实证。
- host root 运维所有 firewall 权限；runner 无 NET_ADMIN/NET_RAW，无 Docker socket，不引入 backend Docker SDK。
- 固定专网 bisheng-runner / br-bsrunner / 172.30.166.0/24；runner 两个地址 .11/.12 是安全边界输入，禁止其他 runner 地址。backend/controller 可以双网连接，但 runner NEW 到它们全部拒绝。
- 原 bisheng-sandbox 不再使用。不能把旧网络改 internal=true 当成修复。

## 部署顺序（仅 host root，由部署者执行）

1. 停止两个 runner，确认没有用户代码；核实主机和 Docker 子网不重叠。
2. 审阅 `ip route` 与业务拓扑，将公网地址的内部服务/控制网段写入 `RUNNER_INTERNAL_CIDRS`（空格分隔 IPv4 CIDR）；确实不存在时显式 `none`。host 自身所有 LOCAL 地址动态由 addrtype 阻断。此变量不是 token，不放任何凭据。
3. host 必须已有 iptables/ip6tables、Docker、flock，bridge-nf-call-iptables/ip6tables 均为 1，Docker DOCKER-USER 已存在。helper 不安装包、不改系统 sysctl，不 flush 任何表。
4. `RUNNER_INTERNAL_CIDRS='经审阅CIDR' bash docker/lib/runner-egress.sh plan` 审核生成规则。
5. 同一变量运行 `... apply`。helper 仅创建自己的 chain/jump 和专网，保留 root-only `/var/lib/bisheng-runner-egress` 反向操作 journal。若失败，runner 保持停止；阅读错误与 journal 后运行 `... rollback`，不要直接重新 apply。
6. 使用新 compose 创建/连接 backend、worker 到新网（保留其原有网络），随后运行 `... verify`。Docker 修改规则顺序会令验证失败，必须重新审阅，不允许忽略。
7. `... start` 在 verify 成功后才启动两个 runner；canonical install.sh 非 prepare-only 同样先 verify。runner restart=no 避免 reboot 时先于 host policy 自动启动。host reboot 必须由运维重新验证规则后启动。
8. root 手工 docker start/compose up 可以绕过部署门禁，root 是可信运维边界。不能宣称容器自己能证明 host firewall 正确；不要把标志文件当成这种证明。

## 规则与回滚边界

v4 FORWARD 和 DOCKER-USER 置顶跳转，仅 `-i br-bsrunner -s .11/.12`，INPUT 同样限定来源；controller 自己在桥上的 NEW 不受限制。runner 对入站 controller 已建立连接的 REPLY 允许；不允许任意内部 ORIGINAL established 连接。非公网/hostlocal/额外内部网段先 DROP，再 DNS 例外、其他公网 TCP/UDP 允许。同桥包必须经过 bridge netfilter；不能只验证 DNS 解析失败。

v6 整桥 INPUT/FORWARD DROP；namespace 禁用为第二层。非 IP 二层发送依赖任务 UID 无有效 capabilities 且 Docker cap_drop ALL（只给 supervisor SETUID/SETGID/CHOWN/DAC_OVERRIDE/KILL）；live 检查 task CapEff=0，不能授予 NET_RAW。

journal 只逆序删除本 helper 创建的规则与 chain，不恢复整个防火墙 snapshot、不改默认 policy、不删除网络、不恢复其他服务。必须停 runner 再 rollback；回滚后停机，不能在无策略时恢复 runner。journal 尚在时重新 apply 拒绝，需要运维审阅清理/归档状态，不自动掩盖失败。

## 必测（不能 skip 坏例）

- host controller 到 backend 与 owned exact peer positive control；真实 runner uid .11/.12 到 backend 同桥 IP、其他私网 peer、宿主 gateway、公网宿主地址均 denied；对应 DROP counter 增长。
- metadata/private/reserved/IPv4-mapped IPv6 的离线规则覆盖；live 只使用授权 exact owned endpoints，不探测真实元数据服务。
- 公网 owned control endpoint 经真实 runner 成功；223.5.5.5 DNS 成功、其他 53 denied。
- task IPv6 socket/route 不可用，host ip6tables hook/counter 验证；不能因为目标无 listener 判通过。
- runner HTTP controller response/auth/lease/UID/env/resource/timeout/cleanup/Office 回归。
- verify 对缺 chain/改规则/改顺序/bridge sysctl off/网络不同均失败；未配置 policy 的 installer 不执行 Docker up。
- 两次 apply 幂等；rollback 不触及其他容器或规则；重启/规则reload后的启动门禁。
