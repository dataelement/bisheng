# F059 Docker 与平台回归记录（C 线准备）

## 1. 结论与证据边界

**本地回归与109真实Engine级应用包回归通过；完整平台业务验收仍未完成。** 主agent已在109运行同版原生容器回归，C线自身只提供本地准备。 本文不将 fake Engine、模拟 K8s、SQLite fixture 或跳过用例写成 109/189 部署证明。T067 的完整平台/权限/SDK验收仍待主 agent 串行完成，不能因本报告将其整个任务勾选完成。

共同基线 `c90927b1f4e0388a956d4e300c7951ff7745b1bf`；继承的公共租户修复来自发布线 `9d156f261cc7769fcf75f41caeb104a425308017`，本线只修测试/文档/harness，未修改任何生产权限、审批、状态或执行器业务规则。执行时的测试文件变化见 Git 提交，日志摘要见 [docker-regression.json](./docker-regression.json)。

## 2. 实际执行

| 选择 | 结果 | 证据类别与限制 |
| --- | --- | --- |
| runtime-manager 全部 tests | 967 passed / 10 skipped | 本地；共享 Docker/K8s 执行器、构建、应用包、存储、数据、egress、生命周期；相应 fixture 模拟 Engine/集群 |
| app-proxy 全部 tests | 256 passed | 本地 ASGI/HTTP/WS/路由/身份与拒绝；不是实机 nginx/网络/连接撤权 |
| backend app_runtime＋app_publish 全部 | 1564 passed / 18 skipped | 本地；真实 Python 生产服务逻辑与 SQLite fixture，外部中间件有mock；不证明MySQL/DM8实际迁移 |
| 新harness安全合同＋权限登记＋live收集 | 54 passed / 11 skipped | 54为本地；11含原7项权限集成门及F059 live4项；不得计为业务E2E |
| CLI `--help` | 通过 | 不访问网络、不写任何平台数据 |
| CLI 无 `F059_E2E=1` | 拒绝，未产生journal | opt-in安全检查，不是运行失败掩盖 |
| Ruff＋相对路径arch-guard＋diff --check | 通过 | 无生产代码变化；敏感字段拒绝测试为合成fixture，不包含真实凭据 |

测试命令使用共享 Python3.11；backend 的 `config` 是临时专用测试配置路径，JSON不包含配置内容。原始日志位于本机 `/private/tmp/f059-e2e-*.log`；SHA-256固定内容，后续集成若测试数改变必须重新运行并更新，不能照抄此处数值。

## 3. 发现并修复的过时测试合同

1. 授权对象 picker 已支持 total：原fixture只mock list，遗漏 count，两个测试意外连接真实数据链路。补 count stub并断言 `data/total`，未放宽任何权限。
2. 发布线已注册 linsight_skill：删除该资源“永远未注册”的负例假设，改为正向验证 app 完整 Catalog/registry/picker 与非owner-projection路径；未知类型拒绝用例保留。
3. egress 策略读取必须独立 `roles=("egress",)` 身份；旧fixture无roles。补身份及真实K8s material表schema，保留真实repository投影，不mock为空绕过。
4. 生产固定Pod名在维护多阶段复用但历史不可覆写：bddb1f986 已去掉 operation/kind/name 唯一约束，仅actualUID唯一。模型测试明确assert新合同及旧约束不存在。

同一全量backend选择首次为1519 passed / 18 skipped / 3 failed；修复egress身份/fixture表与模型约束后为1525 passed / 18 skipped。通过数还增加了3个清理安全参数用例，因此不能单凭总数差推断覆盖。更早仅权限定向基线为3 failed / 41 passed / 7 skipped，修复后该组44 passed / 7 skipped。

## 4. 真实 Docker 回归待执行

使用 [e2e-checklist.md](./e2e-checklist.md) 同一CLI和测试数据，`F059_E2E_EXECUTOR=docker`，全部身份及应用仍使用专用 `e2e-f059-` 租户/名字，禁止连接或清理109已有非测试业务服务。

- [ ] v1源码/source-image、v2 bundle、完整image；Python/Node/static真实准备与探活。
- [ ] 平台CLI发布、预检拒绝、单独人工审批、预览隔离、正式入口、版本更新。
- [ ] owner/nonowner/foreign允许与拒绝；日志筛选脱敏；HTTP/WS、SDK/OBO、CONNECT撤权与manager停用投影。
- [ ] SQLite提交行、停用/恢复、容器重建、备份/迁移/恢复、owner删除；backend附件SDK0.1.1上传下载及跨应用拒绝。
- [ ] 离线镜像＋离线依赖＋平台接口分别验证；缺wheel/坏摘要/镜像拉取失败/健康失败保留精确阶段。
- [ ] 原有非测试容器/应用前后清单一致；只回收本次拥有的应用与临时资源。

