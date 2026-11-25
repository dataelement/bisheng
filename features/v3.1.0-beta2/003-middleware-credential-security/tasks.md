# Tasks：中间件密码与配置加密治理

Milvus 内部 Base64 消息例外、选项 C 和旧 ES 无认证升级的现行范围见 [spec.md](./spec.md)。不要按 2026-11-14「原生文件必须全部加密」理解本任务表里的旧描述。

> **2026-11-15 选项 C**：应用字段密文，原生文件受限明文。2026-11-14 的全量密封发现收在 [discovery.md](./discovery.md) §9，已被选项 C 收窄。AC-57～AC-70 以 spec 现行文本为准，设计见 design §4.14。原 81/83 是 v1 历史，不代表本轮交付完成。

> 2026-11-13新增原入口逐组件选择改密需求：AC-48～AC-56已获用户确认，设计§4.13已确认，追加T060～T083；本轮标准单机验收完成，原DM与完整交付门禁保留。

**关联**：[spec.md](./spec.md) · [design.md](./design.md)
**版本**：v3.1.0-beta2。**分支**：当前 feat/3.1-beta2，不创建/切换分支或 worktree。

## 状态

| 步骤 | 状态 | 备注 |
| --- | --- | --- |
| spec.md | ✅ 已评审 | AC-01～AC-76 原门禁见 reviews.md；2026-11-25 已确认首次设密增量 AC-77～79 与设计 |
| design.md | ✅ 已确认 | 现行正文是选项 C；2026-11-14 密封方案审查只作历史记录 |
| test-cases.md | ✅ 已编写 | QA 参考；执行证据见 verification.md，不以用例数量宣告全覆盖 |
| tasks.md | ✅ 已拆解 | 拆解门禁见 reviews.md；逐任务 L1 见 task-reviews.md |
| 实现 | 🟡 进行中 | 109/119；协议、原入口、迁移清理和权限门禁已复验，整体v2尚未完成，T035（DM）/T038（完整交付）保留未完成 |

## 用户最新修正（2026-11-12）

原40/43仅指旧方案；本次已追加T044～T053实现与回归，取消正常部署的人工配置包前置步骤，详见design.md §0及§4.6.1。标准单机T034真实验收见2026-11-13报告；完整验收仍受T035/T038门禁约束。

## 开发模式

按依赖波次顺序执行，各任务完成后做 task-review 再勾选。测试任务只写断言/夹具，配对实现随后进行；安全基础设施也采用有意义的先测后实现。测试任务完成只表示代码已写并捕捉到红阶段，AC 满足仍以配对实现变绿和相应集成结果为准。

每项最多两个目标文件。共享文件后续任务只增加前驱约定能力，不覆盖前驱产物。无前端、新 API、新表或错误码任务；不创建无关类型空任务。原 Celery headers → ContextVar 不变，维护跨租户操作有显式范围。

中间件、镜像和 DM 在可用 CI/验收环境执行；缺环境不得算通过。QA 用例单独交测试工程师，本计划从 spec/design 独立拆解，不以用例表生成脚本或依赖。

## Tasks


### Wave 1 · 独立加密与构建基础

- [x] **T001**：外置密钥安全回归
  **类型**：测试
  **文件**：`src/backend/test/core/test_secret_crypto.py`
  **逻辑**：临时文件和动态 key；缺失、坏格式、权限、轮换、快照和脱敏；不导入业务上下文。
  **覆盖 AC**：AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-30
  **依赖**：无

- [x] **T002**：外置加密基础
  **类型**：基础设施
  **文件**：`src/backend/bisheng/core/config/secret_crypto.py`
  **逻辑**：外部 version=1 有序 keyring，首项写入、全环解密、进程快照；保留 str/bytes 约定，无固定 key。
  **覆盖 AC**：AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-30
  **依赖**：T001
  **配对测试**：T001；绿阶段及 L1 审查通过后完成。

- [x] **T032**：构建隔离回归
  **类型**：测试
  **文件**：`src/backend/test/deploy/test_credential_build.py`
  **逻辑**：使用临时源文件/镜像档案夹具验证秘密分层扫描和脱敏；真正交付源码及镜像的全量扫描在 T038 执行。
  **覆盖 AC**：AC-01, AC-06, AC-42
  **依赖**：无

- [x] **T033**：构建秘密排除
  **类型**：基础设施
  **文件**：`src/backend/.dockerignore`、`src/backend/scripts/check_image_secrets.py`
  **逻辑**：排除本地配置/env/secrets/generated；扫描交付文件及显式镜像档案层，只报位置不打印 key，缺输入不伪通过。
  **覆盖 AC**：AC-01, AC-06, AC-42
  **依赖**：T032
  **配对测试**：T032；绿阶段及 L1 审查通过后完成。

### Wave 2 · 运行配置与现有消费者

- [x] **T003**：密码字段回归
  **类型**：测试
  **文件**：`src/backend/test/core/test_credential_settings.py`
  **逻辑**：覆盖数据库、Redis URL/dict、ES/统计、MinIO、Milvus；特殊字符、冲突及坏密文。
  **覆盖 AC**：AC-04, AC-05, AC-06, AC-07, AC-11, AC-18, AC-21, AC-24, AC-27
  **依赖**：T002

- [x] **T004**：模型集中解密
  **类型**：基础设施
  **文件**：`src/backend/bisheng/core/config/settings.py`、`src/backend/test/conftest.py`
  **逻辑**：移除固定 key，转发 T002，集中字段解密/脱敏/去默认值；不重复解密已解析模型。 共用测试 fixture 使用临时动态 key，不保留生产兼容常量。
  **覆盖 AC**：AC-01, AC-04, AC-05, AC-06, AC-11, AC-18, AC-21, AC-24, AC-27
  **依赖**：T003
  **配对测试**：T003；绿阶段及 L1 审查通过后完成。

- [x] **T005**：配置来源回归
  **类型**：测试
  **文件**：`src/backend/test/core/test_credential_loader.py`
  **逻辑**：!env、旧环境来源、多源冲突、必填 URL、显式开发配置和纯读取。
  **覆盖 AC**：AC-03, AC-04, AC-08, AC-09, AC-11, AC-38
  **依赖**：T004

- [x] **T006**：共享纯读取器
  **类型**：基础设施
  **文件**：`src/backend/bisheng/core/config/credential_loader.py`
  **逻辑**：局部 SafeLoader/来源映射；只读文件与 env，不导入 DB，不增加顶层 YAML。
  **覆盖 AC**：AC-03, AC-04, AC-08, AC-09, AC-11, AC-38
  **依赖**：T005
  **配对测试**：T005；绿阶段及 L1 审查通过后完成。

- [x] **T007**：运行引导接入
  **类型**：实现
  **文件**：`src/backend/bisheng/common/services/config_service.py`、`docker/bisheng/entrypoint.sh`
  **逻辑**：同源读取和 preflight；在 Alembic 前拒绝缺 key/URL，移除相关 xtrace；保留 Worker 租户 headers 语义。
  **覆盖 AC**：AC-03, AC-04, AC-06, AC-11, AC-38
  **依赖**：T005, T006
  **配对测试**：T005；绿阶段及 L1 审查通过后完成。

- [x] **T008**：沙箱错误身份回归
  **类型**：测试
  **文件**：`src/backend/test/sandbox/test_sandbox_credential_failures.py`
  **逻辑**：非空坏页 token 不回退部署身份，未配置页 token 保持旧语义，覆盖 DB/cache 来源。
  **覆盖 AC**：AC-29, AC-31
  **依赖**：T004

- [x] **T009**：沙箱坏密文显式失败
  **类型**：实现
  **文件**：`src/backend/bisheng/common/services/config_service.py`、`src/backend/bisheng/tool/domain/services/sandbox_conf_service.py`
  **逻辑**：仅 InvalidToken 转脱敏配置失败，其他无关业务回退不扩改。
  **覆盖 AC**：AC-06, AC-29, AC-31
  **依赖**：T007, T008
  **配对测试**：T008；绿阶段及 L1 审查通过后完成。

