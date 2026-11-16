## 2026-11-16 Helm 移出本次范围

用户要求把 Helm 移出本次密码治理。`docker/helm/bisheng` 已恢复到治理前的 Chart，`src/backend/test/deploy/test_credential_helm.py` 已删除。下文把 Helm 外部 Secret、渲染通过或 Helm v2 拒绝写成当前交付的记录，只保留为当时的证据，不再描述当前 Chart，也不能计为本次通过。

---

## 2026-11-15 旧 ES 无认证升级：本地通过，166 待用户手动部署

用户确认将旧 ES 无认证升级纳入原部署脚本。原命令已接入服务端状态识别、交互选择、加密设密、原数据卷复用、断点续跑和显式配对回退。本地 Bitnami ES 8.12.0 单节点真实测试通过：由无认证、有原索引和别名的服务启动，启用认证并验证匿名业务访问拒绝、原索引身份/文档/别名保留，重启后密码仍可用，显式配对回退后原索引仍在；隔离项目容器清理完成。该测试使用本地 ARM64 镜像与覆盖后端，不是 166 AMD64 正式部署。机器可读结果文件已清理。此前只读检查只证明 166 后端缺少 basic_auth，并未证明服务端关闭认证；166 的实际部署与验收继续由用户手动执行。

ES 核心最终 18 passed；聚焦路径（核心、密封迁移、原命令、Redis 入口）49 passed、7 项依赖告警。扩大专项初跑 247 passed、1 failed、1 skipped：失败是 Redis 入口测试仍断言旧入口形式，而运行配置已由密文运行器包装；断言已按实际调用链修正。最终扩大专项重跑 **250 passed、1 skipped、7 项依赖告警、0 failed**（`/tmp/bisheng-es-final-regression2.log`）。跳过项为本机缺 Helm 可执行文件，不能计作 Helm 渲染通过。Bash 语法、Ruff、架构守卫和 git diff --check 通过。

166 仅准备 `/root/bisheng-feat-3.1-beta2` 的 99 个源码文件、独立 `.env` 和本地覆盖镜像 `bisheng-original-acceptance:20261115`；原 `/root/bisheng-feat-3.0.0` 脚本校验值未变，同项目仍是 15 个容器。未在 166 执行安装、启动/停止服务或修改 ES 账号。真实服务端状态、后端/worker 业务链路、DM 和正式成对发布镜像保持待验。

下方 240 项专项回归和早前 166 结果均不覆盖本新增能力，不得作为该场景已通过的证据。

---

## 2026-11-15 密码长度和字符种类调整

按用户新增要求，统一的输入校验改为 MySQL、Redis、ES、Milvus、统计 ES 至少 6 个字符；MinIO 原生密钥按组件自身限制至少 8 个字符。纯数字、纯字母、纯符号均可通过输入校验，不要求同时包含三种字符。空值、模板占位符、换行和 NUL 仍拒绝。首次安装与轮换共用此校验，交互提示显示对应下限。

专项扩展回归首次运行 237 passed、1 failed；失败仅为原命令交互测试仍匹配旧提示文案。更新精确提示断言后，相关 33 项测试全部通过（7 项依赖告警）；随后完整凭据专项回归重跑 240 passed、7 项依赖告警、无跳过，日志 /tmp/bisheng-password-minimum-final.log。未在 166 重新执行真实中间件改密；本次证据覆盖 Python 输入校验、加密落盘与原命令 PTY 输入流程，不声明纯符号密码已逐一经过五组件真实服务认证。

## 2026-11-14 单项 MinIO 与最终业务复验

普通部署账号通过原命令只选择 MinIO 改密，8 个提示完成、exit 0、无密码回显。数据、业务、worker 三项 safe probe 全部 passed；旧签名下载 URL 失效，重新获取的链接内容正确。MySQL、Redis、ES、etcd、OpenFGA 容器 ID 与此前保留部署快照相同；MinIO 及依赖它的 Milvus 正常重建。

最终持久目录扫描 1229 文件，无未允许的已知密码/约定编码命中、不可读文件或未核验链接。例外明确记录 Milvus 原生 RocksMQ Base64 消息及已核验的 MySQL socket 链接；Docker inspect、12 个当前项目容器的文件层和日志均通过。当前实际使用的 9 个不同镜像全部层流式扫描通过，scan-images.exit=0。原服务 3001 复查 HTTP 200。

扫描仅对本次在内存中取得的已知新旧密码及 raw、URL、JSON/repr、Base64 编码进行匹配，不等于通用秘密发现或任意编码解码。全程不生成明文密码词典或原始导出 tar 文件。

---

## 2026-11-14 最新复验进展（优先于下方历史记录）

当前仍为增量验收中，未提交或发布。聚焦回归已更新为 **213 passed、7 项依赖告警、无跳过**，日志 `/tmp/bisheng-sealed-full-final.log`；清理与恢复针对性集合 17 passed。

166 隔离环境发现并修复迁移清理容器未挂载源目录的问题：此前 journal COMPLETE 不能证明旧文件已删除。修复后要求完整受管目录可见、部署标识匹配、CLI policy-root 与签名状态一致；同时支持 COMPLETE 状态的清理恢复并保护正在使用的主密钥。通过专用夹具重新设置恢复指针（不修改签名 journal），由 UID 1000 执行原部署命令。直接检查旧目录原有 13 个文件，现为 **0 个**；恢复指针已移除，主密钥文件仍在。原命令已退出 0，五项保留选择均完成且无密码回显；后续单项 MinIO 改密与最终扫描尚待收口，不以文件数代替完整验收。

