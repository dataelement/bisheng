# BiSheng 标准 Helm

唯一父 Chart 为 [`bisheng/`](./bisheng/)，完整教程见 [Chart README](./bisheng/README.md)。
运行控制面唯一源码在 `deploy/kubernetes/app-runtime`，代码沙箱唯一源码在 `docker/helm/bisheng-sandbox`；父 Chart 以固定版本本地依赖打包，避免复制后漂移。

当前是 **3.1.0-beta1 源码改造**，尚未构建本次 Backend/Runtime Manager 镜像，未在新集群验收。不能把已有 3.0.0 镜像配到新 Chart 后宣称可安装。正式发布流程须提供同一版本镜像清单、真实 digest 和官方双架构运行目录，再运行 `scripts/package_helm.py`。

本目录不依赖私有 `k8s-product` 仓库，不包含任何客户集群地址或凭据，不安装 StorageClass/CSI，也不格式化节点磁盘。

## 凭据密钥环（v3.1.0-beta2）

v3.1.0-beta2 起，所有 backend 镜像进程（含 render-settings 初始化容器）通过 `BS_SECRET_KEYS_FILE` 读取外部密钥环，镜像内不再有默认加密密钥。Chart 把密钥环投影到 `/run/settings-secrets/credential-keys/keys.json`（只读，0400），render-settings 用它把数据库、Redis 密码加密写进生成的 config.yaml，业务进程用它解密。

- **全新安装**：`global.credentials.existingKeyringSecret` 留空，Chart 首次安装时生成 `<release>-credential-keys` Secret（`helm.sh/resource-policy: keep`）。之后升级沿用原 Secret；Secret 丢失时 Chart 拒绝渲染，不静默换钥。请把该 Secret 纳入备份。
- **从更早版本升级**：数据库里已有的密文（如沙箱令牌、组织同步凭据）用旧版内置密钥加密。先用同版本凭据工具以 adopt-key 模式生成密钥环文件，再创建 Secret 并引用它：

```bash
kubectl -n bisheng create secret generic bisheng-credential-keys --from-file=keys.json=/secure/bisheng/keys/keys.json
helm upgrade bisheng docker/helm/bisheng -n bisheng --reuse-values --set global.credentials.existingKeyringSecret=bisheng-credential-keys
```

`config.extraEnv` 与各组件 `extraEnv` 不得覆盖 `config`、`BS_SECRET_KEYS_FILE`、`bisheng_DATABASE_URL`，Chart 会直接报错。轮换密钥、重新加密数据库密文和回滚步骤见 [中间件凭据运维手册](../../docs/中间件凭据运维手册.html)。Secret 的静态加密与 RBAC 由集群策略负责，Base64 不等于加密。