- [x] **T039**：Redis 单点字典运行适配回归
  **类型**：测试
  **文件**：`src/backend/test/core/test_credential_redis_client.py`
  **逻辑**：执行真实适配器，覆盖同步/异步连接参数与 TLS、不污染原字典。
  **覆盖 AC**：AC-04, AC-11, AC-15
  **依赖**：T004

- [x] **T040**：Redis 单点字典运行接线
  **类型**：实现
  **文件**：`src/backend/bisheng/core/cache/redis_conn.py`
  **逻辑**：single dict 连接双客户端；Sentinel 字符串地址用 literal_eval，不执行 eval。
  **覆盖 AC**：AC-04, AC-11, AC-15
  **依赖**：T039
  **配对测试**：T039；已过绿阶段与 L1。

- [x] **T041**：更新既有沙箱错误身份断言
  **类型**：测试
  **文件**：`src/backend/test/sandbox/test_get_sandbox_conf.py`
  **逻辑**：旧坏密文回退断言改为显式失败；保留合法空值及其他回退回归。
  **覆盖 AC**：AC-29, AC-31
  **依赖**：T009

### Wave 3 · 配置包与只读检查

- [x] **T010**：配置包回归
  **类型**：测试
  **文件**：`src/backend/test/core/test_credential_bundle.py`
  **逻辑**：fresh/adopt-key/增量 mode；弱值、冲突、不覆盖、!env 物化、非秘密保留和无网络。
  **覆盖 AC**：AC-05, AC-07, AC-08, AC-09, AC-10, AC-11, AC-28, AC-37
  **依赖**：T006

- [x] **T011**：输入与序列化
  **类型**：基础设施
  **文件**：`src/backend/bisheng/core/config/credential_inputs.py`
  **逻辑**：安全清单、组件限制与密码文件读取；无 source/eval，adopt-key 记录未治理项。
  **覆盖 AC**：AC-07, AC-08, AC-10, AC-11, AC-28
  **依赖**：T010
  **配对测试**：T010；绿阶段及 L1 审查通过后完成。

- [x] **T012**：版本包渲染
  **类型**：实现
  **文件**：`src/backend/bisheng/core/config/credential_bundle.py`
  **逻辑**：新目录输出；增量只改目标/消费者；native 实际凭据和业务密文分开，不输出秘密摘要。
  **覆盖 AC**：AC-05, AC-08, AC-09, AC-10, AC-11, AC-12, AC-15, AC-18, AC-21, AC-24, AC-28, AC-37
  **依赖**：T010, T011
  **配对测试**：T010；绿阶段及 L1 审查通过后完成。

- [x] **T013**：离线 CLI 回归
  **类型**：测试
  **文件**：`src/backend/test/core/test_credential_tool.py`
  **逻辑**：子进程验证 keygen/prepare/check 无账号修改、退出码、原文件保留及无秘密 argv/log。
  **覆盖 AC**：AC-02, AC-06, AC-08, AC-09, AC-10, AC-37
  **依赖**：T012

- [x] **T014**：离线 CLI
  **类型**：实现
  **文件**：`src/backend/bisheng/core/config/credential_tool.py`
  **逻辑**：实现已确认参数/退出码；仅显式 keygen 生成 key，prepare 不激活不改账号，复用前驱模块。
  **覆盖 AC**：AC-02, AC-06, AC-08, AC-09, AC-10, AC-37
  **依赖**：T013
  **配对测试**：T013；绿阶段及 L1 审查通过后完成。

- [x] **T015**：只读在线检查回归
  **类型**：测试
  **文件**：`src/backend/test/core/test_credential_checks.py`
  **逻辑**：SDK 边界替身验证新连接/只读操作/关闭资源，component 子集不等于 enforce，不写对象和队列。
  **覆盖 AC**：AC-09, AC-11, AC-14, AC-17, AC-20, AC-21, AC-23, AC-27, AC-40, AC-41
  **依赖**：T014

- [x] **T016**：在线只读检查
  **类型**：实现
  **文件**：`src/backend/bisheng/core/config/credential_checks.py`、`src/backend/bisheng/core/config/credential_tool.py`
  **逻辑**：同 Settings 参数，新建 SDK 连接，只读 probe、不初始化业务上下文、不降级 TLS，错误脱敏。
  **覆盖 AC**：AC-09, AC-11, AC-14, AC-17, AC-20, AC-21, AC-23, AC-27, AC-40, AC-41
  **依赖**：T015
  **配对测试**：T015；绿阶段及 L1 审查通过后完成。

### Wave 4 · 部署

> 2026-11-16：T024～T027、T042 以及 T037、T043、T109 中的 Helm 部分移出本次范围。`docker/helm/bisheng` 已恢复到治理前，`src/backend/test/deploy/test_credential_helm.py` 已删除。这些任务不再作为本次交付。

- [x] **T017**：安装包装器回归
  **类型**：测试
  **文件**：`src/backend/test/deploy/test_credential_install.py`
  **逻辑**：Docker 命令替身/临时 env，验证 prepare-only 无拉取/启动、无需宿主 Python、无秘密 argv、网络/挂载限制。
  **覆盖 AC**：AC-06, AC-08, AC-09, AC-10, AC-37, AC-38
  **依赖**：T014

- [x] **T018**：宿主工具包装
  **类型**：实现
  **文件**：`docker/credentials.sh`
  **逻辑**：docker run 指定后端镜像；离线 network none，输入/key 只读，不继承主机秘密环境，不依赖主 Compose 未生成变量。
  **覆盖 AC**：AC-06, AC-08, AC-09, AC-10, AC-37, AC-38
  **依赖**：T017
  **配对测试**：T017；绿阶段及 L1 审查通过后完成。

- [x] **T019**：分阶段安装
  **类型**：实现
  **文件**：`docker/install.sh`、`docker/.env.example`
  **逻辑**：本次密码改路径引用；prepare-only 已有配置时缺本地镜像明确失败；首次仅结构校验；正常安装按准备/初始化/检查/应用阶段，真实改密不自动执行。
  **覆盖 AC**：AC-07, AC-09, AC-10, AC-12, AC-37
  **依赖**：T017, T018
  **配对测试**：T017；绿阶段及 L1 审查通过后完成。

- [x] **T020**：Compose 原生联动回归
  **类型**：测试
  **文件**：`src/backend/test/deploy/test_credential_compose.py`
  **逻辑**：渲染与命令替身核查全部 native/key/业务密文来源；固定依赖顺序，无秘密 env/argv，不扩大权限。
  **覆盖 AC**：AC-03, AC-06, AC-12, AC-13, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-33, AC-35, AC-37
  **依赖**：T012

- [x] **T021**：Compose 凭据挂载
  **类型**：基础设施
  **文件**：`docker/docker-compose.yml`
  **逻辑**：bundle/native/key 最小挂载，删除本次旧密码 env 覆盖；覆盖 API/Worker/OpenFGA/Gateway/Milvus 对象存储。
  **覆盖 AC**：AC-03, AC-06, AC-12, AC-15, AC-17, AC-18, AC-21, AC-24, AC-37
  **依赖**：T019, T020
  **配对测试**：T020；绿阶段及 L1 审查通过后完成。

- [x] **T022**：MySQL 与初始化适配
  **类型**：实现
  **文件**：`docker/gateway/init.sh`、`docker/mysql/credential-health.sh`
  **逻辑**：defaults-extra-file 替代 MYSQL_PWD/参数密码，保留既有建库职责；check SELECT1 只读，初始化不自动修改已有账号。
  **覆盖 AC**：AC-06, AC-12, AC-13, AC-14, AC-33
  **依赖**：T020, T021
  **配对测试**：T020；绿阶段及 L1 审查通过后完成。

