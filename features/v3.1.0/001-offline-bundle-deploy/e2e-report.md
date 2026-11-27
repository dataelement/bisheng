# F001 E2E 覆盖报告

日期：2026-11-27。平台：本地 macOS / Python 3.10；Linux amd64/aarch64 安装主机与 Docker 操作用受限模拟器验证，不访问生产环境。HTTP 上传/下载、multipart、真实 tar、逐文件流式 SHA256 和目录拷贝均实际执行。

| AC | 自动覆盖 | 结果 |
| --- | --- | --- |
| AC-01 | 电脑无 Docker 下载；显式指定 arm64，与本机架构无关 | PASS |
| AC-02 | 完整包、分卷全量下载；缺远端分卷不误判结束 | PASS |
| AC-03 | 下载重试跳过已校验文件，交付内容不含下载凭据 | PASS |
| AC-04 | 整目录拷贝，禁止网络安装，分卷不落地合并；重复安装保留密钥，互斥锁阻止并发操作 | PASS（Docker 模拟） |
| AC-05 | Gateway 可选下载，复制后配置，启动顺序与镜像引用 | PASS（Docker 模拟） |
| AC-06 | Compose变量/字面镜像引用，架构不匹配拒绝；真实 Compose 解析当前配置为 gateway:v1.9.3 | PASS（拉取/保存模拟） |
| AC-07 | 下载损坏、拷贝损坏、错版本/架构、重复路径、越界tar和目录锁均拒绝 | PASS |
| AC-08 | PUT 与 REST multipart 上传；嵌套目录正确；上传失败不发布固定版本清单 | PASS（本地 HTTP 仓库） |

验证命令与结果：

- `python3 -m unittest discover -s scripts/tests -p test_offline_deploy.py -v`：15/15 通过。
- `bash scripts/tests/offline-bundle.sh`：原有打包、架构、上传幂等与覆盖拒绝、通知回归通过。
- `bash scripts/tests/compose/test-install.sh`：23/23 通过。
- `docker compose --env-file docker/.env.example -f docker/docker-compose.yml --profile gateway config --format json`：实际 CLI 解析通过。
- 所有变更 shell / 内嵌 Python 语法、三个 CI YAML、arch-guard、八列 QA 主表与文档命令检查通过；`git diff --check` 通过。

## 尚需实机验收

- [ ] 实际 CI 拉取并保存两个目标架构的全部发行镜像（含 Compose 指定 Gateway），向真实 Nexus 发布新版本。
- [ ] 使用只读账号在真实用户电脑下载、拷贝到禁止外网的 Linux 服务器。
- [ ] 验证实际 Docker load、全套服务健康、数据库初始化、license 授权及平台登录/WebSocket。
- [ ] 根据实际需求另行交付模型、文档服务及 Vibe App 的额外运行镜像/依赖材料。

自动化范围内 PASS；整套发行与实机断网部署验收为 PARTIAL，未宣称已发布可下载产物或已完成生产验收。