真实五组件数据探针、业务探针和实际 Celery 任务在此前迁移后通过；业务覆盖登录、权限拒绝、流程元数据、知识文件上传下载及确定性嵌入检索，不代表真实模型质量或完整流程执行。验收使用本地覆盖镜像，且为适配已发布后端增加了仅限夹具的 `/object/` Nginx 路由，不能据此声明最终成对发布镜像已通过。

Milvus 原生 RocksMQ 中 Base64 凭据按用户确认保留例外；部署器生成材料仍必须加密。DM 保持待验证。此处为 2026-11-14 历史状态：Gateway、rootless、未验证原生旧布局及当时的无认证旧 ES 采用明确拒绝；无认证旧 ES 已由上方 2026-11-15 补充实现取代，166 手动验收仍待执行。Helm v2 尚未验收。

---

## 2026-11-14 用户确认：Milvus 原生持久消息例外

用户明确要求“Milvus密码加密保持现状”。本次据此保留 Milvus 原生账号认证、凭据更新和 RocksMQ 持久消息机制；内部消息中可还原的 Base64 密码作为明确的验收例外，不认定为已加密。该例外仅覆盖 Milvus 自身生成的内部消息/数据文件，不扩大到部署器生成的密码输入、配置包、原生配置、历史副本和恢复备份，这些材料仍须加密。

不引入 Milvus 透明加密卷、FUSE、SYS_ADMIN 或原生镜像分叉。撤销仅因该发现而新增的整批改密拒绝门禁；保留正常的整批身份预检、维护确认、认证和故障恢复检查。仍执行原部署命令。其余未完成回归、业务、迁移和发布验收继续保留待验，不能据此宣布全部交付完成。

下方此前“Milvus阻塞/需重新确认/拟增加拒绝门禁”是历史发现，按本节用户确认的新范围执行；原扫描证据保留。

---

# 2026-11-14：v2 增量验收阻塞（优先于下方 v1 历史结论）

本增量**未通过完整验收**，未提交或发布。当时的 HTML 增量验收报告已清理，结论以本节为准。

- 独立环境：`/home/bisheng-cred-v2/acceptance-20261114`，项目 `rotation-acceptance-166-sealed-v2`。实际部署 UID 1000，使用已有 Docker 组，无部署阶段 sudo；非 rootless。
- 原命令新装完成；五项真实改密在 MySQL 阶段因加密诊断文件重复路径拒绝覆盖而停止，修复为独立不可变记录后原计划续跑完成。`drive-resume.json`：passed，exit_code 0，plaintext_echo false；五组件均 FILES_PERSISTED，journal COMPLETE。
- 原服务 3001 再次复查 HTTP 200；测试项目后端 healthy。未使用原有数据做改密试验。
- 持久扫描 836 文件，命中 `docker/data/milvus/rdb_data/000021.sst`；仅在内存进一步核对，确认 Milvus 密码的 Base64 表示两处出现。另有 MySQL socket 链接待核对。**扫描失败，不排除 SST，不计作安全通过**。
- 源码核对：Milvus v2.5.10 `internal/proxy/impl.go:UpdateCredential` 将原请求交给复制流，`internal/proxy/util.go:SendReplicateMessagePack` 生成 UpdateUserMsg，Proxy 初始化强制启用该生产者。现有加密配置与 tmpfs 未覆盖组件内部消息持久化；AC-59/61 尚未满足。
- 新增包含 Milvus 改密的整批请求安全门禁，在 capture/prepare/preflight/step 拒绝；不让其他选中项先修改。单测同时核对拒绝前没有调用原生连接、journal 不改变；166隔离增量镜像已重建；UID 1000执行含Milvus的既有混合计划preflight，退出2、命中特定门禁、journal哈希不变。未重建原有业务服务。
- 聚焦命令 `/tmp/bisheng-sealed-predecision-tests.log`：117 passed / 7 依赖告警；范围为新协议、完整包、输入、迁移、状态、角色挂载、重建、保护门禁与扫描等。Go Linux/arm64 静态测试以容器 UID 12031 运行 9 项通过，提供跨语言夹具且无 skip。
- 扩大旧回归历史命令 171 passed / 24 failed / 1 skipped；旧明文假设和边界 double 尚需适配，不能以新集合通过代替全量收口。语义适配后的 bundle/migration 集合 21 passed。
- 真实业务/数据探针本轮失败，诊断加密保存；不声明业务通过。真实存量升级、配对回退、全部持久范围与镜像层扫描未完成。DM、主机重启、Gateway、rootless 和 K8s 保持待验。

后续涉及加密文件系统或修改原生镜像，会改变 design §4.14 已确认的边界。依照 SDD-Guide §3，需先确认补充设计；不自动增加 SYS_ADMIN、挂载 FUSE 或修改宿主安全设置。

---

# 实施与验证记录：中间件密码与配置加密治理

**更新日期**：2026-11-12。**任务**：50 / 53 完成（含原入口返工）；T034、T035、T038 保留未完成。**整体状态**：代码与本地验证已实施，完整交付验收待执行。没有提交、推送、部署客户服务或改变客户真实密码。

## 1. 已实施内容

