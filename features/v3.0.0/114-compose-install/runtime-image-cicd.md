# VibeApp 镜像 CI/CD

2026-10-30，分支 `codex/compose-install`。本次修改仅交付代码，没有触发远端工作流、
推送镜像或补齐历史版本。2026-10-29 的仓库缺失记录仍是当时的实际结果。

## 触发条件

发布入口：`.github/workflows/runtime-images.yml`，名称 Runtime delivery images。

| 事件 | 行为 |
| --- | --- |
| push Git tag `v*` | 自动发布，包含 `v3.0.0`、`v3.0.0-beta6` 等；使用完整 tag 作为镜像版本 |
| workflow_dispatch | 手动选择代码 ref，必填 `version`，镜像版本使用该输入 |
| 普通分支 push | 不触发该发布工作流 |
| pull_request | 不触发该发布工作流；相关路径由 App Runtime Quality 做校验，不登录仓库或推镜像 |

同一 release 的 tag/手动发布共享并发锁，`cancel-in-progress=false`。
已有版本不得覆盖，改变内容必须使用新版本；普通代码提交不会自动生成新镜像。
本次将 runtime-images.yml、build_runtime_images.sh 和 sync_runtime_images_cr.sh
加入 App Runtime Quality 的 PR 路径过滤，确保这些修改触发现有测试门禁。

## 原生构建与发布顺序

1. 两个原生 job 并行：`ubuntu-22.04` / AMD64，`ubuntu-22.04-arm` / ARM64。
   builder 检查宿主机、Linux Docker Engine 与目标架构一致，不使用 QEMU 作为发布证据。
2. 同时登录 Docker Hub 和 CR，CR 凭据名与 backend 的 `.github/workflows/ci.yml`
   保持一致：`CR_DOCKERHUB_USERNAME`、`CR_DOCKERHUB_TOKEN`；Hub 使用
   `DOCKERHUB_USERNAME`、`DOCKERHUB_TOKEN`。
3. `scripts/build_runtime_images.sh` 在干净 checkout 构建 9 个镜像。先构建 manager、
   proxy、各语言运行/准备镜像，再用本次构建的基镜像构建 helper 和 assembler。
4. 所有镜像通过原生架构和隔离 smoke 后推 Hub，记录镜像 ID、源代码 SHA、
   版本标签、真实仓库 digest；执行已有离线 bundle、复用和 SQLite 集成检查。
5. `scripts/sync_runtime_images_cr.sh` 检查本架构 9 个 CR tag 都不存在，再用 Hub
   验收清单中的本地 image ID 逐个 tag/push 到 CR，不重建、不解析可变来源 tag。
   已有 tag、认证或网络状态不明会停止；push 失败也会停止。
6. 从实际 CR push 后的 Docker metadata 生成 `dist/cr/runtime-images-<arch>.json`。
   CR 和 Hub 使用各自真实 RepoDigest，不直接替换清单内的域名；选取 CR RepoTag
   避免同一个本地镜像的双仓库 tag 导致库存工具判定歧义。
7. 两个原生 job（包含 CR 同步）都成功后，catalog 按 Hub/CR 两个仓库并行工作。
   校验两个架构的 release 和源码 SHA 一致，按冻结 digest 发布四个多架构服务索引；
   最后生成 release 清单与三个语言 profile 的双架构清单。

发布不是跨仓库事务：Hub 的分架构镜像先推送，后续失败时已推镜像不会回滚，
也不允许覆盖重试。失败版本需检查实际状态并使用新 release 重新发布。

## 镜像和 tag

每个仓库都发布以下 9 个镜像的 `:<version>-amd64`、`:<version>-arm64`：

| 镜像名（统一 bisheng- 前缀） | 用途 | 另有 `:<version>` 双架构索引 |
| --- | --- | --- |
| runtime-manager | 编排服务，也用于 egress/admission 角色 | 有 |
| app-proxy | 应用入口 | 有 |
| runtime-helper | K8s 准备/数据辅助工具 | 有 |
| runtime-assembler | OCI 组装工具 | 有 |
| app-python | Python 运行镜像 | 无，由 profile 选择平台 digest |
| app-python-preparer | Python 准备镜像 | 无，由 profile 选择平台 digest |
| app-node | Node 运行镜像 | 无，由 profile 选择平台 digest |
| app-node-preparer | Node/静态资源准备镜像 | 无，由 profile 选择平台 digest |
| app-static | 静态站点运行镜像 | 无，由 profile 选择平台 digest |

例如 release 为 `v3.0.0`：

```text
dataelement/bisheng-runtime-manager:v3.0.0-amd64
dataelement/bisheng-runtime-manager:v3.0.0-arm64
dataelement/bisheng-runtime-manager:v3.0.0
cr.dataelem.com/dataelement/bisheng-runtime-manager:v3.0.0-amd64
cr.dataelem.com/dataelement/bisheng-runtime-manager:v3.0.0-arm64
cr.dataelem.com/dataelement/bisheng-runtime-manager:v3.0.0
```

不发布 latest。其他版本号不会自动填补 `.env.example` 中的 `v3.0.0`，部署时需匹配
实际发布版本。第三方 `tecnativa/docker-socket-proxy` 不属于这 9 个自有构建镜像，
本次流水线没有同步它；原 CR 默认地址是否可用仍需单独准备和核查。

## 交付物

- `runtime-images-amd64`、`runtime-images-arm64` artifact：各包含 Hub 清单与
  `cr/` 子目录下的 CR 清单。
- `runtime-profiles` artifact：保留原 Hub 名称，包含 runtime-release.json、
  runtime-profiles.json、四个服务索引记录。
- `runtime-profiles-cr` artifact：相同类型的 CR 专用交付物，其服务/运行/准备镜像
  均引用 `cr.dataelem.com`。应用 profile 仍需按原流程导入平台，并准备应用自身依赖。

本地验证覆盖新同步脚本的 AMD64/ARM64 正常路径、已有 tag、认证失败、推送失败、
源码 SHA 不匹配和未发布来源，以及真实库存/应用清单工具的 CR 双架构生成。
真实双架构构建与两个远端仓库推送需合入后运行 Actions 验证。
