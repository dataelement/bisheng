# Spec Discovery：中间件密码与配置加密治理

**日期**：2026-11-11。**状态**：需求发现、正式规格与设计均已确认；任务已拆解，开始基础实现。最新进度以 tasks.md 为准。
**工作区**：当前 `feat/3.1-beta2`，基线 `285bfde44d`；保留既有未提交的 HTML 文档，不创建或切换分支/worktree。

## 1. 已确认的输入

- 用户要求客户在部署时配置中间件密码，治理默认弱密码与业务配置明文存储。
- 用户明确要求用于解密 MySQL 配置密码的密钥不得写在代码中。
- 用户选择：完整覆盖部署改密、认证、配置加密、客户独立密钥及存量迁移；Compose 优先、兼顾 Helm。
- 用户选择：允许受权限保护的部署明文 Secret 文件，业务配置保存密文；客户填写密码，缺失即停止，不自动生成中间件密码。
- 用户要求逐中间件说明首次部署、已有环境改密、影响、验证及失败恢复。
- 用户要求 HTML 增加业务背景、安全现状与可行性评估；已于本轮明确认可 [HTML 方案](../../../docs/中间件密码与配置加密治理方案.html)，并要求进入下一步。

## 2. 已核实的代码事实

| 事实 | 核实位置 |
| --- | --- |
| 现有共用 Fernet 密钥硬编码；数据库和 Redis 已有解密，MinIO/ES/Milvus 仍需补齐 | `src/backend/bisheng/core/config/settings.py:26`、`:119`、`:138`、`:160`、`:1073`、`:1088`、`:1101` |
| 安装脚本仅首次复制 .env 模板，不生成业务 config.yaml；API/Worker 挂载已有配置 | `docker/install.sh:32`；`docker/docker-compose.yml:175`、`:229` |
| MySQL 密码使用方包括 OpenFGA 和启用时的 Gateway 数据库初始化任务 | `docker/docker-compose.yml:22`、`:71`、`:91`、`:103` |
| Redis 使用方包括缓存、Celery/Linsight 与商业 Gateway；当前健康检查接受 NOAUTH | `docker/bisheng/config/config.yaml:68`、`:107`；`docker/gateway/config/application.yml:42`；`docker/docker-compose.yml:141` |
| MinIO 密码同时用于毕昇和 Milvus 对象存储 | `docker/docker-compose.yml:167`、`:221`、`:338` |
| 共用加密工具还影响组织同步凭据和沙箱令牌及其缓存 | `src/backend/bisheng/org_sync/domain/models/org_sync.py:33`；`src/backend/bisheng/common/services/config_service.py:28`、`:62` |
| API 在执行数据库迁移成功后启动 | `docker/bisheng/entrypoint.sh:50` |
| Helm 只交付应用服务，外部中间件需另行准备 | `docker/helm/README.md`；`docker/helm/bisheng/values.yaml` |

核查为静态读取，未读取真实部署凭据、未连接客户环境、未改密。对应版本官方文档与源码依据见 HTML 各组件章节；镜像兼容及回滚流程尚待集成验收。

## 3. 进入正式规格的边界

- 新装和存量升级均覆盖；存量密钥迁移先保持实际密码不变，再逐组件处理实际改密。
- 保留现有账号权限、租户归属和业务语义；不扩展为账号拆分、密码热更新、新业务页面或强制 Vault/KMS。
- 组织同步与沙箱维护只变更加密表示，不获得对应领域业务写入权；独立密钥体系的数据不在本次迁移范围。
- 使用当前分支命名归档为 `features/v3.1.0-beta2/003-middleware-credential-security/`；登记增量 release contract，不推断其他版本内容。
- 用户认可的 HTML 继续作为已确认方案输入。正式 spec 只承载需求与可验收行为；技术契约在 spec 确认后单独整理 design，不提前编写任务或执行代码。

## 4. 流程依据