- 外置 version=1 有序 Fernet keyring，源码固定 key 已移除。Settings 集中处理 MySQL/DM、Redis URL/dict、MinIO、ES/统计 ES、Milvus password/token；秘密字段隐藏输入与 repr，坏密文显式失败。
- 共享局部 YAML/!env 读取、旧数据库环境来源、冲突拒绝；启动 preflight 先于 Alembic。显式 SQLite 测试配置与生产缺配置失败分开；pytest 自身生成临时 key/config，不提供生产回退。
- 配置包/CLI：fresh、adopt-key、单组件 password-change、key-rotation；新目录、文件权限、客户密码文件、原生消费者一致性、只读在线检查及退出码；不自动改账号/激活包。
- Compose/安装包装器：受控 native/key 挂载，MySQL 只读健康检查与独立建库，Redis ACL/PONG、MinIO、ES password-file、Milvus user.yaml、OpenFGA/Gateway 联动；应用进程显式重建。
- Helm：外部 Secret、三个 Python Deployment 的同配置/密钥与 revision rollout，旧密码 values 拒绝，独立 HMAC/sandbox 契约保留。
- 存量维护：仅组织同步 auth_config / 全局沙箱 token_enc；全量预检、密文备份/fsync、每批100行锁/内存核对、保留租户/时间/未知字段、journal/resume、缓存待处理、首 key 复检。反向字段恢复由 DBA 按 runbook 核对执行。
- 构建排除与源码/镜像元数据/全部镜像层扫描；运维手册和脚本索引已补齐。5项补充任务仅补既有运行路径/模板，范围见 tasks.md。

## 2. 实际执行结果

| 检查 | 结果 | 范围与限制 |
| --- | --- | --- |
| 聚焦回归（含既有数据库/Redis URL与沙箱回归） | **200 passed，9 skipped，0 failed** | 209项；9项显式真实环境测试未配置，不计作通过 |
| 扩展 core / Celery 配置 / org_sync 回归 | **328 passed，2 failed** | 两项既有 Beat 测试假设冲突，见下；与聚焦集有重叠，不相加 |
| 独立核心模块（隔离共享业务 fixture，较早一轮） | 84 passed | 后续新增的回归包含在最终200项中；不是完整部署证明 |
| 独立 DB维护运行测试 | 4 passed，9 live skipped | SQLite真实事务测试；MySQL/DM原生锁与驱动仍待验收 |
| Docker Compose config --quiet | 通过 | 合成非秘密路径/env，未启动完整服务 |
| Helm实际 template /负例 / lint | 通过 | 临时官方 Helm3.17.4，三个Python Deployment解析成功、旧 values 拒绝；未连接Kubernetes |
| Bash -n | 通过 | 包装器、安装器、entrypoint、MySQL/Redis/Milvus/Gateway、维护脚本 |
| Ruff format/check | 通过 | 32个本次变更Python文件 |
| 架构守卫 | 67个工作区变更文件，0违规/提示 | 包含新增文件；未扩大到无关发版线差异 |
| 后端源码扫描 | 0命中 | 扫描器能力边界内；真实交付镜像尚无档案 |
| 已知旧固定key精确扫描 | 67个变更文件，0命中 | 从HEAD在内存提取用于静态对照，不写文件/不回显；不是运行时旧key自动读取能力 |
| 镜像层/metadata扫描回归 | 通过 | 人工Docker-save档案夹具，覆盖下层残留、whiteout及metadata已知key；不是实际发布镜像扫描 |
| QA参考表 | 未执行 | 47条仍为“待执行”；不以单测代填QA结果 |

两项扩展失败均在 `test/celery/test_beat_schedule_registration.py`：测试要求任务名为模块全路径，现有 `runtime_audit_reconcile` 使用显式短名称，任务注册在 `worker/runtime_audit/tasks.py` 且由 worker 包导入。已核对 **CeleryConf AST、该测试文件和 worker/__init__.py 均与HEAD一致**；未修改无关任务名或降低断言。故扩展回归不标“全绿”，T038仍待闭环。

## 3. 可复现入口

本工作区没有 .venv；本次只读使用现有工作区的 Python3.11.15和依赖，PYTHONPATH始终指向当前后端，未修改其他工作区。正式环境可换为本项目 `uv run`。共享测试 conftest 已自带临时引导，不再需要外部临时pytest插件。

```bash
cd src/backend
export PYTHONPATH="$PWD"
# 将 python 替换为配套Python3.11环境；Helm需在PATH中。
python -m pytest \
  test/core/test_secret_crypto.py test/core/test_credential_settings.py \
  test/core/test_credential_loader.py test/core/test_credential_bundle.py \
  test/core/test_credential_tool.py test/core/test_credential_checks.py \
  test/core/test_credential_rewrap.py test/core/test_credential_redis_client.py \
  test/deploy test/credential_security \
  test/sandbox/test_sandbox_credential_failures.py test/sandbox/test_get_sandbox_conf.py \
  test/sandbox/test_sandbox_conf_probe.py test/sandbox/test_sandbox_conf_service.py \
  test/core/test_redis_password_url.py test/database/test_database_password_url.py -q
# 本次最终结果：200 passed, 9 skipped

python -m pytest test/core test/celery/test_celery_redis_config.py \
  test/celery/test_beat_schedule_registration.py test/org_sync -q
# 本次最终结果：328 passed, 2 failed（上述既有断言冲突）

# 隔离测试基础设施直接使用真实模块，而不是全局业务premock：
python -m pytest --confcutdir=test/core test/core/test_secret_crypto.py test/core/test_credential_settings.py test/core/test_credential_loader.py test/core/test_credential_bundle.py test/core/test_credential_tool.py test/core/test_credential_checks.py test/core/test_credential_rewrap.py test/core/test_credential_redis_client.py -q
```

