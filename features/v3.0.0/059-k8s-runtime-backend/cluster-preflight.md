# 189 K8s只读盘点（2026-10-21）

## 实测事实

| 项目 | 结果 |
| --- | --- |
| 主机 | 192.168.106.189，用户指定的专用K8s验收环境 |
| Kubernetes client/server | v1.28.15 / v1.28.15 |
| 节点 | binfeng-k8s-node189，Ready，control-plane/worker，amd64，无taint |
| OS/内核 | CentOS7，3.10.0-1160.119.1.el7.x86_64 |
| CRI | docker://24.0.9 |
| 节点可分配资源 | cpu7600m；memory63656577179（kubectl原始Quantity） |
| CNI | calico-node与calico-kube-controllers运行；未执行隔离效果探测 |
| StorageClass/PV/CSIDriver | 均为空 |
| RuntimeClass/ResourceQuota/NetworkPolicy | 均为空 |
| 工作负载 | 仅9个kube-system Pod；无业务工作负载 |
| 命名空间 | default、kube-node-lease、kube-public、kube-system、kubekey-system |

命令：kubectl version -o json；get nodes、storageclass、pv、csidriver、runtimeclass、resourcequota -A、namespace、pods -A、networkpolicy -A。未读取kubeconfig/Secret内容，报告不包含认证凭据。

## 对后续验收的影响

1. 持久数据需要先明确供应方式。可以为本套件预置有节点绑定的专用本地卷；不能假定已有动态CSI，也不能宣称本地卷可跨节点故障迁移。
2. 镜像需验证冻结引用能被该Docker CRI实际识别；准备机下载和节点导入并非全部前置。
3. 需要在本套件资源上实测网络允许/拒绝、准入和RBAC。未安装RuntimeClass仅能验证默认隔离及不可用档位的明确回退，不能宣称gVisor/Kata已运行。
4. 单节点无法证明跨节点重调度/物理节点故障切换；该部分必须列为环境限制而非通过。
5. 截至本报告，没有创建Namespace、PV/PVC、Pod/Job或修改节点配置，没有进行任何应用部署。

## 设计核对资料

- [K8s initContainer](https://kubernetes.io/docs/concepts/workloads/pods/init-containers/)支持顺序初始化和卷内文件交接；具体材料投递与授权要另行设计。
- [emptyDir](https://kubernetes.io/docs/concepts/storage/volumes/#emptydir)随Pod回收，可重建代码/依赖缓存与持久数据库必须分开。
- [卷访问模式](https://kubernetes.io/docs/concepts/storage/persistent-volumes/#access-modes)中RWO仍允许同节点多Pod，不能作为单写证明；RWOP有CSI前置，本环境没有CSI。
- [Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/)用于核对工作负载准入；RBAC单独不能表达所有Pod字段限制。
- [BuildKit rootless前置](https://github.com/moby/buildkit/blob/master/docs/rootless.md)用于后续兼容构建器选型，本次没有执行构建器。