- [x] **T023**：Redis/Milvus 原生入口
  **类型**：实现
  **文件**：`docker/redis/credential-health.sh`、`docker/milvus/credential-entrypoint.sh`
  **逻辑**：Redis 文件读取后仅进程内 REDISCLI_AUTH；Milvus 原生配置加载并 exec；无 xtrace、自动关闭认证或猜测路径。
  **覆盖 AC**：AC-06, AC-15, AC-16, AC-17, AC-18, AC-24, AC-25, AC-26, AC-27
  **依赖**：T020, T021
  **配对测试**：T020；绿阶段及 L1 审查通过后完成。

- [ ] **T024**：Helm 外部 Secret 回归（2026-11-16 移出范围）
  **类型**：测试
  **文件**：`src/backend/test/deploy/test_credential_helm.py`（已删除）
  **逻辑**：不再交付。Chart 已恢复到治理前，不验收外部凭据 Secret。
  **覆盖 AC**：AC-39（已移出范围）
  **依赖**：无

- [ ] **T025**：Helm 输入契约（2026-11-16 移出范围）
  **类型**：基础设施
  **文件**：`docker/helm/bisheng/values.yaml`、`docker/helm/bisheng/templates/_helpers.tpl`（已恢复）
  **逻辑**：不再交付。不增加 `credentials.existingSecret` 或 `configRevision`。
  **覆盖 AC**：AC-39（已移出范围）
  **依赖**：无

- [ ] **T026**：Helm API/Worker 挂载（2026-11-16 移出范围）
  **类型**：基础设施
  **文件**：`docker/helm/bisheng/templates/backend-deployment.yaml`、`docker/helm/bisheng/templates/worker-deployment.yaml`（已恢复）
  **逻辑**：不再交付。不改为凭据 Secret 挂载。
  **覆盖 AC**：AC-39（已移出范围）
  **依赖**：无

- [ ] **T027**：Helm Linsight/Secret（2026-11-16 移出范围）
  **类型**：基础设施
  **文件**：`docker/helm/bisheng/templates/linsight-deployment.yaml`、`docker/helm/bisheng/templates/secret.yaml`（已恢复）
  **逻辑**：不再交付。不改 Helm 中的凭据 Secret。
  **覆盖 AC**：AC-39（已移出范围）
  **依赖**：无

- [ ] **T042**：Helm 原有 ConfigMap 接线收口（2026-11-16 移出范围）
  **类型**：基础设施
  **文件**：`docker/helm/bisheng/templates/configmap-config.yaml`、`docker/helm/bisheng/templates/configmap-nginx.yaml`（已恢复）
  **逻辑**：不再交付。ConfigMap 接线恢复治理前行为。
  **覆盖 AC**：AC-39（已移出范围）
  **依赖**：无

- [x] **T043**：清理配套发布模板的旧密码来源
  **类型**：基础设施
  **文件**：`docker/bisheng/config/config.yaml`。`docker/helm/bisheng/files/config.yaml` 已于 2026-11-16 恢复，不再属于本任务。
  **逻辑**：Compose 模板不携带可用旧密码/固定 key 密文；拓扑默认值为非秘密常量，客户已有文件不覆盖。Helm 模板不在本次范围。
  **覆盖 AC**：AC-01, AC-07, AC-08, AC-11
  **依赖**：T012, T019
  **配对测试**：T010, T013；配套模板完整 CLI 测试通过。

### Wave 5 · 存量维护

- [x] **T028**：断点重加密回归
  **类型**：测试
  **文件**：`src/backend/test/core/test_credential_rewrap.py`
  **逻辑**：新旧 token、空/坏值、未知 JSON、journal 落后/第三值冲突，磁盘失败先于提交和幂等。
  **覆盖 AC**：AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35
  **依赖**：T004

- [x] **T029**：重加密纯逻辑
  **类型**：基础设施
  **文件**：`src/backend/bisheng/core/config/credential_rewrap.py`
  **逻辑**：不依赖业务模型的计划、受控密文备份/fsync、状态机/resume，缓存待处理不能完成。
  **覆盖 AC**：AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35
  **依赖**：T028
  **配对测试**：T028；绿阶段及 L1 审查通过后完成。

- [x] **T030**：数据库维护回归
  **类型**：测试
  **文件**：`src/backend/test/credential_security/test_rewrap_runtime.py`
  **逻辑**：多租户组织/全局沙箱夹具；原时间、未知字段、批事务/CACHE_PENDING/重试和无关体系不动。
  **覆盖 AC**：AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-36
  **依赖**：T029

- [x] **T031**：显式维护脚本
  **类型**：实现
  **文件**：`src/backend/scripts/rewrap_credentials.py`、`src/backend/scripts/rewrap_credentials.sh`
  **逻辑**：同 settings，默认 dry-run，apply/all-tenants 显式；ORM 锁/事务每批100，精确字段；缓存阶段正确初始化/关闭上下文，resume 状态真实。
  **覆盖 AC**：AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-36
  **依赖**：T030
  **配对测试**：T030；绿阶段及 L1 审查通过后完成。

### Wave 6 · 集成及交付

- [x] **T034**：真实组件集成测试
  **类型**：测试
  **文件**：`src/backend/test/credential_security/test_live_middleware.py`、`src/backend/test/credential_security/conftest.py`
  **逻辑**：显式选择锁定镜像组合，新装/存量/失败恢复用真实连接和专用数据验证；无环境标未执行，不降低断言。
  **覆盖 AC**：AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-33, AC-34, AC-35, AC-36, AC-41, AC-42
  **依赖**：T016, T022, T023

- [ ] **T035**：双 DB 迁移集成测试
  **类型**：测试
  **文件**：`src/backend/test/credential_security/test_live_rewrap.py`
  **逻辑**：MySQL/DM 同夹具验证 tenant/时间/JSON/原生事务锁、磁盘缓存故障和恢复不覆盖新记录。
  **覆盖 AC**：AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-36, AC-42
  **依赖**：T031

- [x] **T036**：运维与源码手册
  **类型**：文档
  **文件**：`docker/中间件凭据运维手册.html`、`src/backend/scripts/README.md`
  **逻辑**：实际入口、角色/备份/停写/新连接验证/恢复，key 全丢不可逆、旧签名 URL、在途任务核对、source/systemd 与未验证边界。
  **覆盖 AC**：AC-07, AC-10, AC-13, AC-16, AC-19, AC-22, AC-23, AC-25, AC-26, AC-28, AC-30, AC-33, AC-34, AC-35, AC-36, AC-38, AC-41, AC-42
  **依赖**：T022, T023, T031

- [x] **T037**：部署手册
  **类型**：文档
  **文件**：`docker/README.md`。`docker/helm/README.md` 已于 2026-11-16 恢复，Helm 凭据说明不再属于本任务。
  **逻辑**：env/config 职责、bundle 激活/recreate 和中间件真实改密责任，check 不替代业务验收。Helm 不在本次范围。
  **覆盖 AC**：AC-11, AC-37, AC-40, AC-41, AC-42
  **依赖**：T019, T027, T036

- [ ] **T038**：最终交付回归
  **类型**：测试
  **文件**：`features/v3.1.0-beta2/003-middleware-credential-security/verification.md`
  **逻辑**：执行适用单测、既有兼容回归、格式/架构守卫、镜像/双 DB/E2E/恢复并留证据；缺环境明确未执行、相关任务不打勾；不在本任务修改未声明产品文件。
  **覆盖 AC**：AC-01～AC-47（含本次原入口返工的真实部署验收）
  **依赖**：T044～T053, T009, T016, T022, T023, T027, T031, T033, T034, T035, T036, T037

### Wave 7 · 已确认返工：原命令无感部署

以下返工已获用户“OK，开始返工”授权。每项完成后按task-review检查目标文件、配对测试、依赖、设计同步；L1记录见task-reviews.md。

