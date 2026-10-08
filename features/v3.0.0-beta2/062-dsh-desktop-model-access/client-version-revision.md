# 登录会话客户端版本修复（2026-09-20）

用户已批准：客户端上传实际桌面应用版本，Gateway 接收并保存，同步公开接口文档；DSH 尚未正式发布，不实现对旧 Gateway 的未知字段兼容重试。

## 需求与验收

- 新登录会话展示发起登录时 DSH Desktop 的应用版本。
- 版本缺省时保存 NULL，历史会话继续显示 —；不补造数据、不影响登录。
- 版本不参与 License、席位、额度、身份判断或版本准入；Token 刷新保留登录时记录的版本。
- 不改会话管理界面和毕昇 Python API；复用已有 client_version 字段，不新增表结构或迁移。

## 实现与契约

Electron `app.getVersion()` → 现有 Broker 返回的 Harness 子进程环境 `DSH_DESKTOP_VERSION` → enterprise 插件 → `POST /api/dsh/authorizations.client_version` → Redis 授权事务 → Token 交换 → `gt_dsh_session.client_version` → 既有会话查询及展示。

环境字段由应用内部设置，无需管理员配置。请求字段可缺省/null，非空字符串限制为 1～64 个版本标识 ASCII 字符（首字母/数字，后续字母/数字和 . _ + -），以兼容两种数据库现有 VARCHAR(64)。字段规则详见 client-api.md §4.3。

公开响应结构与 contract_version=0.5.0 不变；本次不引入新的协议版本校验、网络错误重试或旧 Gateway 回退。联调时先更新 Gateway 再更新客户端；回滚时也应配套回滚。历史测试会话不用清退，显示版本需在新客户端重新登录。

## 实施与验证

- [x] Gateway 授权字段、Redis 序列化和会话入库传递。
- [x] Desktop 主进程版本经现有子进程环境传递，登录请求携带字段。
- [x] 同步客户端 Mock 和公开接口说明。
- [x] 针对性回归与静态检查；真实环境部署另行执行。

## 本地验证结果

- Desktop：enterprise-controller、enterprise-credential-broker、enterprise-contract 共 **11 项通过**；TypeScript typecheck 通过。HTTP Mock 登录验证版本由进程环境传至授权事务及会话，另覆盖未提供版本时的登录。
- Gateway：客户端版本、授权、地址配置、换证契约、SQL 可移植性专项共 **25 项通过、1 项跳过**。覆盖可选字段、长度/字符/类型约束、授权 JSON 序列化以及真实 Token 服务将版本交给会话仓储；复用既有会话 Mapper 和查询响应字段。
- 本地 Docker 未运行，真实 SQL 交换/刷新测试按其环境条件跳过；没有据此声称实测数据库或 109 环境。
- 三仓 `git diff --check` 通过。本修订不包含线上部署；原生桌面端和管理页真实联调需两端更新后重新登录。
