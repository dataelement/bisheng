# BiSheng 标准 Helm

唯一父 Chart 为 [`bisheng/`](./bisheng/)，完整教程见 [Chart README](./bisheng/README.md)。
运行控制面唯一源码在 `deploy/kubernetes/app-runtime`，代码沙箱唯一源码在 `docker/helm/bisheng-sandbox`；父 Chart 以固定版本本地依赖打包，避免复制后漂移。

当前是 **3.1.0-beta1 源码改造**，尚未构建本次 Backend/Runtime Manager 镜像，未在新集群验收。不能把已有 3.0.0 镜像配到新 Chart 后宣称可安装。正式发布流程须提供同一版本镜像清单、真实 digest 和官方双架构运行目录，再运行 `scripts/package_helm.py`。

本目录不依赖私有 `k8s-product` 仓库，不包含任何客户集群地址或凭据，不安装 StorageClass/CSI，也不格式化节点磁盘。