- [x] **T044**：原命令和真实终端回归
  **类型**：测试
  **文件**：`src/backend/test/deploy/test_credential_one_command.py`、`src/backend/test/deploy/test_credential_install.py`
  **逻辑**：两个原入口、真实离线加密；隐藏输入/确认、重复/失败/丢失/锁、旧部署断点及不重建原生组件。
  **覆盖 AC**：AC-43, AC-44, AC-45, AC-46, AC-47
  **依赖**：T017

- [x] **T045**：自动引导CLI与旧环境快照回归
  **类型**：测试
  **文件**：`src/backend/test/core/test_credential_tool.py`、`src/backend/test/core/test_credential_bundle.py`
  **逻辑**：缺key可列需求/校验输入；密钥合并不覆盖/不泄漏；旧容器!env物化与坏快照拒绝。
  **覆盖 AC**：AC-43, AC-44, AC-45, AC-46, AC-47
  **依赖**：T010, T013

- [x] **T046**：原入口状态与迁移向导
  **类型**：基础设施
  **文件**：`docker/lib/credential-install.sh`、`docker/lib/credential-migrate.sh`
  **逻辑**：受限目录、锁、TTY、私有输入与prepared指针；授权停写、旧身份导入、数据库计划续跑；不自动改账号。
  **覆盖 AC**：AC-43, AC-44, AC-45, AC-46, AC-47
  **依赖**：T044, T045
  **配对测试**：T044/T045及安装静态契约；本地绿阶段与L1通过，真实交付门禁不因此完成。

- [x] **T047**：内部CLI及快照解析
  **类型**：基础设施
  **文件**：`src/backend/bisheng/core/config/credential_tool.py`、`src/backend/bisheng/core/config/credential_bundle.py`
  **逻辑**：requirements/validate-inputs/validate-keyring/join-keyrings；严格读取runtime-env，物化迁移来源。
  **覆盖 AC**：AC-43, AC-44, AC-45, AC-46, AC-47
  **依赖**：T045
  **配对测试**：T044/T045及安装静态契约；本地绿阶段与L1通过，真实交付门禁不因此完成。

- [x] **T048**：原安装器接回与自动参数
  **类型**：实现
  **文件**：`docker/install.sh`、`docker/.env.example`
  **逻辑**：无参数安装、权限/版本自动保存、prepare-only结构模式；保留Gateway/registry和显式维护参数。
  **覆盖 AC**：AC-43, AC-44, AC-45, AC-46, AC-47
  **依赖**：T044, T046, T047
  **配对测试**：T044/T045及安装静态契约；本地绿阶段与L1通过，真实交付门禁不因此完成。

- [x] **T049**：宿主包装兼容和旧安装回归
  **类型**：基础设施
  **文件**：`docker/credentials.sh`、`scripts/tests/compose/test-install.sh`
  **逻辑**：新只读路径选项及Bash3.2空数组兼容；免宿主Python、registry/Gateway/compose两种入口契约。
  **覆盖 AC**：AC-43, AC-44, AC-45, AC-46, AC-47
  **依赖**：T044, T048
  **配对测试**：T044/T045及安装静态契约；本地绿阶段与L1通过，真实交付门禁不因此完成。

- [x] **T050**：静态Compose门禁接线
  **类型**：基础设施
  **文件**：`scripts/tests/compose/verify-app-runtime-compose.sh`、`.github/workflows/app-runtime-quality.yml`
  **逻辑**：静态检查使用不落盘的非秘密路径及模板env，计入只读健康检查拆出的mysql-init；不要求CI密码。
  **覆盖 AC**：AC-43, AC-44, AC-45, AC-46, AC-47
  **依赖**：T048
  **配对测试**：T044/T045及安装静态契约；本地绿阶段与L1通过，真实交付门禁不因此完成。

- [x] **T051**：原命令HTML SOP与安装说明
  **类型**：文档
  **文件**：`docker/中间件凭据运维手册.html`、`docker/README.md`
  **逻辑**：主线仅原命令及必要引导，区分新装/重复/旧版/失败，明确备份和待验边界；撤销旧Markdown SOP交付。
  **覆盖 AC**：AC-43, AC-44, AC-45, AC-46, AC-47
  **依赖**：T048, T049

- [x] **T052**：维护文档链接同步
  **类型**：文档
  **文件**：`src/backend/scripts/README.md`。`docker/helm/README.md` 已于 2026-11-16 恢复，不再承载本次凭据说明。
  **逻辑**：脚本索引指向新版 HTML 手册。Helm 不混入本次单机安装，也不在本次范围。
  **覆盖 AC**：AC-43, AC-44, AC-45, AC-46, AC-47
  **依赖**：T051

- [x] **T053**：方案HTML修正入口
  **类型**：文档
  **文件**：`docs/中间件密码与配置加密治理方案.html`
  **逻辑**：完整同步15章正文、原入口/场景SVG、当前加密契约、实际代码索引和验收状态；区分改造前/当前/待验，取消日常安装人工前置，工具仅作内部能力及专项维护参考。
  **覆盖 AC**：AC-43, AC-44, AC-45, AC-46, AC-47
  **依赖**：T051

### Wave 8 · 真实验收发现的MySQL初始化修复（2026-11-13）

- [x] **T054**：MySQL原生特殊字符回归
  **类型**：测试
  **文件**：`src/backend/test/deploy/test_mysql_credential_entrypoint.py`、`src/backend/test/deploy/test_credential_compose.py`
  **逻辑**：真实新装发现单引号导致vendor初始化SQL错误；验证SQL/CNF字面量、反引号、无命令执行、原密码不变及拒绝随机/空值，固定wrapper接线。
  **覆盖 AC**：AC-06, AC-11, AC-12, AC-43, AC-46
  **依赖**：T044, T048

- [x] **T055**：MySQL原生安全初始化适配
  **类型**：基础设施
  **文件**：`docker/mysql/credential-entrypoint.sh`、`docker/docker-compose.yml`
  **逻辑**：在原生命周期上只替换bootstrap SQL/CNF序列化；root降权后保留安全helper，标准mysql用户启动，不自动改已有账号。
  **覆盖 AC**：AC-06, AC-11, AC-12, AC-43, AC-46
  **依赖**：T054
  **配对测试**：T054；单测通过；同一含单引号密码真实新装成功，TCP认证通过、无密码socket被拒绝，L1见task-reviews.md。

## 实际偏差记录

- 复用现有配置格式、算法和账号权限决策不变。为完成既有调用链接入，增加 T039–T043：RedisClient single dict、旧沙箱断言、两个 Helm ConfigMap 以及两个发布模板；每项不超过两个文件。
- 原 MySQL 健康检查的建库职责移到显式 mysql-init 一次性服务，以保证健康检查只读；没有删除既有 OpenFGA 建库能力。
- 本地 Helm 缺失后从官方获取临时3.17.4二进制并校验SHA256，已完成实际渲染/lint。Docker 可读取缓存上游镜像，实际隔离容器因远程路径/创建超时未完成，已清理；私有镜像/DM与全业务仍待验证。
- 真实组件测试代码已写，9项因未提供显式隔离环境跳过；T034/T035/T038 保留未完成，QA参考表不回填为通过。

### 真实验收发现的缓存生命周期修复

- [x] **T056**：缓存清理保留既有数据库上下文回归
  **类型**：测试
  **文件**：`src/backend/test/credential_security/test_rewrap_runtime.py`
  **逻辑**：真实内存数据库消费者在缓存删除成功/失败后仍可读取；只模拟Redis网络边界；红阶段两项失败。
  **覆盖 AC**：AC-30, AC-33, AC-34, AC-35, AC-36
  **依赖**：T031

