# F086 测试镜像发行与109启动验证

- 测试Tag：`v3.0.0-test-vibe`，提交`755d4456e50c015a3fa88da0c0c35ab53bbd1650`；用户已明确授权更新该测试Tag。此前失败记录保留。
- [Runtime delivery images](https://github.com/dataelement/bisheng/actions/runs/39567381522)：Success，6m25s；两架构各7镜像、原生禁网集成与catalog均通过。[原backend/frontend CI](https://github.com/dataelement/bisheng/actions/runs/39567381486)：Success，7m34s。
- 两个服务索引：`dataelement/bisheng-runtime-manager:v3.0.0-test-vibe`、`dataelement/bisheng-app-proxy:v3.0.0-test-vibe`；amd64和arm64均由原生runner构建。原生运行时/preparer镜像使用`:<release>-<arch>`标签，目录冻结child digest。
- 首轮因runner没有rg失败。755d4456e5仅将两处改用grep -Eqi；本地已验证“标签不存在继续、已存在拒绝、认证错误拒绝”三个分支，shell/YAML检查及2项镜像合同测试通过。
- 109直连Docker Hub超时；使用用户给定代理在准备机下载公开amd64镜像，转存、docker load后以镜像默认CMD启动。未修改daemon代理、未重启既有业务服务。
- 独立内网验证：两个healthz为200；proxy UID10001；manager通过socket proxy读取Engine信息并ping成功；缩小的测试proxy拒绝容器列表403；manager无签名v2控制请求403，旧v1控制请求410，平台不可达时app入口503。两服务均只读rootfs、无host端口、无docker.sock挂载。
- 测试容器、网络、远端目录已回收；原27个业务容器完整ID一致且运行，保留镜像缓存。

## 证据边界

本目录不是完整Feature验收通过声明。109本轮是公开服务镜像启动/访问检查；未重新部署整个平台，未执行新BIGINT迁移、DM8/K8s或完整客户断网新装。GitHub三份artifact的存在和摘要从页面核对，未将ZIP下载/目录导入记为通过；双架构应用包集成由真实CI job执行。

本次Tag不包含工作树中尚未提交的backend多租户启动及BIGINT修复；这些修复的已有证据另见live-validation.md/model-review.md。verify_services.py是通过本机SSH运行的复核脚本，临时服务密钥在运行时随机生成，不包含登录凭据。
