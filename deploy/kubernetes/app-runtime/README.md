# BiSheng Kubernetes Runtime 子 Chart

标准平台安装入口及完整参数说明在 [`docker/helm/bisheng`](../../../docker/helm/bisheng/README.md)。此目录是唯一 runtime 子 Chart 源码，父 Chart 固定本地依赖打包；不要复制到另一个私有仓库维护第二套模板。

控制面使用 release namespace，默认不创建/修改共享 Namespace 安全标签；应用/Helper 独占执行 Namespace。资源名带 release/namespace 摘要。独立安装子 Chart 时，运维提供正式镜像 digest、平台 HTTPS/公开 CA、服务身份/issuer Secret、data 验证公钥初始化和实际网络/存储配置；平台父 Chart 已统一装配这些引用。它不会自行部署 Backend 或获得安装者权限。

schema2 `descriptor.json` 是运维配置，Backend 挂同一文件作为期望值，Manager 心跳及新操作绑定该配置。手动诊断结果位于独立 ConfigMap，缺失、失败或老化不构成运行门槛。**没有强制环境验收、24小时有效期或6小时巡检任务。** 原每次应用发布的镜像、依赖、启动、健康检查继续执行。

`services.resources/placement/probes/apiTimeoutSeconds/dnsTimeoutSeconds` 控制服务部署；`execution.helperResources/placement/timeouts/operationTimeoutSeconds` 控制执行；`network` 必须描述实际 CIDR/参与者范围；storage 的 `className` null/空/具体类三态，SQLite 使用有界且已确认锁语义的 ext4/xfs RWO。不是所有 CSI 已验证兼容。

父子共享凭据用 `global.credentials`，内部 Pod 端口为 `global.internalPlatformPort`；独立子 Chart 可保留自己的 services/platform 引用和 `network.platformPodPort`。全局镜像 Registry 不会重写已冻结 catalog 的 runtime/preparer 材料；企业镜像搬迁需对应正式目录 revision。

默认没有诊断 Job。按需启用 `diagnostics.enabled` 获取独立 ledger/report 和 `diagnostic-plan` CM，再由受控运维身份补充真实目标并显式调用 `scripts/verify_k8s_runtime.py`。否定网络测试保留正对照，回收继续严格核对 UID/状态/围栏，不能强删未知写入者。该命令不是 Manager 服务账号的安装职责。

停止/卸载前通过平台正常流程停止应用、确认写入者和备份。执行 namespace、卷、公钥、默认拒绝网络和 fail-closed Webhook 保留；卸载控制面不等于应用或业务数据回滚。无匹配本次源码的正式镜像/catalog 时，仅可做模板检查，不能宣称新集群安装成功。