- [x] **T057**：维护缓存连接生命周期隔离
  **类型**：基础设施
  **文件**：`src/backend/scripts/rewrap_credentials.py`
  **逻辑**：独立Redis连接删除指定缓存并仅关闭自身；保留现有DB上下文供主密钥复检；失败不标完成。
  **覆盖 AC**：AC-30, AC-33, AC-34, AC-35, AC-36
  **依赖**：T056
  **配对测试**：T056；成功/失败两项回归变绿；同一真实中断现场续跑退出0，COMPLETE=3，新主密钥独立复检通过，密文未重复改写。

### 真实验收发现的维护工具挂载修复

- [x] **T058**：同目录输入与输出挂载回归
  **类型**：测试
  **文件**：`src/backend/test/deploy/test_credential_install.py`
  **逻辑**：输入清单和输出配置包共用父目录，两种参数顺序均只挂载一次并允许显式输出；使用系统Bash3.2。
  **覆盖 AC**：AC-37, AC-42
  **依赖**：T009

- [x] **T059**：合并维护工具重复挂载
  **类型**：基础设施
  **文件**：`docker/credentials.sh`
  **逻辑**：精确相同目标只生成一个bind mount；显式输出授权的父目录合并为可写，其余只读；不引入宿主Python和秘密环境透传。
  **覆盖 AC**：AC-37, AC-42
  **依赖**：T058
  **配对测试**：T058；本地两种顺序绿、真实五组件password-change准备成功，L1见task-reviews.md。

## 完成规则

- T038 包含项目强制 /e2e-test 与 /sdd-code-review；不能仅靠本地单测标记完整交付。
- 镜像入口与 UID/GID 必须在接入真实部署前验证；相关环境不可用时，保留待验证状态。
- 不执行提交、推送、合并或客户实际改密，除非另有明确授权。

## Wave 8 · 用户已确认：原入口选择改密

新增自动化按已确认spec/design的风险独立设计，不以QA参考表作为任务执行器输入。每项最多两个目标文件，完成后进行task-review。

- [x] **T060**：计划与检查点安全回归
  **类型**：测试
  **文件**：src/backend/test/core/test_credential_rotation.py
  **逻辑**：纯状态、子账号部分完成、未知认证拒绝区分、秘密不外泄、持久化失败、请求幂等
  **覆盖 AC**：AC-48, AC-50, AC-52, AC-54, AC-56
  **依赖**：T059

- [x] **T061**：改密计划及阶段状态
  **类型**：基础设施
  **文件**：src/backend/bisheng/core/config/credential_rotation.py
  **逻辑**：不可变计划、阶段配置/基线、私有持久化、输入摘要和状态核实决策
  **覆盖 AC**：AC-48, AC-50, AC-52, AC-54, AC-56
  **依赖**：T060
  **配对测试**：T060

- [x] **T062**：原生管理适配回归
  **类型**：测试
  **文件**：src/backend/test/credential_security/test_rotation_native.py
  **逻辑**：新旧正反认证、管理预检、MySQL子账号、Redis权限、ES/Milvus状态未知、MinIO重建判定
  **覆盖 AC**：AC-50, AC-51, AC-52, AC-53, AC-54, AC-55
  **依赖**：T061

- [x] **T063**：原生管理与显式维护入口
  **类型**：基础设施
  **文件**：src/backend/bisheng/core/config/credential_rotation_native.py；src/backend/bisheng/core/config/credential_rotation_cli.py
  **逻辑**：纯SDK管理/预检/脱敏、显式执行及恢复；容器内无Docker访问
  **覆盖 AC**：AC-50, AC-51, AC-52, AC-53, AC-54, AC-55
  **依赖**：T062
  **配对测试**：T062

- [x] **T064**：原生编排保留回归
  **类型**：测试
  **文件**：src/backend/test/deploy/test_rotation_compose.py
  **逻辑**：已有配置/数据挂载/网络/未选项保留、消费者联动、变量字面量不再展开
  **覆盖 AC**：AC-49, AC-52, AC-55
  **依赖**：T061

- [x] **T065**：只转换受管原生配置
  **类型**：基础设施
  **文件**：src/backend/bisheng/core/config/credential_rotation_compose.py
  **逻辑**：从受限原部署快照生成目标native编排；拒绝未知归属，不操作Docker
  **覆盖 AC**：AC-49, AC-52, AC-55
  **依赖**：T064
  **配对测试**：T064

- [x] **T066**：改密内部CLI契约回归
  **类型**：测试
  **文件**：src/backend/test/deploy/test_rotation_cli.py
  **逻辑**：离线prepare与在线管理区分、能力协商、安全挂载和退出码
  **覆盖 AC**：AC-50, AC-51, AC-54, AC-56
  **依赖**：T061, T063, T065

- [x] **T067**：配套工具与内部CLI接线
  **类型**：基础设施
  **文件**：src/backend/bisheng/core/config/credential_tool.py；docker/credentials.sh
  **逻辑**：暴露内部改密命令和会话挂载；check仍只读，在线须显式网络
  **覆盖 AC**：AC-50, AC-51, AC-54, AC-56
  **依赖**：T066
  **配对测试**：T066

- [x] **T068**：原入口逐项选择与恢复回归
  **类型**：测试
  **文件**：src/backend/test/deploy/test_credential_rotation_install.py
  **逻辑**：真实PTY默认保留、单项/多项/取消、非交互、旧版先迁移、原命令续跑
  **覆盖 AC**：AC-48, AC-49, AC-50, AC-51, AC-54, AC-55, AC-56
  **依赖**：T067

- [x] **T069**：宿主原入口改密编排
  **类型**：基础设施
  **文件**：docker/lib/credential-rotate.sh；docker/install.sh
  **逻辑**：同入口选择输入、统一维护、快照、停写、原生生命周期和状态恢复
  **覆盖 AC**：AC-48, AC-49, AC-50, AC-51, AC-52, AC-53, AC-54, AC-55, AC-56
  **依赖**：T068
  **配对测试**：T068

- [x] **T070**：部分治理及下一次复用回归
  **类型**：测试
  **文件**：src/backend/test/core/test_rotation_policy.py；src/backend/test/deploy/test_credential_rotation_install.py
  **逻辑**：未选弱值保留但不冒充全治理、策略篡改拒绝、后续普通部署不误改
  **覆盖 AC**：AC-49, AC-52, AC-56
  **依赖**：T069

- [x] **T071**：部署策略和复用接线
  **类型**：基础设施
  **文件**：src/backend/bisheng/core/config/credential_rotation.py；docker/lib/credential-install.sh
  **逻辑**：绑定导入基线和实际变更，受控保留未选状态，全局enforce语义不变
  **覆盖 AC**：AC-49, AC-52, AC-56
  **依赖**：T070
  **配对测试**：T070

- [x] **T072**：隔离真实选择改密验收
  **类型**：测试
  **文件**：src/backend/test/credential_security/test_live_rotation.py；src/backend/test/credential_security/conftest.py
  **逻辑**：五单选、多选/全部、持久化与故障恢复；用户追加授权后在166独立服务栈改密验收，不修改原部署；未运行不勾选
  **覆盖 AC**：AC-48, AC-49, AC-50, AC-51, AC-52, AC-53, AC-54, AC-55, AC-56
  **依赖**：T071

- [x] **T073**：新增脚本与设计同步
  **类型**：文档
  **文件**：src/backend/scripts/README.md；features/v3.1.0-beta2/003-middleware-credential-security/design.md
  **逻辑**：同步内部边界、实际适配与未验证状态，不增加运维必做命令
  **覆盖 AC**：AC-51, AC-54, AC-55
  **依赖**：T071

- [x] **T074**：运维与部署说明同步
  **类型**：文档
  **文件**：docker/中间件凭据运维手册.html；docker/README.md
  **逻辑**：原入口选择、影响、恢复和限制；手册不提前宣称已验证
  **覆盖 AC**：AC-48, AC-49, AC-50, AC-54, AC-55, AC-56
  **依赖**：T071