DM8按既有确认仅模型/DDL规范静态检查；通用SQLAlchemy dm分支编译不等于实际dmPython/DM8迁移测试。189 amd64单节点结果也不能补齐Docker、arm64或跨节点验收。


## 109 真实 Engine 级回归（2026-10-22）

使用专用 `/opt/e2e-f059-docker`、随机测试node/network、原生amd64镜像与真实Docker Engine，运行 `scripts/smoke_runtime_delivery.py`，退出0。Docker Engine测试身份只在本次测试容器挂载socket，不代表运行服务必须拥有该权限；未重启daemon或任何既有服务。

| 实际检查 | 结果 |
| --- | --- |
| Python/Node/static离线准备、真实HTTP、代码v1→v2 | PASS |
| 三语言依赖产物复用 | PASS |
| static前端构建/install hook及源码变更使依赖缓存失效 | PASS |
| CPython原生扩展离线构建、相同包版本改源码仍生成新产物 | PASS |
| SQLite数据保留、容器停启/数据读写 | PASS |
| bundle发布前后镜像集合无新增OCI构建 | PASS |
| 临时容器/网络清理、非测试容器清单前后SHA一致 | PASS |

原始证据在109专用目录，镜像config digest、关键脚本摘要及完整结果收在同名JSON。该工具的artifact port是内存实现，**不覆盖真实backend/MinIO/发布审批/自然人权限/SDK/OBO**，T067保持未完成；不得将其改写为平台全链路通过。

## 5. L1

架构分层 PASS；命名与AC PASS；平台envelope/CSV/WS协议 PASS；数据库 N/A（只更新fixture和约束断言）；前端 N/A；信息泄漏 PASS（安全env、私有journal、无响应体日志）；设计同步 PASS（不改生产接口）。真实验收与SDD汇总文件由主agent合流后更新。

## 109 平台业务增量（54b runtime / 7b 验收同步）

专用 `/opt/e2e-f059-docker-platform`，真实 MySQL/Redis/MinIO/OpenFGA/backend/Celery 与三代理，固定 manager manifest digest `26f61e7b…`；profile revision=1。

- Python、Node、static 的 bundle 均通过两版真实发布、预检、独立审批、预览、入口和停用恢复。Python/Node 的 WebSocket 允许/拒绝配对通过；Python 的 SDK 身份/OBO、真实附件往返、SQLite 查改导出与跨停启保留通过。三组 owner/nonowner/foreign 边界由实际接口校验。
- 运行数据 helper 的 WAL 读问题已修复并在以上 Python 平台路径复验。停止/恢复工具等待精确操作终态后再检查数据，不吞临时维护错误。
- 第四个 source-image 构建完成，但以 `16124 / precheck_probe / startup_exited` 失败；该旧版 Docker 路径是裸 Python 基础镜像，空 requirements 的夹具缺 SDK 物料。T191–T193 补可校验离线 vendor，失败记录保留。
- 完整镜像已另起固定两 digest 的专用批次，尚未计通过。source-image、缺依赖、故障/恢复/删除及最终非测试清单仍待闭合，T067 保持 pending。

固定日志摘要、应用 ID 与步骤见同名 JSON。此处不将成功的代理请求当作宿主防火墙实际阻断证据，也不宣称真实模型正向调用已验证。

完整镜像增量：独立d109image1批次v1/v2两次publish、预览审批及v1 stop/resume均有实际通过记录；首次批次最后观察退出1，后来安全诊断wrapper仅重做v2 observe（含SDK/附件/WS/数据/权限）退出0。原失败无精确栈，原因未定，不改写为无中断整批通过。固定日志及ID见JSON；T067仍pending。

109 `d109src1`实际平台批次退出0：source-image两版发布、审批预览、HTTP/WS、SDK/OBO、真实附件、SQLite读写/导出、owner/非owner/跨租户配对、停用恢复与升级全程通过；缺离线依赖在precheck_build按16227拒绝且无审批。源码包使用显式8个pure-Python wheel及原SDK字节，bootstrap不访问网络、不读取开发venv。固定journal SHA `3c8b0eaff14c5483568767f64e8c706b512df81aa6ca0d0e98776a8bb35b79f4`，精确ID在JSON。旧失败source应用记录保留；当前manager仍54b，故障/最终清理未完成，T067不提前勾选。
