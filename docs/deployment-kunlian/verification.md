# Docker 部署手册：验证记录

日期：2026-11-11。范围仅为本目录新增文档与配置参考；未执行部署。

## 已核实

- 当前源码：bisheng `02b22c810d`，Gateway `4e15750f`；tag沿用Drone当前分支规则，部署仓库按用户参考统一为公网 cr.dataelem.com，不代表公网tag已发布。
- 读取用户参考文档；未复制账号密码、License 或真实昆联凭据。
- 读取主 Compose、.env.example、install.sh、后端配置与入口、SSO模型/控制面、Gateway Dockerfile/Drone/SSO校验源码。
- 独立只读核查覆盖 Gateway License、数据库表、秘密格式与注入、路径、Origin及统一编排兼容边界。

## 静态检查

| ID | 方法 | 结果 |
| --- | --- | --- |
| E-001 | 本机 Docker Compose v5.1.2：主文件 + 新 overlay，`config --no-env-resolution --format json` 后断言；不联系 daemon，不启动服务 | PASS，15个启用服务；7组宿主端口均为回环；MySQL及初始化密码、两处OpenFGA URI覆盖正确；3组env_file均指向docker/secrets；Nginx include挂载存在；两沙箱无发布端口。命令退出0 |
| E-002 | Ruby检查Markdown本地链接、行尾空白、代码围栏、YAML重复键；Open3逐段执行 `bash -n` | PASS，8个文件、17个本地链接、3份YAML无重复键，18个Bash块语法通过；命令退出0。仅解析，不执行部署命令 |
| E-003 | 独立部署风险复核 | PASS（文档范围），修正网关退出窗口说明：禁新登录不等于关闭整个Kunlian运行时；补充前端启动前一次性Nginx检查。实际Nginx/协议仍NOT_RUN |

## 公网镜像源修订

用户要求参照 telemetry 部署文档，将部署端镜像统一为 `cr.dataelem.com`。已更新后端、前端、沙箱及Gateway（含ARM64）的公网引用、`.env`示例、登录/拉取/inspect命令；移除内网HTTP仓库与insecure-registry配置步骤。仅修改文档，不更改CI发布目标、不执行镜像同步或部署。公网tag是否已发布、网络可达、权限和digest仍为NOT_RUN。

修订后静态检查PASS（退出0）：四类镜像均使用公网引用；主手册无原内网仓库地址及insecure-registry JSON；18个Bash代码块通过bash -n；17个本地链接有效，行尾空白检查通过。

## 未执行（不以静态检查替代）

| 项目 | 状态 |
| --- | --- |
| 远端镜像存在、CI运行成功、digest和commit对应、目标架构 | NOT_RUN |
| Docker安装与目标服务器Compose启动 | NOT_RUN |
| 实际Nginx配置语法 / 重载、License与SQL / Redis / OpenFGA就绪 | NOT_RUN |
| 真实昆联目录、映射、普通用户SSO和退出 | NOT_RUN |
| 固定V1、Worker A→B同派发ID接管、事务回滚 / 通知丢失下游单次输出 | NOT_RUN |
| 数据备份恢复、回退、DM8与容量 | NOT_RUN |

Docker官方页面访问被工具网络校验拒绝，未尝试绕过；手册保留官方URL供部署人员确认受支持系统。未改变现有特性tasks、TODO、NOT_RUN或现网配置。
