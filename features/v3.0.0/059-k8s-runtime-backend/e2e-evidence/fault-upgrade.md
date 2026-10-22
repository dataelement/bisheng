# F059 故障与升级验收（进行中）

## 109 真实 prepare 取消

固定 runtime 源码 `54b3ea2c1`，专用测试平台与 Node profile revision=1。`e2e-f059-cancel-d109c2` 的真实 npm 根 postinstall 已打印固定 BEGIN 标记；按精确 app/deployment/kind=prepare 查询账本，120 秒内获取仍 running/preparing 的绑定后调用 owner 取消接口。

| 检查 | 实际结果 |
| --- | --- |
| owner cancel / 非 owner、跨租户 cancel | 成功 / 两者精确 16105 |
| 操作终态 | cancelled / operation_cancelled / cleanup complete |
| 发布结果 | 预检失败、无审批和正式版本 |
| 运行写入者清理 | 同一实际 CID 连续两次不存在，剩余该操作容器为 0 |
| 人工强制清理 | 未执行 |

应用、部署、版本、操作和实际 CID 及四份脱敏证据摘要见 [JSON](./fault-upgrade.json)。先前 d109c1 误用 revision=2 被拒绝，保留 setup 失败记录，不能计为取消验证。

## 未完成项

189 初始化失败、取消、未知写入者、响应丢失、manager 重启、迁移失败/快照恢复、升级/卸载保留和最终清理尚未完成。私有故障代理与夹具本地测试只证明工具行为。单节点结果不能代表 NodeLost 跨节点围栏；T070 保持 pending。

## 109 实际迁移基线（尚未v2/恢复）

v1实际发布、独立审批12 executed，generation1/deploy completed与cleanup complete后，owner两次PATCH写入随机哨兵与NULL。每次写前非owner16162、跨租户16101且rows未变；两行及其SHA/随机值SHA已冻结于私有0600证据，完整ID见JSON。旧测试工具误把终态写成approved，曾在任何数据写前拒绝；修正后只对原成功发布接续两行PATCH，没有重复发布。v2失败和恢复仍待执行，不能把准备或本地SQLite repro计为平台故障通过。

189新r2先准备未到创建资源阶段，controller空闲租约已过期导致renew409与terminal fact失败；前端部署最终16227/operation_timeout，但manager op仍running/admitted/cleanup pending。未修改租约、无Pod/PVC；登记T198/T199后正常修复。旧r2 journal与失败记录保留，不原地抹去重跑。

## 189 控制器自然空闲续租复验

e405候选同一Pod/容器/holder经历自然租约过期，精确renew409后fresh claim/renew成功，epoch3→4，descriptor未变。旧已到期操作进入failed/cleanupcomplete且无资源；这不是Pod停止证明。真实业务之后的独立准备失败仍保留在platform证据。

## 189 主安装域卸载前置（静态复核）

在 `6f254f337` 的 Chart 与调用链复核中，primary release 的卸载被旧 r4 未确认创建阻断：应用 `2122578f094b4c5fb19f9669815431f2`、操作 `6031594368584d1090ba7a7a2ca8e2e4` 的 PVC 仍为 Bound，未取得原写入者停止事实。按名字 404 不构成停止证明。

Chart 卸载会删除 admission webhook、服务与 RBAC，以及执行域 NetworkPolicy、Quota、LimitRange；保留 Namespace/PV/PVC 不能替代持续围栏。当前五个业务应用即使全部停用，也不能据此卸载该 primary release。本轮没有执行卸载、移除保护或手工释放账本。

完整卸载验收须使用独立 release/installationId、控制与执行 namespace、受限服务身份、合格 PV 和独立平台配置及逻辑存储域；运行真实 SQLite 应用并确认停止与 cleanup 后，才卸载该独立域。共享 backend 的新应用默认节点及 manager/data RPC 地址是全局配置，不能临时改向新 manager 而影响 primary。仅合成 SQLite/PVC 的 Helm 保留检查最多证明存储保留子合同，不算完整平台卸载通过。

源码锚点：`deploy/kubernetes/app-runtime/templates/admission.yaml`、`network.yaml`、`rbac.yaml`、`storage.yaml`、`services.yaml`；`runtime_delivery_coordinator.py:45`、`runtime_control_client.py:21`、`runtime_data_session_service.py:113`。该项保持待验收，不将静态复核记为真实卸载结果。

## T256/T257 manager独立升级：真实189

2ac固定源码的amd64 manager原生构建及UID10001/禁网/只读导入烟测通过；内网仓库digest `5619057b1c026d9ff545f4090f6c84c9aaef5fc1050604162770c7f4d018830c`、config586bdc40…。首轮私有Git checkout umask077产生700目录/600文件，镜像生成但非root import失败；只正规化固定公开构建源码权限，内容和Git clean保持，R2另用标签/日志/结果。保留bad bd2092…及日志，未改产品Dockerfile绕过。

Helm28只更新images.manager，旧Pod30d08ee0…替换为faa48ee8-fd38-4980-a290-4b44ada8d6b4；五应用PodUID、各容器CID、PVC/PV身份全部未变，egress/admission/app-proxy的Pod与容器未重启。descriptor数据/UID、helper/assembler/profile均不变。receipt SHA `539386dafef972122991013f7b03c0e920be301df794dea3df09ea5136763e5b`，before/after SHAefe107e7…/6e7757c1…；不据此声称切换期间所有HTTP请求连续成功。

自然node heartbeat已ready/controller_epoch22，运行期15必需检查和原始安装报告16项分别通过，bundle/image/source-image三路径true；容量仍6784Mi/3125m/5实例，旧r4failed/cleanup pending及原PVC保持。root首轮核查误要求运行期16而assert失败，实际报告无故障；纠正口径后冻结真实ready文件，不改产品。owner取消、inflight重启/释放及其他故障仍待独立实测。