临时Helm从官方get.helm.sh下载并对照官方SHA256校验，未安装到系统目录；其路径为 `/tmp/darwin-arm64/helm`。本地JUnit原始摘要在 `/tmp/bisheng-credential-focused.xml`（209/0/0/9）和 `/tmp/bisheng-credential-expanded.xml`（330/2/0/0），括号依次为总数/失败/错误/跳过。临时文件不作为长期交付证据，最终结果已写在本文。

先测后实现证据包括：加密模块缺失时导入失败；安装/Compose6项原契约失败；Helm未挂载外部Secret失败；迁移模块/脚本缺失失败；ACL权限保留回归先失败后修正；镜像metadata扫描先失败后实现；旧DB环境来源3项先失败后修复。最终有意义的断言覆盖原文件不覆盖、特殊字符/脱敏、旧/新密文、原生配置联动、并发第三值、当前批回滚、缓存故障/resume及磁盘失败先于提交。

## 4. 镜像机制核查和环境边界

只读检查了缓存上游镜像的入口/脚本：MySQL8.0、Redis7.0.4、MinIO2023-03-20、Milvus2.5.10、Bitnami legacy ES8.12.0及OpenFGA1.15.1。确认ES原生password-file加载机制和reset-password路径；Milvus2.5.10源码明确user.yaml最后覆盖；OpenFGA源码加载 /etc/openfga/config.yaml。**项目私有OpenFGA v1.15.2-dm等镜像不是上述缓存镜像，不能等同验收。**

尝试临时 Redis 隔离容器验证组权限、认证/改密/回退，但daemon不能访问本机bind源路径；改用文件复制方案后容器创建超时，未执行到认证验证。按唯一名称清理该测试容器成功。没有映射端口、使用客户数据卷或修改已有服务；本项记为未完成，不能报通过。

尚未完成：私有镜像启动/UID/GID/原生文件读取、全组件新旧密码状态与失败恢复、ES/MinIO/Milvus真实读写、MySQL/DM同场景事务/锁、实际发布镜像各层扫描、多节点/全部Python进程、Sentinel/Cluster/TLS和客户外部权限组合。原生TLS证书与Go/Python信任根必须分别挂载验证，不能因某个上游参数存在就承诺组合通过。

## 5. E2E技能执行记录

按 `/e2e-test` 的SDD分类：本特性无新增HTTP API或前端交互，内部加密/文件逻辑由单测覆盖；已有业务链路和真实部署验收仍需E2E。当前没有显式隔离应用URL、认证身份、真实中间件与DM环境，业务E2E未执行。整体为 **PARTIAL**。

真实测试入口已添加，默认不会连客户环境：

```bash
# 仅在专用可丢弃验收环境设置；config须为同部署YAML，keys为同部署密钥。
export BISHENG_CREDENTIAL_LIVE_DISPOSABLE=true
export BISHENG_CREDENTIAL_LIVE_BUNDLE=/secure/acceptance/bundle
export BISHENG_CREDENTIAL_LIVE_KEYS=/secure/acceptance/keys.json
export config=/secure/acceptance/bundle/config.yaml
python -m pytest --confcutdir=test/credential_security test/credential_security/test_live_middleware.py test/credential_security/test_live_rewrap.py -v
```

验收专用写入只清理本次创建的 e2e 前缀对象/索引/collection/组织配置ID。MySQL/DM分别运行；真实改密由管理员runbook显式执行，改前、改后和配套恢复后复用新连接测试，不能仅跑一次就覆盖全部生命周期。

| AC组 | 当前自动化证据 | 真实E2E/手动验收待办 |
| --- | --- | --- |
| AC-01~06 | 外置key、字段解密、错误/repr、源码/夹具扫描通过 | 实际发布镜像、进程日志和启动顺序 |
| AC-07~11 | 新包、弱值、原文件保留、完整CLI、冲突与env来源通过 | 新装配套镜像、真实连接以及自定义来源 |
| AC-12~17 | MySQL/OpenFGA/Gateway原生契约、Redis各消费者与ACL回归通过 | 新装/存量改密、新旧/匿名拒绝、Gateway及队列处理 |
| AC-18~23 | MinIO/Milvus对象凭据联动、ES与统计字段/TLS参数通过 | 旧对象/新上传/签名、ES同步异步和统计写入/查询 |
| AC-24~27 | Milvus认证源冲突、模型传参、对象凭据与登录分离通过 | 锁定pymilvus/Milvus组合、已有collection及新写入、改密不确定结果 |
| AC-28~36 | 重加密计划/幂等、SQLite事务、时间/tenant/JSON、缓存故障恢复通过 | MySQL/DM同夹具、组织同步/沙箱真实使用、停写/在途任务/配套恢复 |
| AC-37~40 | Compose/Helm实际渲染、安装替身、显式recreate/revision通过 | 所有节点API/Worker/Beat/Linsight版本与新连接、源码/systemd/K8s rollout |
| AC-41~42 | 限制和runbook已交付，未执行状态明确 | 私有镜像/集群TLS/Sentinel及完整业务与恢复签收 |

