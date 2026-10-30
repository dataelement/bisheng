# VibeApp 镜像架构与发布核对

日期：2026-10-29；来源是 CR 已认证 manifest/config 查询，以及 Docker Hub 匿名
registry manifest/config 查询。不是仅根据 CI 文件推断镜像已发布。原始结果见同目录
`image-audit.json`。166 到 Docker Hub 请求失败；公开 Hub 结果从开发机读取。

| 组件 | Docker Hub 已确认版本 | AMD64 | ARM64 | 默认 CR 地址 |
| --- | --- | --- | --- | --- |
| runtime-manager / egress-proxy / Docker 数据 helper | bisheng-runtime-manager:v3.0.0-test-vibe-{arch} | 200 | 200 | :v3.0.0 返回 404 |
| app-proxy | bisheng-app-proxy:v3.0.0-test-vibe-{arch} | 200 | 200 | :v3.0.0 返回 404 |
| Python runtime + preparer | bisheng-app-python / bisheng-app-python-preparer:v3.0.0-test-vibe-{arch} | 均 200 | 均 200 | :v3.0.0 均 404 |
| Node runtime + preparer | bisheng-app-node / bisheng-app-node-preparer:v3.0.0-test-vibe-{arch} | 均 200 | 均 200 | :v3.0.0 均 404 |
| Static runtime | bisheng-app-static:v3.0.0-test-vibe-{arch} | 200 | 200 | :v3.0.0 返回 404 |
| Docker socket proxy | tecnativa/docker-socket-proxy:0.3.0，多架构 index | 有 | 有 | :0.3.0 返回 404 |

上表七个毕昇镜像族对应 14 个原生架构 tag。`{arch}` 分别替换为 `amd64`、`arm64`。
旧测试发行的源码为 `755d4456e5`，不是当前 release-line 最新源码；不能把它们直接
当作当前版本交付物。当前默认 CR 地址尚未同步/发布，因此启用 app-runtime profile
仍会在拉取阶段停止，不回退为旧版，也不自动构建。

当前构建流程还包括 `bisheng-runtime-helper` 和 `bisheng-runtime-assembler`（新增交付/
K8s 工具链）；其 CR :v3.0.0 返回 404，公开 Hub 对已查询标签返回 401，不能据此声称
已公开发布或双架构齐全。普通 Docker 数据 helper 仍复用 manager 镜像；不要将这些
不同角色混为同一个组件。

代码依据：`.github/workflows/runtime-images.yml` 的原生 amd64/arm64 matrix 与
`scripts/build_runtime_images.sh` 的九镜像清单；旧测试发行记录见 F086 的
`e2e-evidence/2026-10-21-ci-release/README.md`。发布当前代码还须真正执行并通过
双原生构建、推送、生成 profile 目录并同步目标仓库；本次没有触发任何发行/推送。
