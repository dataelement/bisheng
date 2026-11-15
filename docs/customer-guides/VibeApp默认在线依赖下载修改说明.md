# Vibe App 默认在线依赖下载修改说明

日期：2026-11-11

## 1. 修改目的

标准部署原默认使用离线模式。当 Vibe App 声明的 Python 依赖既不在基础运行环境中，也没有作为离线 wheel 材料导入时，应用会在发布预检阶段失败。

本次将 v3.1.0-beta1 标准 Docker Compose 和 Kubernetes/Helm 部署的默认行为调整为：**允许发布准备阶段联网下载 Python 依赖，主包源为公网 PyPI `https://pypi.org/simple`。** v3.0.0 历史发行标签及其配套部署说明不因本次源码修改而改写。

## 2. 修改项

| 部署形态 | 原默认值 | 新默认值 |
| --- | --- | --- |
| Docker Compose | `BISHENG_RUNTIME_OFFLINE=true` | `BISHENG_RUNTIME_OFFLINE=false` |
| Docker Compose Python 包源 | 空 | `BISHENG_RTM_BUILD_INDEX_URL=https://pypi.org/simple` |
| Vibe Runtime Helm 子 Chart | `offline.enabled: true` | `offline.enabled: false` |
| Vibe Runtime Helm 子 Chart Python 包源 | 空 | `offline.packageIndex: https://pypi.org/simple` |
| BiSheng 标准 Helm values | 离线且包源为空 | 在线且使用公网 PyPI |

`offline` 是历史配置组名。当 `enabled: false` 时，表示允许准备阶段从 `packageIndex` 下载，不表示应用运行容器可以任意访问公网。

## 3. 生效边界

- 仅在 Vibe App 的发布准备阶段下载依赖。应用正式运行阶段不执行 `pip install`。
- Python 依赖仍由应用的 `requirements.txt`、`pyproject.toml` 或 `uv.lock` 声明。应用不得使用 `--index-url`、`--find-links`、VCS URL 或直接下载 URL 绕过平台包源。
- 准备阶段仅下载与目标 Python/CPU 平台兼容的 wheel。只有源码包、需要缺失系统动态库或额外编译工具链的依赖仍会明确失败。
- `BISHENG_RUNTIME_IMAGE_PULL_POLICY=never` 的默认值保持不变。runtime/preparer 镜像仍需预先交付；它与 Python 包下载是两条独立链路。
- Node/npm 包源不在本次修改范围内，继续沿用各部署形态的现有行为；需要固定源时通过 `BISHENG_RTM_BUILD_NPM_REGISTRY` 或 Helm `runtime.offline.npmRegistry` 显式配置。

## 4. Docker Compose 升级方式

已有安装的 `.env` 不会被安装脚本自动覆盖。如需启用新行为，请显式调整：

```dotenv
BISHENG_RUNTIME_OFFLINE=false
BISHENG_RTM_BUILD_INDEX_URL=https://pypi.org/simple
```

然后重建读取这些参数的服务：

```bash
docker compose --profile app-runtime up -d --no-deps --force-recreate \
  backend backend_worker runtime-manager
```

修改只影响后续新建的准备/发布任务；已运行版本不会在原地安装新依赖。

## 5. 网络要求

使用公网 PyPI 时，部署环境必须能解析并通过 HTTPS/443 访问：

- `pypi.org`
- `files.pythonhosted.org`

Docker 形态中，准备容器位于受隔离的 `bisheng-build` 网络，经 `egress-proxy` 按平台下发的包源白名单出站。Kubernetes 形态继续由 NetworkPolicy、Egress 服务和部署描述中的包源限定出站。

生产私有化环境建议将公网 PyPI 替换为经审批、具备缓存和审计能力的企业包镜像。

## 6. 回退到完全离线

Docker Compose：

```dotenv
BISHENG_RUNTIME_OFFLINE=true
```

Helm：

```yaml
runtime:
  offline:
    enabled: true
    packageIndex: ''
```

离线模式下，缺失依赖必须通过已交付的 wheelhouse/npm cache 或应用私有补包提供。