待验收清单：

- [ ] 新装全部组件用客户独立密码；匿名/旧密码拒绝。
- [ ] API迁移、OpenFGA权限及普通用户业务行为；无越权或身份回退。
- [ ] Celery知识/工作流/default队列、Beat、Linsight与Gateway新连接；在途任务逐一核对。
- [ ] MinIO旧对象、上传下载和新签名；ES同步/异步/统计；Milvus工厂/ORM已有collection与新数据。
- [ ] 全租户组织同步与沙箱页token实际使用；坏token显式失败。
- [ ] 新旧key过渡、首key独立复检、缓存清理、全部节点重启后才移除旧key。
- [ ] MySQL/DM原生锁与批事务；磁盘/缓存故障、第三值、部分提交和resume；恢复不覆盖新增数据。
- [ ] 全部有效key丢失/管理身份丢失的人工恢复演练；保留队列/对象/索引/向量数据。
- [ ] 实际交付源码、容器最终内容和各镜像层无固定/部署秘密；QA47条正式执行。

## 6. SDD特性级代码审查

**审查目标**：当前工作区相对HEAD的已跟踪修改，加本特性未跟踪新增文件；对照spec/design/tasks、七维度清单和实际测试。没有以单独的 git diff 忽略新文件。任务L1详见 task-reviews.md。

| 维度 | 当前结论 | 证据/待办 |
| --- | --- | --- |
| 边界条件 | 本地PASS | 空/坏key、权限/FIFO、格式/冲突、特殊字符、旧新值/第三值、超时/关闭资源、文件失败 |
| 权限与认证 | 本地PASS，真实待验 | 无新增业务权限入口；维护显式跨租户；ACL不扩权；认证开关与账号变化需真实镜像验收 |
| 错误处理 | 本地PASS | 参数/SDK错误脱敏，坏token不改身份；DB提交后缓存失败保留pending，不伪报回滚 |
| 数据一致性 | 本地PASS，双DB待验 | 锁后核对、100行事务、备份先fsync、保留tenant/时间/未知JSON、幂等resume；DM驱动/原生锁未验 |
| 测试覆盖 | **NEEDS_FIX（交付证据待齐）** | 200通过/9未执行；扩展328通过/2既有失败；真实全链路与恢复不足，不能合入签收 |
| 代码风格 | PASS | Ruff、Bash解析、架构守卫、无未声明产品路径 |
| 文档同步 | PASS | design实现快照、43项tasks、运维/部署/Helm手册、脚本索引及限制已同步 |

**总体结论：NEEDS_FIX（验收未闭环）**。本地审查发现的ACL权限、Gateway联动、缺省字段校验/旧环境来源、native配置一致性、测试引导和发布模板问题已修正并有回归。仍需T034/T035/T038的真实环境证据和既有Beat测试问题的独立收口后，才出具可交付PASS；不把跳过项或容器存活当作通过。


## 7. 2026-11-12 原入口返工结果（最新）

用户已确认“原命令部署、必要信息在部署过程中引导”。本轮代码与本地回归完成，正式交付门禁仍未闭环。

### 实现结果

- 原命令 `bash docker/install.sh` / `bash scripts/deploy.sh install` 均保留，无需手填bundle/key/revision。首次客户密码隐藏并两次确认，现有输入检查失败仅重问当前组件；统计ES按配置询问。不兼容旧后端镜像在原入口引导选择配套镜像；非交互明确停止。
- 自动外置key、加密配置/native文件、随机revision、权限/挂载及检查；只有未检测到既有身份/数据时允许新建。现用.env的配置路径/key/revision成组原子激活，prepared指针支持复用，中断可重试；匹配文件丢失时引导备份，不生成替代密钥。正常重复不执行账号改密。
- 旧部署在原入口确认维护及全部节点停写，读取原容器config/env/key到私有文件，新主key+旧key过渡；暂停本机标准应用后调用既有DB维护工具dry-run/apply/verify，持久备份/计划，失败保持停止并通过原命令resume。原生组件不重建，实际密码/认证状态不变，pending不标完成治理。
- HTML SOP替换221步旧版，主线为原命令；高级工具仅作维护附录。旧Markdown SOP不再交付。设计、53项任务与55项QA参考同步，QA状态没有以单测代填。

### 本次实际验证

| 检查 | 最新结果 | 说明 |
| --- | --- | --- |
| 与原聚焦集相同选择，加本轮回归 | **221 passed，10 skipped，0 failed** | 231项；9项live环境未配，1项Helm不可用；历史200/9是上一轮结果，不相加 |
| 原安装器shell契约 | **15 passed** | registry stdin、Gateway配置/路由/复用、两种Compose、免宿主Python、prepare-only、错误止步；Docker边界替身 |
| 真实终端PTY | **通过（含在221项）** | 使用系统Bash/stty，快速输入不回显，确认不一致重问；不是实际中间件部署 |
| 新装/重复/恢复/旧版迁移编排 | **通过（含在221项）** | 执行实际Python离线加密CLI；Docker启动、在线连接、DB调用为显式边界替身，DB底层另有SQLite运行回归 |
| Compose app-runtime静态门禁 | **通过** | 真实Compose解析；默认14/启用profile18个service，含独立mysql-init；未起容器 |
| Ruff与Bash解析 | **通过** | 返工6个Python文件；逐个bash -n六个改动脚本 |
| 架构守卫 | **75个文件，0发现** | 当前已跟踪差异+全部本特性未跟踪文件，含文档；不是仅git diff忽略新文件 |
| 后端源码扫描 | **0发现** | 未提供本次发布镜像档案，不能宣称镜像层验收通过 |
| SOP结构校验 | **通过** | 20个编号步骤无缺号，目录锚点有效，无非法控制字符；不包含正常安装的三项显式路径参数 |

