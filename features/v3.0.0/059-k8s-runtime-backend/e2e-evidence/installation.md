# F059 189 安装验收阶段证据

状态：**T068通过**。固定源码、镜像、资源UID与校验和见 [installation.json](./installation.json)。

候选54b3ea2c1、Helm revision10在189实际完成第五轮15项必需检查及registry-push，正常清理exit0；真实平台公开安装诊断通过。覆盖受限RBAC/exec、PSA、状态来源、同UID删除与binding拒绝、网络隔离、精确镜像启动、材料TLS/HMAC和SQLite锁/fsync。此前失败与其他源码轮次独立保留。

报告过期、CNI身份变化、必需检查失败三组均通过真实发布入口：先确认节点blocked及公开ready=false，提交各自唯一static应用，持久化失败16121/precheck_build、无审批/正式版本/运行操作。每组原样恢复descriptor字符串并验证节点ready，manager Pod UID/containerID/启动时间/restartCount完全不变；没有生成虚假成功报告或延长TTL。

旧失败installer仅按自然到期、同UID及真实停止/绑定拒绝证据清理；固定旧dryRun按四次404与CAS撤销。最终执行namespace无Pod/PVC，canary计划为空。专用registry启用delete经过用户明确授权，原容器及数据保留。

业务发布、应用数据/SDK与故障升级仍由T069/T070单独验收。本节不是整体交付通过；DM8仅静态，单节点不能证明跨节点。

## 业务验收前临时卷池增补

按冻结计划新增scratch-09..40共32个4GiB独占ext4 local PV，实际预分配128GiB；精确NS/nodeUID、原19PV/marker权限及loop前后核对不变。新卷归专用operator管理，Retain，无Helm归属，不重绑旧卷；inventory摘要与新UID见JSON。原preflight卷因既有fsGroup为0:10001/0664，按精确旧UID冻结原状，不改旧权限。该结果不证明宿主重启或跨节点恢复。

后续控制候选0e/Helm11：固定LAN manager manifest b17045eb…，保留当前实际能力报告再升级；四个历史failed draft逐一只读预检后owner DELETE，后续GET16101，无force清理。收据SHA df530fbb693835dfa83604c4adc54b588b2e0e03858bffb34806b87567b93bf7。新业务尚在precheck_build，资源未创建，空闲租约续租409登记T198/T199；该状态不撤销历史T068安装探测证据，但不计T069业务完成。