- [x] **T075**：方案及增量验证证据
  **类型**：文档
  **文件**：docs/中间件密码与配置加密治理方案.html；features/v3.1.0-beta2/003-middleware-credential-security/verification.md
  **逻辑**：如实记录自动化、实际组件、E2E/L2与剩余门禁
  **覆盖 AC**：AC-48, AC-49, AC-50, AC-51, AC-52, AC-53, AC-54, AC-55, AC-56
  **依赖**：T072, T073, T074

## Wave 9 · 真实 Linux 验收发现的修复与证据

既有 AC 的实现修正，不增加运维命令。用户于2026-11-13授权使用192.168.106.166；仅使用独立项目和数据，原部署保留。

- [x] **T076**：Linux秘密文件和整批认证预检回归
  **类型**：测试
  **文件**：src/backend/test/deploy/test_redis_credential_entrypoint.py；src/backend/test/credential_security/test_rotation_native.py
  **逻辑**：验证降权保留补充组、整批预检只读、双通或未知认证状态写入前拒绝。
  **覆盖 AC**：AC-37, AC-49, AC-50, AC-51, AC-55
  **依赖**：T071

- [x] **T077**：Redis受控降权和标准部署接线
  **类型**：基础设施
  **文件**：docker/redis/credential-entrypoint.sh；docker/docker-compose.yml
  **逻辑**：保留redis UID/GID与Docker授予的补充组，不放宽0640秘密文件权限。
  **覆盖 AC**：AC-37, AC-49, AC-51
  **依赖**：T076

- [x] **T078**：原生编排和宿主整批预检接线
  **类型**：基础设施
  **文件**：src/backend/bisheng/core/config/credential_rotation_compose.py；docker/lib/credential-rotate.sh
  **逻辑**：复用受控入口，核对工具、文件与支持的原生命令；整批认证核实后才允许账号写入。
  **覆盖 AC**：AC-49, AC-50, AC-51, AC-54, AC-55
  **依赖**：T077

- [x] **T079**：SDK和CLI整批只读预检
  **类型**：基础设施
  **文件**：src/backend/bisheng/core/config/credential_rotation_native.py；src/backend/bisheng/core/config/credential_rotation_cli.py
  **逻辑**：核实所有选中项的新旧认证，拒绝双通、未知状态和持久化检查点漂移，不写账号。
  **覆盖 AC**：AC-50, AC-51, AC-54, AC-55
  **依赖**：T076

- [x] **T080**：真实业务和原数据保留探针
  **类型**：测试
  **文件**：src/backend/test/credential_security/probes/business_probe.py；src/backend/test/credential_security/probes/data_probe.py
  **逻辑**：显式隔离标记下验证Nginx、账号、管理租户、知识上传下载检索、非所有者拒绝和五类原记录。
  **覆盖 AC**：AC-49, AC-51, AC-52
  **依赖**：T079

- [x] **T081**：真实Worker和确定性模型夹具
  **类型**：测试
  **文件**：src/backend/test/credential_security/probes/worker_probe.py；src/backend/test/credential_security/probes/embedding_fixture.py
  **逻辑**：真实队列往返和任务执行；向量模型用明确标识的测试提供者，不评价模型质量。
  **覆盖 AC**：AC-49, AC-51, AC-52
  **依赖**：T079

- [x] **T082**：ES最终进程就绪回归和接线
  **类型**：基础设施
  **文件**：docker/install.sh；src/backend/test/deploy/test_credential_one_command.py
  **逻辑**：新装和复用也等待最终Java主进程，避免临时JVM造成健康检查提前通过。
  **覆盖 AC**：AC-45, AC-49, AC-51
  **依赖**：T069

- [x] **T083**：探针误用保护回归
  **类型**：测试
  **文件**：src/backend/test/credential_security/test_probe_safety.py
  **逻辑**：未显式授权隔离环境或缺少所有权标记时拒绝执行。
  **覆盖 AC**：AC-51, AC-55
  **依赖**：T080, T081

## Wave 10～后续 · 已确认v2设计（2026-11-14）

新增任务从spec/design独立拆解；QA仅为人工参考。测试先于配对实现，现有81/83为v1历史；无业务表/SQL迁移，Celery headers→ContextVar契约不变。当前工作区实施，不创建分支。

> **2026-11-15 选项 C**：拆除 Go `credential-runtime` 与原生 `sealed-files-v2` 交付门禁。下列 **T086～T091**（Go 协议/静态工具/镜像内置）及原「内存 tmpfs / 子 key 挂载」表述**废止为交付依据**；保留勾选仅表示历史已完成过密封路径实现。现行依据见 `design.md` §4.14（选项 C）与附录 A。相关回归以 `test_credential_runtime_build.py`（断言不再交付 Go）、`test_credential_sealed_compose.py`（明文 `/run/secrets`）为准。

- [x] **T084**：Python加密工件契约
  **类型**：测试
  **文件**：src/backend/test/core/test_credential_artifacts.py
  **逻辑**：Fernet、角色派生、跨部署/版本拒绝、路径/重复字段、坏key及无明文落盘断言。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-57, AC-58, AC-59, AC-67, AC-70
  **依赖**：T083

- [x] **T085**：认证加密工件实现
  **类型**：基础设施
  **文件**：src/backend/bisheng/core/config/credential_artifacts.py
  **逻辑**：实现前驱测试固定的seal/open、角色key派生、私有原子文件写入和非敏感身份校验。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-58, AC-59, AC-67, AC-70
  **依赖**：T084

- [x] **T086**：Go协议互通测试与依赖锁 · **选项 C 废止交付**
  **类型**：测试（历史）
  **文件**：~~src/backend/tools/credential-runtime/protocol_test.go~~（目录已拆除）
  **逻辑**：原 Go↔Python 协议测试。选项 C 后不再维护 Go 树；加密契约以 Python `credential_artifacts` 单测为准。
  **覆盖 AC**：AC-59, AC-67, AC-70（历史）
  **依赖**：T085

- [x] **T087**：Go静态解密与key读取 · **选项 C 废止交付**
  **类型**：基础设施（历史）
  **文件**：~~src/backend/tools/credential-runtime/protocol.go~~（目录已拆除）
  **逻辑**：原 Go 解密实现。选项 C 后无对应交付物。
  **覆盖 AC**：AC-58, AC-59, AC-67, AC-70（历史）
  **依赖**：T086

- [x] **T088**：Go内存文件与环境断言 · **选项 C 废止交付**
  **类型**：测试（历史）
  **文件**：~~src/backend/tools/credential-runtime/runtime_test.go~~（目录已拆除）
  **逻辑**：原 tmpfs/exec 断言。选项 C 改为明文 `/run/secrets` 挂载验收。
  **覆盖 AC**：AC-61, AC-62, AC-63, AC-66（历史）
  **依赖**：T087

- [x] **T089**：静态启动与受控内存恢复 · **选项 C 废止交付**
  **类型**：基础设施（历史）
  **文件**：~~src/backend/tools/credential-runtime/main.go~~（目录已拆除）
  **逻辑**：原 Go 启动垫片。选项 C 后 Compose 直接挂载明文原生文件。
  **覆盖 AC**：AC-61, AC-62, AC-63, AC-66（历史）
  **依赖**：T088

- [x] **T090**：构建与工具提取回归 · **选项 C 改义**
  **类型**：测试
  **文件**：src/backend/test/deploy/test_credential_runtime_build.py
  **逻辑**：断言 Dockerfile/安装器**不再**构建或提取 Go credential-runtime；`credential-runtime.sh` 为 Option C 占位。
  **覆盖 AC**：AC-57, AC-59, AC-70
  **依赖**：T089