本轮没有重新运行旧的扩展Beat回归；§2记录的两项既有失败仍保留。Helm上一轮实际渲染通过，本次因临时Helm已不可用标为未重跑，不能沿用旧结果计入本轮passed。

### E2E与L2补充结论

按已读取的 `/e2e-test` SDD分类，AC-43～47是安装/终端及内部配置契约，无新增HTTP API/浏览器交互；增加原入口及真实PTY回归。原业务与真实部署E2E仍需专用应用URL/身份/中间件/DM环境，本轮未连接共享或客户环境，**整体PARTIAL**。新增QA048～055均待真实执行。

L2复核包含全部新文件和现有改动，按七维度：边界条件PASS；权限/认证本地PASS（维护显式跨租户授权，其他节点必须停写）；并发安全本地PASS（部署锁、唯一新目录、原子指针、DB原计划resume）；信息泄漏PASS（FD3/stty、私有文件、不传秘密argv、无固定key）；代码风格PASS；文档同步PASS；测试覆盖 **NEEDS_FIX（真实交付证据待齐）**。当前总体不出具可合入/生产交付PASS。

真实镜像新装与升级、实际账户状态、MySQL/DM事务/锁及全业务恢复仍按T034/T035/T038执行，未完成的三项保持未勾选。无提交、推送、合并、客户实际改密或部署。


## 8. 治理方案 HTML 全文同步（2026-11-12）

根据用户指出的方案文档漂移，将《中间件密码与配置加密治理方案.html》从顶部补丁说明更新为v2.0全文：保留15章和design-it原样CSS，更新原入口架构/三场景流程两张SVG、密钥迁移与五组件自动新装/专项改密步骤、恢复/可行性/当前验收状态，并从源码重新定位14项代码索引。删除“方案待实施”“工具命令尚未实现”等过期正文，将改造前问题与当前实现/待验项分开。

本次仅同步文档；没有改动运行代码或重跑后端回归，221 passed/10 skipped及15项shell结果仍引用§7的实际记录。结构检查通过：15章TOC与section双向匹配、ID唯一、本地链接目标存在、两张SVG XML合法、无非法控制字符、样式与技能模板一致；架构守卫及git diff --check通过。浏览器工具拒绝file://协议，未通过服务器/其他浏览器等方式绕过限制，未完成本次视觉预览。

## 9. 2026-11-13 本地真实验收（最新）

**结论：标准单机 Compose 范围有条件通过；完整交付仍未关闭。** 用户明确没有DM环境，本轮DM保持NOT RUN，T035/T038不勾选。T034标准单机组合完成，新增实测修复T054～T059完成，当前57/59。

当时的 HTML 本地验收报告和机器摘要已清理。私有原始证据在`docker/.generated/local-acceptance-20261113/control/`，不提交密码、key、环境快照和原始日志。

| 检查 | 最新实际结果 | 边界 |
| --- | --- | --- |
| 聚焦单测/兼容回归 | 231 passed，0 failed，0 skipped；20.95秒 | 含MySQL入口5项、缓存上下文2项、wrapper重复挂载2项、既有URL/沙箱及真实Helm渲染；不含下列live |
| 实际组件/原生MySQL | 9 passed，0 failed，2 warnings；23.77秒 | 修改实际账号密码后重跑；新增缓存清理后DB可继续读取断言，真实网络/事务，无SDK mock |
| 原安装器shell契约 | 15 passed | 此组Docker边界为替身；不能代替真实部署 |
| 原入口实际部署 | 安装/原包装入口重复均退出0；PTY曾实际提示五密码/确认，原文不回显 | 初次暴露vendor MySQL缺陷；修复后只留存并重建本次可销毁MySQL，复用同一密码/key/config重测；不声称未知半初始化自动修复 |
| 重复与密钥恢复 | 首次重复key/config字节不变；缺key非交互退出1、不生成替代身份；交互匹配备份恢复退出0 | 真实原脚本、PTY和Docker |
| 真实旧版升级/故障续跑 | 基线285bfde44d镜像API健康；3条旧密文，含两租户和全局沙箱；CACHE_PENDING后同命令resume到COMPLETE=3 | 7个原生容器ID未变；tenant/time/JSON保留，新主key独立复检、续跑密文不再变，页面token优先于部署token |
| 五组件实际改密及配对回退 | 两轮服务端与消费者配对激活均成功；五项被替换密码新连接均拒绝 | MinIO通过匹配文件重建生效，Milvus对象存储联动；不是仅修改初始化文件 |
| 数据一致性与拒绝路径 | 五组件标记跨重复/迁移/改密/回退均保留；五组件无凭据访问均拒绝 | MySQL1045、Redis认证错误、S3认证/访问拒绝、ES401、MilvusUNAUTHENTICATED；不把任意网络异常当认证拒绝 |
| 当前交付镜像 | 项目原Dockerfile构建，冻结依赖；源码/元数据/全部镜像层扫描退出0，约1.43GiB | 额外匹配真实历史及测试部署/过渡密钥；目标CR beta2后端标签不存在，仅推本机loopback仓库 |
| 日志检查 | 修复后的9容器及6份安装日志，已知秘密原文/URL/JSON/repr匹配0命中 | 不是通用日志安全证明；原始诊断日志受限保存 |
| Compose/Helm/静态 | app-runtime真实解析通过；默认14/profile18；官方Helm3.17.4校验SHA256后真实渲染通过 | 没有真实Kubernetes rollout；最终Ruff/shell/架构/HTML检查见机器摘要 |

