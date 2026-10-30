# 部署脚本验证记录

日期：2026-10-29；分支 `codex/compose-install`，基线 `feat/3.0.0@3eb8f153be`。

| 验证 | 结果 |
| --- | --- |
| `/bin/bash docker/test-install.sh` | 12 项通过；Bash 3.2 + 系统 awk，Docker 命令录制，阻断宿主机 Python。覆盖默认原样复制、保留旧配置、pull 失败中止、Gateway 文件路径强制要求、缓存 license 不绕过、参数/凭据/转发、重复执行、关闭 profile 和两种 Compose 入口。 |
| 既有 `test/tool/test_work_knowledge_deploy.py` | 隔离 conftest 执行，23 项通过。原更新、预览、失败中止和服务范围保持。本轮使用 `-p no:cacheprovider` 重跑，无缓存写入警告。 |
| 直接复制模板后真实 Compose 展开 | 不经过安装脚本：默认 13 服务、app-runtime 17 服务；所有镜像地址为 cr.dataelem.com，MinIO/后端/Milvus 凭据一致，主网络实际名 bisheng-network、沙箱网 bisheng-sandbox。 |
| Gateway profile 与依赖链 | 主 Compose 的 gateway profile 为 15 服务（包含 gateway-db-init）；叠加 app-runtime 为 19 服务。初始化成功依赖、Gateway 无宿主端口、HMAC 一致与独立数据库密码通过检查。 |
| Gateway 配置生成/关闭 | 真实 Compose 校验通过；关闭恢复 13 服务和直接转发。显式使用多个 --profile 时应列出所有所需 profile；本机 Compose 的命令行 profile 会覆盖 COMPOSE_PROFILES。 |
| 原应用运行时静态契约 | 全部通过，默认/app-runtime 的 13/17 服务计数、变量读取契约和隔离网络保持。主网络仍用逻辑键 default，实际名称已显式指定。 |
| 真实 Nginx 配置 | 本地已有 nginx:stable-bookworm，在无网络、无端口的临时容器中分别验证直连和生成的 Gateway 配置，nginx -t 均通过。 |
| 真实 MySQL 初始化 | 本地已有 mysql:8.0；临时无网络、无端口、tmpfs 数据。新 init.sh 连续执行两次，六张表存在；含单引号/反斜杠/美元符号的测试密码能够通过专用账号认证；空密码会拒绝。测试后删除容器。 |
| Shell 语法、YAML、diff、architecture guard | 通过；安装器不使用宿主机 Python/jq。开发/CI 的原静态契约检查仍可使用 Python。 |

## 166 空数据目录实际部署

详见 [部署记录](deployment-166.md)，以及 `evidence/runtime-checks.json`。基础
13 个服务完成首次部署，12 个常驻容器运行、OpenFGA 迁移以 0 退出。前端、API、
数据库/对象与向量存储、首次注册登录、两副本非 root 沙箱执行均已实测通过。
基础阶段未提供 license 文件，按要求跳过。随后使用用户提供的文件启用 Gateway，
有效 pro 授权、Nginx 转发、商业版标识、专用数据库和 HMAC 对照均已实测通过，
详见 [Gateway 实测](gateway-166.md)。VibeApp 的 app-runtime profile 未启用。

镜像已使用 166 的 CR 认证重新核对：基础默认地址全部 200，当前为 AMD64。
沙箱使用用户给定 `feat_3.0.0`。默认 VibeApp 的 CR :v3.0.0 及 socket-proxy 地址
返回 404；旧 Docker Hub 测试版本七个毕昇镜像族的 14 个 AMD64/ARM64 tag 均 200，
socket-proxy 上游有双架构。详见 [镜像核对](vibe-image-audit.md)。

镜像获取存在环境限制：普通 Docker 拉取遇到 TLS 握手超时及异常慢速，已通过相同
镜像内容的 SHA 校验缓存预载继续，之后原安装入口 config/pull/up 返回 0。
这不是无缓存公网拉取全程通过的证明；具体身份与传输边界记录在部署文档中。

仍未验证：第三方 SSO 登录、Gateway 完整 WebSocket/SSE 业务、VibeApp 发布全链路、ARM 整套运行以及
需要外部模型/解析服务的业务流程。该轮验收未构建或发布镜像，代码当时尚未提交、推送；仅部署了用户
授权的 166 新测试目录，主工作区和原 Office 容器保持不变。

## 2026-10-30 VibeApp 双仓库 CI/CD

- actionlint v1.7.7 校验 runtime-images.yml、app-runtime-quality.yml 通过；
  Shell 语法、Ruff check/format、diff 和 architecture guard 通过。
- 镜像发布相关 50 项测试通过（新 CR 同步 8 项、既有交付/库存 42 项）。
  使用 Python 3.11；既有 SQLite 两个本机 HTTP 测试需沙箱外临时端口权限。
- 新测试用 Docker 命令替身验证 AMD64/ARM64、已有 tag、认证含混错误、push 失败、
  源码版本不匹配及未发布来源；并用真实库存/应用清单工具生成 CR 双架构清单。
- 未实际触发 GitHub Actions、构建发布镜像或向仓库写入；历史缺失的 CR tag 没有
  被本次代码修改自动补齐。详见 [触发与发布流程](runtime-image-cicd.md)。