- [x] **T091**：配套镜像内置静态工具 · **选项 C 改义**
  **类型**：基础设施
  **文件**：src/backend/Dockerfile; docker/lib/credential-runtime.sh
  **逻辑**：镜像不携带 `/opt/bisheng/credential-runtime`；安装器不提取 Go 二进制。仅保留 Python `credential_tool`。
  **覆盖 AC**：AC-57, AC-61, AC-70
  **依赖**：T090

- [x] **T092**：完整v2包与检查回归
  **类型**：测试
  **文件**：src/backend/test/core/test_credential_sealed_bundle.py
  **逻辑**：新装、单项、保留、完整native payload一致性及v1只读导入配对，扫描所有输出。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-59, AC-63, AC-67
  **依赖**：T091

- [x] **T093**：配置包渲染和校验接线
  **类型**：基础设施
  **文件**：src/backend/bisheng/core/config/credential_bundle.py; src/backend/bisheng/core/config/credential_tool.py
  **逻辑**：内存渲染后按角色seal，check内存解密检查，manifest明确v2，不默认输出明文。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-59, AC-63, AC-67
  **依赖**：T092

- [x] **T094**：加密输入与stdin回归
  **类型**：测试
  **文件**：src/backend/test/core/test_credential_sealed_inputs.py
  **逻辑**：不产生明文中间文件，坏密文/缺key/取消及旧版导入区别，不把用户名当密码。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-59, AC-60, AC-67
  **依赖**：T093

- [x] **T095**：输入与工件CLI
  **类型**：基础设施
  **文件**：src/backend/bisheng/core/config/credential_inputs.py; src/backend/bisheng/core/config/credential_artifact_cli.py
  **逻辑**：受控stdin直接seal，v2自动化读取和v1明确导入，固定能力标识与子key输出。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-59, AC-60, AC-67, AC-70
  **依赖**：T094

- [x] **T096**：原入口密文输入PTY回归
  **类型**：测试
  **文件**：src/backend/test/deploy/test_credential_sealed_install.py
  **逻辑**：普通账号提示、逐项保留、取消、密钥先于输入准备、无argv/env秘密及自动化默认不抢占。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-57, AC-58, AC-60, AC-70
  **依赖**：T095

- [x] **T097**：宿主输入与工具管道
  **类型**：基础设施
  **文件**：docker/lib/credential-install.sh; docker/credentials.sh
  **逻辑**：替换printf落明文为stdin工具管道；显式key挂载和新能力接线，沿用read-s确认。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-57, AC-58, AC-60, AC-70
  **依赖**：T096

- [x] **T098**：原生明文挂载与角色接线（选项 C）
  **类型**：测试
  **文件**：src/backend/test/deploy/test_credential_sealed_compose.py
  **逻辑**：逐服务明文 `/run/secrets`（及 OpenFGA/Milvus 路径）挂载；无 Go 垫片、无 `/run/bisheng-secrets`；保留数据卷与原生入口。
  **覆盖 AC**：AC-57, AC-58, AC-61, AC-62, AC-63
  **依赖**：T097

- [x] **T099**：标准Compose明文适配（选项 C）
  **类型**：基础设施
  **文件**：docker/docker-compose.yml; docker/lib/credential-runtime.sh
  **逻辑**：原生服务 bind 明文凭据文件；backend/worker 挂主 key；`credential-runtime.sh` 不再提取 Go 工具。
  **覆盖 AC**：AC-57, AC-58, AC-61, AC-62, AC-63, AC-66
  **依赖**：T098

- [x] **T100**：改密敏感状态与阶段加密
  **类型**：测试
  **文件**：src/backend/test/core/test_credential_sealed_rotation.py
  **逻辑**：inputs/inventory/env/source/stages与恢复敏感内容均密文；计划完整性及重复请求保持。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-59, AC-64, AC-65, AC-67, AC-69
  **依赖**：T099

- [x] **T101**：改密状态密文接口
  **类型**：基础设施
  **文件**：src/backend/bisheng/core/config/credential_rotation.py; src/backend/bisheng/core/config/credential_rotation_cli.py
  **逻辑**：敏感payload封装并内存恢复，非秘密journal和身份意图保留；完成后发布完整v2版本。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-59, AC-64, AC-65, AC-67, AC-69
  **依赖**：T100

- [x] **T102**：真实配置捕获和重建回归
  **类型**：测试
  **文件**：src/backend/test/deploy/test_credential_sealed_recreate.py
  **逻辑**：捕获流不落明文，未知布局拒绝，受管实际原生配置内存归属和MinIO/Milvus联动。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-59, AC-61, AC-63, AC-65
  **依赖**：T101

- [x] **T103**：原生重建与捕获流接线
  **类型**：基础设施
  **文件**：src/backend/bisheng/core/config/credential_rotation_compose.py; docker/lib/credential-rotate.sh
  **逻辑**：捕获到seal stdin，编译v2挂载/入口，旧新认证和恢复保留不把配置只初始化当改密。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-59, AC-61, AC-63, AC-65
  **依赖**：T102

- [x] **T104**：v1转换与清理断点回归
  **类型**：测试
  **文件**：src/backend/test/core/test_credential_sealed_migration.py
  **逻辑**：保持原身份，从旧输入/历史完整计划转换、验证前不删，客户文件不擅删；中断原命令恢复。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-59, AC-64, AC-65, AC-69
  **依赖**：T103

- [x] **T105**：旧文件转换状态机与CLI
  **类型**：基础设施
  **文件**：src/backend/bisheng/core/config/credential_sealed_migration.py; src/backend/bisheng/core/config/credential_artifact_cli.py
  **逻辑**：实现已定义六阶段与加密备份、明确自有清单和恢复绑定，不回落v1明文。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-59, AC-64, AC-65, AC-69
  **依赖**：T104

- [x] **T106**：原命令旧版迁移和非root门禁
  **类型**：测试
  **文件**：src/backend/test/deploy/test_credential_sealed_migrate_install.py
  **逻辑**：权限失败在账号写前拒绝，迁移维护确认、重启后续跑与现有部署保护。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-57, AC-58, AC-62, AC-64, AC-65
  **依赖**：T105

- [x] **T107**：原入口迁移与就绪接线
  **类型**：基础设施
  **文件**：docker/lib/credential-sealed-migrate.sh; docker/install.sh
  **逻辑**：原入口识别v1/v2、前置安全/权限检查、受控停写切换、成组激活，不增加人工命令。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-57, AC-58, AC-62, AC-64, AC-65, AC-66
  **依赖**：T106

- [x] **T108**：实际非root与拒绝测试
  **类型**：测试
  **文件**：src/backend/test/credential_security/probes/sealed_fixture.py; src/backend/test/deploy/test_credential_sealed_install.py
  **逻辑**：隔离普通账号无sudo部署、未授权账号读key拒绝，rootless不混报；无Docker授权先拒绝。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-57, AC-58, AC-70
  **依赖**：T107

- [x] **T109**：权限与其他部署入口门禁（选项 C）
  **类型**：基础设施
  **文件**：docker/lib/credential-runtime.sh
  **逻辑**：复用部署账号已有组做明文文件权限。Helm 已于 2026-11-16 移出本次范围，不再在 Chart 中增加凭据门禁。
  **覆盖 AC**：AC-57, AC-58, AC-70
  **依赖**：T108

- [ ] **T110**：真实v2服务和故障恢复
  **类型**：测试
  **文件**：src/backend/test/credential_security/probes/sealed_fixture.py; src/backend/test/credential_security/probes/legacy_fixture.py
  **逻辑**：单组件新装/改密、整栈重建、原生写后故障续跑及强旧身份配对恢复。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-59, AC-61, AC-63, AC-64, AC-65, AC-66, AC-67
  **依赖**：T109

- [ ] **T111**：恢复及适配收口
  **类型**：基础设施
  **文件**：docker/lib/credential-rotate.sh; docker/lib/credential-sealed-migrate.sh
  **逻辑**：依据前驱真实失败修正，仅恢复加密材料，保持意图与身份核实，不降低断言。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-59, AC-61, AC-63, AC-64, AC-65, AC-66, AC-67
  **依赖**：T110