### 9.1 实测产品问题及收口

- **MySQL bootstrap**：CR8.0.43直接拼接含单引号密码导致1064/部分初始化/未设密root socket可连。安全SQL/CNF序列化wrapper保留vendor生命周期与降权、显式mysqld；相同输入真实初始化成功，无密码socket拒绝。未知半初始化状态仍须保留现场并受控恢复。
- **缓存生命周期**：维护函数关闭全局DB上下文，导致恢复Redis后主key复检仍失败。改为独立RedisClient并只关闭自身；两项SQLite消费者回归红到绿，同一实际DB计划resume成功。
- **维护挂载**：inputs和out共父目录重复挂载，Docker在准备阶段拒绝。精确同目标合并、显式输出父目录保留写权限，其余只读；两种顺序及真实五组件包准备通过。

### 9.2 E2E覆盖与人工项

API经Nginx执行匿名401、RSA注册、登录和用户信息最终状态核对；验证码保持启用，仅API夹具读取自己nonce。账号为本地首次管理员，不能证明全部普通用户ReBAC。真实页面登录交互、知识语义召回/LLM工作流、完整Linsight、页面沙箱执行、旧签名URL、统计ES业务、许可Gateway、真实K8s、外部集群/TLS、多节点及性能没有执行，保持人工/专项待验；不将SDK读写算作全业务E2E。

本轮清理前的全部6个原用户数据卷及11个改名旧毕昇容器仍保留、旧服务仍停止。只删除1,145个无关镜像ID；新建镜像/卷仅用于此次验收。五组件标记和3条迁移夹具已按精确范围清理，保留测试账号。最终平台及API健康均HTTP200，当前验收栈继续运行供查看。

### 9.3 L2补充审查

边界：同目标参数顺序、空数组Bash3.2及特殊字符有回归；认证：正确/替换/无凭据配对；并发：显式租户谓词、行锁及原计划幂等；泄露：镜像全层与已知秘密日志检查；覆盖：本地标准组合通过、DM等明确缺失；风格：Ruff/脚本与架构门禁；文档：design/tasks/HTML同步。三项实测修复范围PASS，完整特性交付仍为NEEDS_FIX（T035/T038及专项环境未闭环），不输出生产PASS，不合入或提交代码。

最终静态收口：Ruff检查34个Python文件通过，10个shell语法通过，架构守卫80文件0发现，三份HTML锚点/本地链接与2张SVG结构通过，git diff --check通过；本轮未做浏览器视觉预览。

## 10. 提交与远端整合

2026-11-13用户授权commit并推送当前分支；验收结论、DM及完整交付待验证状态保持不变。远端新增4个安全修复提交及001/002特性文档，整合时保留远端内容，将本特性文档编号调整为003并合并版本契约。提交推送不等于发布可部署镜像。整合后的聚焦回归231 passed、0 failed、0 skipped（21.91秒）。本轮未重建包含远端4项安全修复的镜像，原9项live与部署演练仍明确属于整合前已记录镜像；新机器所用配套镜像需要另行构建发布。

## 11. 原入口逐项改密增量验收（2026-11-13～14）

结论：标准单机支持范围内，本轮T060～T083完成；总进度81/83。T035（DM无环境）和T038（完整交付及专项回归）继续保留。代码增量未提交，最终配套镜像未发布；不能直接把既有远端标签当成本次验收产物。

### 11.1 环境、命令与实际证据

用户指定192.168.106.166。新建独立目录`/root/bisheng-rotation-acceptance-20261113`、Compose项目`rotation-acceptance-166`，使用新数据、新账号和独立密钥；没有修改原部署及其密码。后端基于机器已有`cr.dataelem.com/dataelement/bisheng-backend:feat_3.1-beta2`覆盖当前配置模块，构建本地`bisheng-rotation-acceptance:20261113`，前端使用原发布镜像。测试包装器仅将镜像拉取替换为本地缓存存在性检查；原生组件、账号写入、Compose生命周期与应用均为真实服务。未验证最终发布镜像的远端交付。

真实安装执行原`docker/install.sh --no-gateway`，自动化改密使用原入口及其已有受限输入文件支持。交互分支另有PTY回归，逐项默认保留、隐藏输入、维护确认及恢复菜单通过。隔离配置仅修改项目名称、网络、数据目录、loopback端口等测试资源归属。

