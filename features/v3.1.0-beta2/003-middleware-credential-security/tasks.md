# Tasks：中间件密码与配置加密治理

**关联**：[spec.md](./spec.md) · [design.md](./design.md)
**版本**：v3.1.0-beta2。**分支**：当前 feat/3.1-beta2，不创建/切换分支或 worktree。

## 状态

| 步骤 | 状态 | 备注 |
| --- | --- | --- |
| spec.md | ✅ 已评审 | 用户 2026-11-11 确认，47 条 AC（原42条，新增原入口AC-43～47已确认返工） |
| design.md | ✅ 已评审 | 用户 2026-11-11 确认，技术维护入口 |
| test-cases.md | ✅ 已编写 | 55 条 QA 参考，均待执行；不作为任务/执行器输入 |
| tasks.md | ✅ 已拆解 | sdd-review tasks 检查通过，55 个任务（原53项，补2项真实验收MySQL修复） |
| 实现 | 🟡 进行中 | 57 / 59；标准单机真实验收通过，T035（DM）/T038（完整交付）保留未完成 |

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

### Wave 4 · 部署与 Helm

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

- [x] **T024**：Helm 外部 Secret 回归
  **类型**：测试
  **文件**：`src/backend/test/deploy/test_credential_helm.py`
  **逻辑**：固定 values/外部 Secret 夹具验证所有 Python Deployment 挂载/revision，旧秘密值拒绝和无普通明文配置。
  **覆盖 AC**：AC-03, AC-06, AC-39, AC-40
  **依赖**：T014

- [x] **T025**：Helm 输入契约
  **类型**：基础设施
  **文件**：`docker/helm/bisheng/values.yaml`、`docker/helm/bisheng/templates/_helpers.tpl`
  **逻辑**：external Secret/configRevision，移除本次旧密码来源，旧 values 报迁移错误；保留其他独立秘密契约。
  **覆盖 AC**：AC-03, AC-06, AC-39, AC-40
  **依赖**：T024
  **配对测试**：T024；绿阶段及 L1 审查通过后完成。

- [x] **T026**：Helm API/Worker 挂载
  **类型**：基础设施
  **文件**：`docker/helm/bisheng/templates/backend-deployment.yaml`、`docker/helm/bisheng/templates/worker-deployment.yaml`
  **逻辑**：同 Secret config/key 路径，显式 revision rollout，不假设 Secret 更新自动滚动。
  **覆盖 AC**：AC-03, AC-39, AC-40
  **依赖**：T024, T025
  **配对测试**：T024；绿阶段及 L1 审查通过后完成。

- [x] **T027**：Helm Linsight/Secret
  **类型**：基础设施
  **文件**：`docker/helm/bisheng/templates/linsight-deployment.yaml`、`docker/helm/bisheng/templates/secret.yaml`
  **逻辑**：独立 Linsight 同配置；移除本次 MinIO 明文 Secret 生成，不误删 HMAC/sandbox 能力。
  **覆盖 AC**：AC-03, AC-06, AC-39, AC-40
  **依赖**：T024, T026
  **配对测试**：T024；绿阶段及 L1 审查通过后完成。

- [x] **T042**：Helm 原有 ConfigMap 接线收口
  **类型**：基础设施
  **文件**：`docker/helm/bisheng/templates/configmap-config.yaml`、`docker/helm/bisheng/templates/configmap-nginx.yaml`
  **逻辑**：停止输出业务配置 ConfigMap；Nginx 只保留非秘密地址，复用输入校验。
  **覆盖 AC**：AC-39, AC-40
  **依赖**：T025, T027
  **配对测试**：T024；实际 Helm 渲染通过。

- [x] **T043**：清理配套发布模板的旧密码来源
  **类型**：基础设施
  **文件**：`docker/bisheng/config/config.yaml`、`docker/helm/bisheng/files/config.yaml`
  **逻辑**：模板不携带可用旧密码/固定 key 密文；拓扑默认值为非秘密常量，客户已有文件不覆盖。
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
  **文件**：`docs/中间件凭据运维手册.html`、`src/backend/scripts/README.md`
  **逻辑**：实际入口、角色/备份/停写/新连接验证/恢复，key 全丢不可逆、旧签名 URL、在途任务核对、source/systemd 与未验证边界。
  **覆盖 AC**：AC-07, AC-10, AC-13, AC-16, AC-19, AC-22, AC-23, AC-25, AC-26, AC-28, AC-30, AC-33, AC-34, AC-35, AC-36, AC-38, AC-41, AC-42
  **依赖**：T022, T023, T031

- [x] **T037**：部署及 Helm 手册
  **类型**：文档
  **文件**：`docker/README.md`、`docker/helm/README.md`
  **逻辑**：env/config 职责、bundle 激活/recreate、外部 Secret/rollout 和中间件真实改密责任，check 不替代业务验收。
  **覆盖 AC**：AC-11, AC-37, AC-39, AC-40, AC-41, AC-42
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
  **文件**：`docs/中间件凭据运维手册.html`、`docker/README.md`
  **逻辑**：主线仅原命令及必要引导，区分新装/重复/旧版/失败，明确备份和待验边界；撤销旧Markdown SOP交付。
  **覆盖 AC**：AC-43, AC-44, AC-45, AC-46, AC-47
  **依赖**：T048, T049

- [x] **T052**：维护文档链接同步
  **类型**：文档
  **文件**：`src/backend/scripts/README.md`、`docker/helm/README.md`
  **逻辑**：链接统一指向新版HTML手册，维护/Helm不混入正常单机安装前置。
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