- [ ] **T112**：磁盘扫描与真实业务证据
  **类型**：测试
  **文件**：src/backend/test/credential_security/probes/sealed_scan.py; src/backend/test/credential_security/test_sealed_scan.py
  **逻辑**：已知原文/定义编码扫描目录、日志、卷、容器及镜像层；探针显式隔离标记和所有权保护。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-59, AC-63, AC-68, AC-69
  **依赖**：T111

- [ ] **T113**：166隔离普通账号验收夹具
  **类型**：基础设施
  **文件**：src/backend/test/credential_security/probes/sealed_fixture.py
  **逻辑**：管理员一次性设置隔离账号/目录和已有Docker授权；全部安装以该UID执行，精确资源标签，禁止重启共享主机。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-57, AC-58, AC-61, AC-62, AC-63, AC-64, AC-65, AC-66, AC-67, AC-68, AC-69, AC-70
  **依赖**：T112

- [ ] **T114**：增量E2E与L2审查
  **类型**：测试
  **文件**：features/v3.1.0-beta2/003-middleware-credential-security/verification.md; features/v3.1.0-beta2/003-middleware-credential-security/task-reviews.md
  **逻辑**：真实登录/知识检索/权限/Worker、静态和全范围扫描，记录未执行主机重启/DM，不冒充发布通过。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-57, AC-58, AC-59, AC-60, AC-61, AC-62, AC-63, AC-64, AC-65, AC-66, AC-67, AC-68, AC-69, AC-70
  **依赖**：T113

- [ ] **T115**：治理HTML和SOP同步
  **类型**：文档
  **文件**：docs/中间件密码与配置加密治理方案.html; docker/中间件凭据运维手册.html
  **逻辑**：说明密文文件与内存运行、普通账号前置条件和原命令恢复，不引入必需手工步骤。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-57, AC-59, AC-64, AC-65, AC-70
  **依赖**：T114

- [ ] **T116**：部署与维护说明同步
  **类型**：文档
  **文件**：docker/README.md; src/backend/scripts/README.md
  **逻辑**：实际支持、密钥权限、加密输入和版本限制同步，不宣称普通文件删除能安全擦除。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-57, AC-59, AC-64, AC-65, AC-69, AC-70
  **依赖**：T115

- [ ] **T117**：任务与验证最终收口
  **类型**：文档
  **文件**：features/v3.1.0-beta2/003-middleware-credential-security/tasks.md; features/v3.1.0-beta2/003-middleware-credential-security/verification.md
  **逻辑**：逐项核实证据再勾选，未完成真实环境项保持未完成，发布镜像和测试镜像分开。前驱产物只增量接入，不重写无关逻辑。
  **覆盖 AC**：AC-57, AC-58, AC-59, AC-60, AC-61, AC-62, AC-63, AC-64, AC-65, AC-66, AC-67, AC-68, AC-69, AC-70
  **依赖**：T116


## 2026-11-14：真实扫描发现的安全阻塞与补充任务

不是完整交付。Milvus 2.5.10 的原生复制流把 Base64 凭据写入持久 RocksMQ，AC-59/61 未通过；补充设计须按 SDD-Guide §3 重新确认。详见 design §4.14 起始说明与 HTML 增量验收报告。T110～T117不因此勾选。

- [x] **T118**：Milvus 持久凭据问题的整批拒绝门禁
  **类型**：安全修复与回归
  **文件**：src/backend/bisheng/core/config/credential_rotation_cli.py; src/backend/test/deploy/test_rotation_cli.py
  **逻辑**：在 capture/prepare/preflight/step 前拒绝包含 Milvus 改密的整批请求；已有混合计划也不得先联系原生服务或改变 journal。不是密码加密问题的最终修复。
  **覆盖 AC**：AC-59, AC-61, AC-62, AC-67
  **依赖**：T103
  **验证**：新增拒绝与无原生调用/无 journal 变化检查，纳入117项聚焦通过集合；Ruff和shell语法通过。实际配套镜像另行核对，不将本任务勾选解释为T110完成。

后续透明加密数据卷或修复 Milvus 镜像的任务，待补充设计确认后拆解；不预先实现FUSE、SYS_ADMIN或原生数据清理。


- [x] **T119**：按用户确认的 Milvus 原生消息例外撤销临时拒绝门禁
  **类型**：范围调整与回归
  **文件**：src/backend/bisheng/core/config/credential_rotation_cli.py; src/backend/test/deploy/test_rotation_cli.py
  **逻辑**：恢复正常混合计划身份预检；不新增文件系统或容器权限，历史发现与明确例外同步文档。
  **覆盖 AC**：AC-59/AC-61的Milvus原生消息明确例外，其他范围不变
  **依赖**：T118

T119 L1：CLI与加密状态聚焦回归8项通过，Ruff与diff检查通过。正常混合计划preflight调用原生身份预检，journal保持不变；没有把原生消息例外扩展为部署文件明文许可。


## 2026-11-14 当前 L1 收口（优先于上方历史阻塞）

T092～T109 的实现与针对性回归已核对，纳入专项 213 passed、无跳过；T104～T107 的清理恢复子集 17 passed。166 实际 UID 1000 新装、保留、五组件续跑及受管 v1 转换通过，未授权 UID 12031 读取主密钥拒绝，无 Docker 授权在账号写入前拒绝；rootless 为拒绝测试，不冒充 rootless 部署通过。T108/T110 的文件映射调整为实际使用的 opt-in PTY 夹具与迁移夹具，不虚构不存在的 pytest 文件。

修复实际旧文件清理缺失：要求完整 store 挂载、部署标识和签名 policy-root 匹配；COMPLETE 恢复不倒退状态；主密钥排除删除。实测旧文件 13→0，原命令 exit 0。单独 MinIO 改密及数据/业务/worker 验证通过，未选中原生服务 ID 保持不变。

T110 及之后保持未勾选：完整故障矩阵、最终扫描、L2 审查与发布范围尚未全部收口。HTML 已同步当前方案，但不以文档更新替代前驱验收。主机重启、DM 和最终发布镜像仍未验证。

## 2026-11-15：用户确认旧 ES 无认证升级，原命令接入

- [x] **T120**：服务端安全状态识别与交互选择。ES 8.12.0 单节点使用服务端安全设置及真实认证结果，未知状态阻断；原命令提示启用、保留或导入现用密码。覆盖 AC-71、AC-72。证据：core 与部署聚焦测试。
- [x] **T121**：密文迁移与原生 ES 切换。读取旧包并加密封存，捕获实际数据卷、端口、镜像与资源；ES 设密意图和官方工具/API 写入分开，应用保持停写直至验证。覆盖 AC-72、AC-73、AC-75。证据：本地 Bitnami 8.12.0 实测，最终结果另见 verification.md。
- [x] **T122**：中断恢复和显式配对回退。沿用同一目标，探针归属签名保存；只在确认后恢复原无认证模式，不回滚索引数据。覆盖 AC-74、AC-76。证据：故障注入与本地原生回退实测。
- [x] **T123**：原命令验收与用户手册同步。保持 bash docker/install.sh，新增镜像缓存策略以支持测试机本地覆盖镜像；更新 HTML 运维指南与治理方案。覆盖 AC-72、AC-76。证据：部署命令 double 与静态检查。
- [ ] **T124**：166 原有环境手动部署、原索引与业务验收。执行人：用户。覆盖 AC-71～AC-76。不得由开发侧再建隔离栈或修改原账号。
- [ ] **T125**：最终发布镜像、全部客户端业务链路及外部环境验收。覆盖 AC-74、AC-76。测试用例 TC-CRED-086～093 保持参考状态“待执行”，自动化结果在 verification.md 单独登记。