本特性跨配置、部署、中间件和存量凭据，涉及 C6，采用 [SDD-Guide §1–§3](../../../docs/SDD-Guide.md) 的 Full SDD。用户对 HTML 方案的认可作为需求发现确认；新生成的 spec 仍需经 `/sdd-review` 后由用户确认。

## 5. 正式规格评审记录

2026-11-11，按仓库 `sdd-review` 的现行 spec-checklist 完成需求覆盖、AC 质量、范围与架构边界检查，结果见 [spec-review.md](./spec-review.md)。42 条 AC 使用 EARS 句型，编号连续且唯一；文档相对链接已校验。

| HTML 输入范围 | 规格覆盖 |
| --- | --- |
| §1–§4 背景、现状、方案总览及外置密钥 | AC-01、AC-02、AC-03、AC-04、AC-05、AC-06、AC-07、AC-08、AC-09、AC-10、AC-11、AC-28、AC-29、AC-30、AC-31、AC-32、AC-33、AC-34 |
| §5 MySQL | AC-12、AC-13、AC-14 |
| §6 Redis | AC-15、AC-16、AC-17 |
| §7 MinIO | AC-18、AC-19、AC-20 |
| §8 Elasticsearch | AC-21、AC-22、AC-23 |
| §9 Milvus | AC-24、AC-25、AC-26、AC-27 |
| §10–§13 恢复、可行性、部署交付与验收 | AC-33、AC-34、AC-35、AC-36、AC-37、AC-38、AC-39、AC-40、AC-41、AC-42 |

本次仅文档静态评审，不代表代码、镜像或客户环境验收通过。spec 确认前不创建实施任务、不修改业务代码，也不把状态标记为用户已确认。

## 6. 规格确认与正式设计

用户于 2026-11-11 明确回复“确认”，正式批准 42 条规格，未改变既有范围。随后整理 [design.md](./design.md)，按 sdd-review 的 24 项设计清单完成静态评审，结果见 [design-review.md](./design-review.md)。设计确认前未生成实施任务或 QA 用例。

镜像原生配置入口、文件权限、SDK/服务端组合和实际恢复仍属实施/交付门禁，本机 Docker daemon 访问被拒绝，未声称已运行验证。

## 7. 设计确认后

用户再次于 2026-11-11 回复“确认”，批准正式设计。按模板生成 47 条八列 QA 参考用例，结果均为待执行；之后从 spec/design 独立拆解 38 个任务并完成任务评审，见 tasks-review.md。任务无新增人工确认门禁。

已完成 T001/T002：独立外置密钥模块及 34 项测试；尚未替换现有运行时固定密钥。无真实客户凭据操作、提交、推送或部署。


## 8. 用户纠正：部署入口与操作体验优先（2026-11-12）

用户明确否定新增大量人工准备步骤的部署体验，要求运维继续执行原有命令；需要的信息可以在同一次部署过程中引导补齐。本条覆盖此前将独立keygen/prepare/check作为正常部署前置步骤的安排。

- 保留 `bash docker/install.sh` 与 `bash scripts/deploy.sh install`，后者继续转发前者。
- 标准新装由安装脚本完成镜像准备、缺失信息引导、首次外置key创建、配置加密、原生消费者同步、权限/挂载、检查及启动。
- 缺少客户密码时在当前部署会话隐藏输入并确认；密码仍由客户提供，不自动生成中间件密码，不使用统一弱密码。
- 正常重复部署复用已保存的密码、key及配置，不重复询问、不重新生成、不自动改账号密码。
- 正常部署不要求用户理解keyring、bundle、revision，也不要求执行辅助工具或填写其路径参数。
- 存量部署或失败重试先识别已有状态；必要的旧配置/key/管理信息通过同一入口引导恢复，不能按新装覆盖原有身份和数据。
- 只有显式要求的真实改密或密钥轮换才进入对应维护流程，不能在普通启动时默认执行。

当前install.sh仍强制要求预先生成配置包，因此不满足本次修正。已有200项聚焦回归证明基础安全能力，不证明“一条命令部署”已经实现。下一轮围绕原安装入口补充交互、复用和失败重试验收，原长SOP不作为正常部署的合格交付。
