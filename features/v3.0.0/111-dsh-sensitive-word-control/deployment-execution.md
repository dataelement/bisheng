# F111 work120 整合与109 DSH交付执行记录

更新：2026-10-24。用户已明确授权合入最新`feat/bisheng-work-120-main`、推送、Drone构建并部署109专用DSH13001，及启动当前客户端分支联调；其他部署环境不可变更。本文不保存密码、Token、HMAC或License值。

## 已核事实

- B远端target：`858f76605ca81f0cef36f42841414b797a432fac`；原目标worktree有他人未跟踪review文档，保留。新隔离集成树：`/Users/zhangguoqing/.codex/worktrees/f111-work120-delivery/bisheng`。
- B源F111基线`2e6b5ae0`有目标尚未包含的provider兼容修复，须按真实历史合并保留；source现有敏感词实现尚待形成提交。
- 组合迁移真实图为两head，必须在发布前修复。109当前实际head为`work110_dsh_local_sessions`，尚未应用F111。
- 109目标Compose项目：`dsh-bisheng`，文件`/opt/server/dsh/bisheng/docker-compose.yml`，目标服务`backend`/`backend_worker`/`frontend`，公开13001，backend仅本机17860。Gateway项目`dsh-gateway`，文件`/opt/server/dsh/bisheng-gateway/docker-compose.yml`，目标服务`gateway`，仅本机18098。
- 109Gateway实际外部配置`/opt/server/dsh/bisheng-gateway/application.yml`覆盖jar路由；现仅WebSocket与带CacheRequestBody的HTTP通配路由。须最小加入两精确DSH POST路由并保留其余配置。
- 109实际backend：DSH开启、单租户、签名头X-Signature、共享HMAC未配置；Gateway已有共享HMAC。部署时复用其现有值给backend，密钥不输出/不入Git。Gateway当前未配content-safety和正response-timeout，启用前需明确部署读取预算。
- G `origin/main=v1.8.0=2995df6f`与109现有remove-dsh-seat源码树一致；G无同名work120分支。交付将建立同名DSH集成分支与唯一新DSH专用tag。
- Gateway Drone只由v* tag构建；普通tag会自动部署115。必须使用现有`v*-dsh-*`排除模式、验证115步骤skip，再仅更新109。

## 尚未执行

源提交/合并/远端推送、构建、镜像digest、远端备份/迁移/配置修改/服务更新、平台登录与客户端联调均待实际执行。当前只读核查不当部署成功。原DM8/完整E2E/容量待验与既有前端门禁失败保留；不修改其他环境，不用License绕过来求绿。
