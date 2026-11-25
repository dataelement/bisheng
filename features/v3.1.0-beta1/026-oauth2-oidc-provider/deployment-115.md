# 115 OAuth2 / OIDC 测试部署（2026-11-25）

## 用户验证入口

- 平台：http://192.168.106.115:3001/
- 管理：用原有全局管理员登录后进入 http://192.168.106.115:3001/sys ，选择 OAuth2 客户端页签。
- Issuer：http://192.168.106.115:3001
- OIDC discovery：http://192.168.106.115:3001/.well-known/openid-configuration
- JWKS：http://192.168.106.115:3001/api/v1/oauth2/jwks
- authorize/token/userinfo/revoke：同 origin 下 `/api/v1/oauth2/{authorize,token,userinfo,revoke}`。

新建客户端时填写实际测试应用的回调地址；public 客户端使用 Authorization Code + PKCE S256，confidential 客户端保存当次显示的 secret。用普通用户走未登录→登录→授权同意/拒绝→应用回调，再检查刷新、撤销。内置 dsh-desktop 保持原默认配置，不用它做破坏性验证。

## 实际交付

- 原始 feature：77f213ac23；修复在独立 fix/026-sso-115 工作树，原始用户工作树未修改。
- Compose 项目 dsh-enterprise，目录 `/opt/server/bisheng-worker/prod/docker`。只切换 backend 和 frontend。
- 后端以实际运行的 image-naming-review-67d885bd36 镜像为基底，仅叠加 23 个 SSO 相关源文件。没有把本地 release 工作树的全部 Python 源码复制到镜像。
- 平台以 115 当前 0a9256a234 源码为基础合入 25 个前端文件的最小增量，使用本工作树的共享包构建；客户端旧静态产物保留。
- 新镜像：dataelement/bisheng-backend:sso-oauth2-20261125（c75b833310707cb8dcd4c1c7b4c42666122c31dd5eed28b4abf0125958775261）；dataelement/bisheng-frontend:sso-oauth2-20261125（4e0ee2eaa0d8843d2d2bac0807e7c9246ec11abc97f08f8a12dde6ddc22f4ded）。
- 新建独立 oauth2_client / oauth2_session / oauth2_refresh_token 三表；仅对这些表 create_all(checkfirst)，不执行全量 Alembic 升级、不改存量账号数据。
- Nginx 新增两个 exact root discovery 代理；API 仍经过项目原 Gateway。

## 验证与限制

- Provider 回归 43 PASS；前端 69 业务用例 + 23 API client 用例 PASS，根 lint/typecheck、i18n 和平台生产构建 PASS。
- 候选镜像真实 main 加载及 6 条健康/协议探针 PASS；切换后 API healthy、0 重启。
- 115 真实 HTTP E2E 6 PASS：public/confidential 管理权限配对、PKCE、授权码、JWKS 实际签名验证、scope、refresh/replay、revoke。所有测试前缀客户端和专用用户/租户已清理。
- 23 个后端文件 SHA256 与 manifest 相同；平台 index SHA256 cd912a77cb1bb7536764c70decf81b99b680b442341ed81a3286892e661703d6；client SHA256 eb6fdeb1a69ce06507d384ffadbaf4805c35a19e383978b8e4ddf37f5b836966，与部署前相同。
- Worker、Gateway、MySQL、Redis、OpenFGA 容器 ID 和镜像未变；最终检查最近30秒无 Traceback。
- 115 HTTP Date 比运行测试的本机快约48秒；最终 JWT 测试采用60秒容差，仍校验签名/issuer/audience/exp/iat。未修改服务器系统时间。外部客户端验签需考虑这一偏差或先校准时钟。
- 实际普通用户 UI 同意/拒绝、管理员三语管理页面、旧 Desktop 客户端完整交互及 DM8 实库并发未宣称验收。既有 /api/oauth2/list 和新版 request-scope/bootstrap 在此旧后端返回404，登录页面使用现有兼容回退。
- 旧 Desktop 页面仍保留确认动作，标准 OAuth 流程支持 require_consent=false；没有把旧 Desktop 自动确认宣称为已交付。

## 回滚

发布目录 `/opt/server/bisheng-worker/releases/sso-oauth2-20261125` 已保留数据库备份（gzip校验通过）、配置、旧镜像和容器信息。敏感文件仅保留服务器私有目录，不入仓库。

```sh
cd /opt/server/bisheng-worker/prod/docker
cp /opt/server/bisheng-worker/releases/sso-oauth2-20261125/backups/compose.env .env
cp /opt/server/bisheng-worker/releases/sso-oauth2-20261125/backups/nginx.default.conf nginx/conf.d/default.conf
docker compose -p dsh-enterprise config --quiet
docker compose -p dsh-enterprise up -d --wait --wait-timeout 180 --no-deps backend frontend
```

回滚保留新增 OAuth 表和用户验证期间的数据，不执行删表或恢复全量数据库；若需数据回退应另行确认影响。完整回滚服务演练未执行。
