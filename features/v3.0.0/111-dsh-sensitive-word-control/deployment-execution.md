# F111 work120 整合与109 DSH交付执行记录

更新：2026-10-24。用户已明确授权合入最新`feat/bisheng-work-120-main`、推送、Drone构建并部署109专用DSH13001，及启动当前客户端分支联调；其他部署环境不可变更。本文不保存密码、Token、HMAC或License值。

## 已核事实

- B远端target：`858f76605ca81f0cef36f42841414b797a432fac`；原目标worktree有他人未跟踪review文档，保留。新隔离集成树：`/Users/zhangguoqing/.codex/worktrees/f111-work120-delivery/bisheng`。
- B源F111基线`2e6b5ae0`有目标尚未包含的provider兼容修复，须按真实历史合并保留；source敏感词实现提交3420114d0已形成，组合候选继续修复后才合并提交。
- 组合迁移原图两个head，T176已将未发布F111接续f062_credit_multiplier，持久保护已发布积分revision哈希，普通迁移回归37PASS。109当前实际head为`work110_dsh_local_sessions`，尚未应用F111。
- 109目标Compose项目：`dsh-bisheng`，文件`/opt/server/dsh/bisheng/docker-compose.yml`，目标服务`backend`/`backend_worker`/`frontend`，公开13001，backend仅本机17860。Gateway项目`dsh-gateway`，文件`/opt/server/dsh/bisheng-gateway/docker-compose.yml`，目标服务`gateway`，仅本机18098。
- 109Gateway实际外部配置`/opt/server/dsh/bisheng-gateway/application.yml`覆盖jar路由；现仅WebSocket与带CacheRequestBody的HTTP通配路由。须最小加入两精确DSH POST路由并保留其余配置。
- 109实际backend：DSH开启、单租户、签名头X-Signature、共享HMAC未配置；Gateway已有共享HMAC。部署时复用其现有值给backend，密钥不输出/不入Git。Gateway当前未配content-safety和正response-timeout，启用前需明确部署读取预算。
- G `origin/main=v1.8.0=2995df6f`与109现有remove-dsh-seat源码树一致；G无同名work120分支。交付将建立同名DSH集成分支与唯一新DSH专用tag。
- Gateway Drone只由v* tag构建；普通tag会自动部署115。必须使用现有`v*-dsh-*`排除模式、验证115步骤skip，再仅更新109。

## 尚未执行

最终合并提交/远端推送、CI镜像digest、迁移/配置修改/服务更新、平台登录与客户端联调仍待实际执行。B/G/D源提交分别3420114d0/108eb5c8/6c84d46；Gateway审查确证同消息跨part漏检，T185测试51项其中19RED，T186修复进行中，发布暂缓。Desktop当前分支正式npm run build通过，尚未启动。原DM8/完整E2E/容量待验与既有前端门禁失败保留；不修改其他环境，不用License绕过来求绿。

## 部署前备份（已执行）

仅检查dsh-bisheng/dsh-gateway项目标签后，在109 `/opt/server/dsh/backups/f111-20261024-predeploy` 建立700目录、600文件：configuration.tgz（7295字节）、镜像引用与ID、专用两库single-transaction dump（28313708字节）及SHA256SUMS。两个实际库是 `dsh_test_work110_main_20261020` 和 `bisheng_gateway`，没有备份/修改其他部署库。备份保留于远端私有目录，不将配置、凭据或业务数据下载入Git。命令exit0。运行服务尚未变更。

实际13001 Nginx：/api/v1/dsh模型入口经过gateway:8080；旧/api/dsh登录兼容入口直连backend:7860，不能误将该登录兼容规则视为模型绕过路径。Gateway自身仅loopback18098暴露。当前平台页面为登录页，无现成已登录会话；已向用户询问验收租户/平台账号，等待答复，不将root机器凭据猜作平台密码。

## 最终源码与发布准备

Gateway修复后最终commit `faa6463b14cc908e6e507241a9d280efb040e80e`，唯一新DSH标签 `v1.8.0-dsh-f111-20261024-faa6463b`；882项主独立回归及第二独立交叉审（60配对+2100语义样本）通过。该ref命中现有115排除规则；实际远端refs/Drone115步骤状态仍以随后读回为准。B远端刷新仍858f766，目标无并行推进。

用户提供的测试账号已真实RSA登录并GET user/info读回成功；临时会话仅本机0600文件，不保存密码到仓库。待部署后使用真实PKCE客户端联调。