| 验收项 | 结果与证据 |
| --- | --- |
| 初始安装与五组件整体改密 | 两轮真实五组件改密成功；全部新身份通过、旧身份拒绝；第二轮写入前整批认证预检通过；包括引号、反斜杠及`@$#%`等特殊字符 |
| 最终归属预检 | 最终镜像对真实Docker捕获数据执行只读capture成功；外国地址、DNS不归属及不支持Redis命令的拒绝有回归 |
| 原命令重复部署 | 退出0；计划仍为2个；MySQL两个root账号password_last_changed均未变，未再次执行原生改密 |
| 密钥、数据、配置保留 | 密钥文件SHA256不变；MySQL行、Redis键、S3对象、ES文档、Milvus向量五类预置数据均保留；新配置可供实际后端读取 |
| 业务回归 | 经真实Nginx完成管理员与普通账号登录、用户信息、管理租户选择、工作流元数据保留、知识文件上传/下载和检索；验证实际召回内容及空间ID，旧签名URL拒绝、非所有者读取拒绝 |
| Worker | 真实Celery control ping及任务投递，按本次UUID核实实际Worker日志中的succeeded；重复部署就绪后再次通过 |
| 故障续跑与配对回退 | 本地独立真实中间件2项live通过：原生已成功而文件未落盘的注入故障后续跑不重复MySQL ALTER；PTY选择配对反向计划恢复强旧身份与配置 |
| 单项及混合选择 | 本地真实五项逐一、MySQL+Redis及全部选择通过；相同请求幂等live另1项通过。该本地栈的应用消费者为夹具，业务证据以166全栈为准 |
| 镜像检查 | 最终增量镜像源码及docker save全部层扫描退出0；额外匹配本次密钥。不是已发布镜像验收，也不是未知秘密绝对不存在的证明 |

运行元数据另行检查：读取初始及两轮改密的15项已知密码，匹配全部隔离Compose容器Config.Env/Cmd/Entrypoint/Healthcheck的实际解码字符串，0命中；密钥文件0600。`*_PASSWORD_FILE`中的路径不是密码，未将路径误算为秘密原文。证据`control/runtime-secret-scan-safe.json`。

远端原始证据保存在上述目录的`control/`（私有日志不可公开）：`rotation-first.private.log`、`rotation.private.log`、`repeat.private.log`、各`*-after.exit`、`image-scan.log`、`acceptance-safe.json`。仓库里的脱敏汇总已清理，不保存账号、验证码、cookie、密钥或签名URL。

### 11.2 实测问题与修复

1. Linux Redis vendor入口降权丢失补充组，无法读取0640 ACL：用受控setpriv保留明确授予的组，运行UID/GID仍为redis；标准Compose与改密编排均接入，不放宽文件权限。实际Linux入口通过，标准Compose接线另有解析断言。
2. ES初始化期间临时JVM提前通过健康检查：新装、复用和改密均等待最终PID1 Java进程。临时bash到最终java有专门回归。
3. MinIO冻结异常被生成器上下文破坏、Milvus SDK暗中重试写请求：分别采用类式上下文和同一已认证通道的一次RPC，避免误判旧身份与重复写入。
4. 增加整批新旧认证与Docker地址归属验证；任何双通、未知、外部或歧义目标均在账号写入前拒绝。恢复时重新核实已持久化检查点，不凭文件状态跳过服务器验证。
5. 重复部署后立即执行的业务探针一度因应用尚在启动失败；等待后端healthy与Worker上线后全部复测通过。保留失败日志，不把启动中的HTTP响应计为权限或业务验收成功。

### 11.3 自动化与L2增量审查

最终聚焦集：`test/core/test_credential*`、`test/core/test_rotation*`、`test/core/test_secret_crypto.py`、`test/deploy`、`test/credential_security`、沙箱坏密文回归，**205 passed / 20 skipped / 7 warnings，34.31秒**；20个跳过项包括未开启的live与Helm环境，不计通过。真实live使用上述单独证据。Redis标准接线收口2项另行通过。Ruff、shell语法、五个改密/CLI生产模块架构守卫及git diff --check通过。

L2七维：边界（强旧密码回退、未知身份拒绝、支持版本明确）、认证（新旧配对及DNS归属）、并发/恢复（部署锁、封存计划、意图检查点、整批预检）、泄露（受限文件、隐藏输入、镜像扫描）、覆盖（CLI/真实组件/业务/故障并列）、风格（静态门禁）、文档（原命令与限制同步）本轮范围PASS_WITH_NOTES。完整特性保持NEEDS_FIX：T035/T038未闭环，不宣称生产发布通过。

### 11.4 支持范围及未覆盖项

真实组合为MySQL8.0.43 root、Redis7.0.4 default且非TLS/6379、ES8.12.0、MinIO RELEASE.2023-03-20T20-16-18Z、Milvus2.5.10（SDK2.6.15，已认证root）。主动Gateway、独立统计ES、外部集群、非标准Redis及未经验证的管理身份在预检拒绝，不自动猜测密码。

业务检索使用明确的确定性embedding测试提供者；验证真实存储与检索链路，不评价模型效果。工作流仅验证元数据，完整LLM工作流、Linsight、页面交互、真实Kubernetes、多节点、性能及DM尚未执行。现有部署前端HTTP200复核通过；隔离验收资源与私有证据保留，停止测试容器后不删除数据卷。

清理复核：本地`rotation-acceptance-20261113`及166的`rotation-acceptance-166`项目容器已停止，仅处理精确项目标签的自有资源；测试embedding另按自有标签停止。没有删除镜像、配置、日志或数据卷。166原12个`bisheng-*`容器仍运行，原前端再次HTTP200；本地原`bisheng-*`服务继续运行。
