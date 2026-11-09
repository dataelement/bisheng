# 自定义联网搜索部署与运维

本文记录当前实现的部署要求，不代表功能已完成验收。实现依据：[密钥服务](../../../src/backend/bisheng/tool/domain/services/web_search.py)、[请求适配器](../../../src/backend/bisheng_langchain/gpts/tools/web_search/custom.py)、[设置服务](../../../src/backend/bisheng/tool/domain/services/web_search.py)。上线前还需按实际部署形式和环境执行下述验证。

## 部署配置

通过部署平台的密钥管理功能注入所有 API 实例、所有可能执行工具的 Celery worker（包括不同队列和副本）及所有 Linsight worker；不要假设 API 的环境会传递到独立进程。所有进程的 keyring 内容必须一致，出站策略至少覆盖该进程实际要访问的目标；建议一致管理以避免不同执行路径表现不一致。环境变量变更后按部署平台流程重启或滚动替换各进程，并验证每个副本；健康检查成功不代表搜索可用。不要把密钥写入仓库、镜像、普通配置文件、命令历史、日志或工单。进程环境也可能被特权用户、调试接口或转储读取，应限制访问。

| 环境变量 | 格式和作用 |
| --- | --- |
| `BISHENG_WEB_SEARCH_SECRET_KEYRING` | JSON 对象，key ID 映射到 Fernet key，例如 `{"2026-01":"<Fernet key>"}`。ID 为非空字符串，最长 128 字符；每个值均须是有效的 Fernet key。此对象本身是秘密。 |
| `BISHENG_WEB_SEARCH_SECRET_ACTIVE_KEY_ID` | 当前写入使用的 ID，必须存在于 keyring。缺失、无效 JSON、无效 key 或 active ID 不存在时，依赖密钥的操作失败，不会回退到默认 key。Schema 操作 proof 的签发和验证也使用该 keyring，即使搜索无认证也必须配置。 |
| `BS_CUSTOM_SEARCH_ORIGINS` | 测试和正式搜索使用的逗号分隔精确 origin 列表，格式 `scheme://host:port`，不含路径、查询或末尾斜杠，端口即使为默认 80/443 也必须显式写出。例如 `https://search.example.com:443`。IPv6 使用方括号；按目标 URL 的解析结果匹配，不做通配符或后缀匹配。不要在逗号附近加空格。 |
| `BS_CUSTOM_SCHEMA_ORIGINS` | Schema URL 导入专用的逗号分隔精确 origin 列表，格式和搜索 origin 相同，例如 `https://schema.example.com:443`；独立授权，不会回退使用搜索列表。粘贴 Schema 内容无需此列表。 |
| `BS_CUSTOM_SEARCH_PORTS` | 逗号分隔的整数端口，例如 `443,8443`。目标端口必须同时出现在此列表和所匹配 origin 中。 |
| `BS_CUSTOM_SEARCH_CA_FILE` | 可选，指向各进程所在容器或主机内可读取的 PEM CA bundle 绝对路径；设置后替换 Python 默认 CA，而非追加。未设置时使用 Python 系统默认 CA；需要同时信任公网与私有 CA 时须提供包含全部所需根证书的 bundle。无效或不可读文件导致 HTTPS 失败。 |
| `BS_CUSTOM_SEARCH_PRIVATE_CIDRS` | 可为空；逗号分隔的严格网络 CIDR，如 `10.42.0.0/16,fd12:3456::/32`，不得有主机位。仅授权其中的 RFC1918 IPv4 或 `fc00::/7` IPv6 地址，不会覆盖始终禁止的地址类型。不要添加空格。 |

对应用途的 origin 列表或端口列表为空时出站失败；无效端口或 CIDR、未授权 origin、解析失败、空 DNS 答案或任一解析地址不合规也会失败。配置错误不一定在进程启动时发现。Schema URL 导入和搜索使用各自的 origin 列表，共用端口和私网 CIDR 列表；分别授权 Schema 和搜索 origin，或通过粘贴内容导入 Schema。导入 URL 不能含 userinfo、查询串或 fragment。搜索配置的 server 可含路径，但授权只检查 origin，不限制其路径，因此必须只授权可信服务并配合网络层限制。

### 部署形式

- Docker Compose：`docker/docker-compose.yml` 将上表变量从 Compose 插值环境透传给 `backend` 和 `backend_worker`，缺省为空；空 keyring 或授权列表不会开启搜索。`backend_worker` 的 `worker` 模式同时启动 Celery 和 Linsight；单独部署的队列或 Linsight 进程也须独立注入。通过受控部署系统提供秘密，勿写入受版本控制的 `.env`；`docker compose config` 会展开并显示秘密，不要将其输出到日志。使用自定义 CA 时，另通过部署覆盖配置将 bundle 只读挂载到两个容器的相同绝对路径。
- Kubernetes/Helm：`backend.extraEnv`、`worker.extraEnv`、`linsight.extraEnv` 支持 Kubernetes `env` 项；对 keyring 使用已有 Secret 的 `valueFrom.secretKeyRef`，不要把明文放在 values 文件或命令行。三个 Deployment 都须配置，worker 模式也启动 Linsight。当前 chart 没有额外 CA volume 挂载参数；需要私有 CA 时须通过受控的 chart 扩展或部署补丁向所有相关容器只读挂载 bundle，并设置对应路径。
- systemd 或其他部署：为每个 API、各队列 Celery 和 Linsight unit/进程分别配置部署平台的秘密注入和出站策略；本仓库不包含这些后端 systemd unit，须核对实际运维仓及宿主权限。若指定 CA，确保每个进程可读取其绝对路径。

## 密钥生成和保管

在受控主机或密钥管理系统中使用 `cryptography.fernet.Fernet.generate_key()` 生成独立的随机 Fernet key，通过安全通道直接写入密钥管理系统；避免将输出显示到共享终端、CI 日志或 shell 历史。不要使用示例值、人工口令、仓库内固定密钥或其他用途的 key。为每个环境使用不同 keyring 和唯一 ID；记录 ID、启用时间、责任人及保留期限，不记录 key 明文。数据库密文包含 key ID，明文信封绑定租户及分类 ID，迁移数据库时必须保留这些身份和对应 key。

## 保存时的凭据检查

**绝不可在固定参数中放入秘密**，也不要将秘密放入 Schema、URL 或提示词；请使用专用认证配置。保存时仅对本次可取得的凭据执行补充检查：`keep`、`clear` 和 `replace` 均尝试解密已有的旧凭据；`replace` 还检查新提交的凭据。对可取得的旧凭据，检查发生变化的 prompt、提交并合并后发生变化的非 custom provider 白名单字段值，以及选择 custom 时不在原固定参数列表中的参数项的值；`keep` 和 `clear` 不重新扫描未变化值。`replace` 还使用新凭据检查最终 prompt、合并后的所有已知 provider 白名单字符串字段，以及保留或新提交的 custom 固定参数字符串值，即使这些值未变化或当前选择其他 provider。不检查字典键、custom proof 或其他 custom 字段。无论凭据长短，包含其原文子串即拒绝保存，短凭据也可能导致无关文本误报。此检查不识别编码、变形或其他未知秘密，不能将保存成功视为配置不含秘密的证明。此保存检查不同于下文的响应预览脱敏。

非 custom provider 的设置只允许以下字符串字段：`bing`、`bocha`、`jina`、`tavily`、`deepseek` 的 `api_key` 和 `base_url`；`serp` 另有 `engine`；`cloudsway` 另有 `endpoint`；`searXNG` 有 `server_url` 和 `base_url`。新增或修改不在白名单的 provider 或字段会被拒绝。历史上已存在的未知 provider 和字段在设置读取视图中隐藏，但保存时保留；原样提交的旧值不会被当作新配置写入。隐藏和保留不等于扫描或清除历史秘密，应由授权人员另行审计和处置。格式无效的历史 custom 配置也会从视图隐藏，需要重新导入；已存非 custom provider 不是对象时相关更新会返回 409 并要求迁移。

已有旧凭据无法解密时，选择 custom 会失败；选择其他 provider 时，仅当 prompt 和合并后的非 custom provider 配置与原来一致才允许保存，否则返回 409。在满足其他保存校验的前提下，可以切换 provider 或清除旧凭据；`replace` 仍须能够用当前有效 keyring 加密新凭据。这不意味着任意切换都能成功：切换到尚未配置或字段不完整的 Bing/Serp 时，表单可能补入 Bing 默认 `base_url` 或 Serp 默认 `engine`，使合并后的 provider 配置发生变化并触发 409。应恢复旧 key 后再配置，或在授权及其他保存条件满足时先清除旧凭据；清除后再按正常流程配置目标 provider。受限切换不恢复旧凭据，默认 Bing URL 也不代表上游可用，仍须配置有效的上游凭据并验证。

## 轮换、备份和恢复

1. 先通过独立受控渠道备份现有 keyring 和数据库，并确认可在隔离环境恢复；准备新随机 key 和新 ID。
2. 先将包含新旧 key 的 keyring 分发到所有 API、Celery、Linsight 副本，active 暂留旧 ID；逐副本验证旧凭据仍可解密。
3. 将所有副本的 active ID 滚动切换到新 ID；切换期间保证所有副本均已拥有两把 key。新替换的凭据以新 ID 加密，旧密文及既有 Schema proof 仍用其记录的旧 ID 验证或解密。切回时也必须保留读取现有新密文和验证新 proof 所需的新 key。
4. 当前实现没有提供自动批量重加密或迁移任务；`keep` 只解密验证，不重加密。管理员可在受控流程中逐个分类显式替换凭据，使其按当时 active key 写入；处理并发版本冲突、权限及各租户范围，验证实际记录后再判断是否完成。不要直接修改密文或声称已有 CAS 批量轮换工具。长生命周期已初始化工具可能仍持有旧凭据；按需重启或结束相关执行，验证新实例。
5. 保留旧 key，直到确认所有在线记录、保存的 Schema proof 和保留期内的每份数据库备份均不再需要它，且恢复演练通过。凭据替换不会自动更新旧 proof；未验证所有 proof 已重新签发前不得移除旧 key。若旧备份仍含旧密文，应在独立安全位置保留对应旧 key 直至备份到期；若合规要求提前销毁，明确接受这些备份无法恢复相应凭据。数据库备份与 keyring 分开存储和授权，并记录版本对应关系。

key 遗失或错误、密文损坏、租户或分类 ID 不匹配时无法解密，不能从密文恢复明文；须恢复正确 key/身份或重新向上游获取并配置凭据。密钥泄露时，应同时评估撤销并更换上游 API Key：仅切换 Fernet active ID 不会撤销已泄露的上游凭据。

## 出站安全与限制

只授权必要的可信 origin、端口及最小私网网段，并在防火墙或网络策略中实施独立的最小权限出口控制。默认不允许私网；回环、链路本地、组播、未指定、保留和 IPv4-mapped IPv6 地址会被拒绝，即使包含在配置的 CIDR 中。公网地址仍必须满足 origin 和端口授权；非全局且不在受支持私网范围中的地址不可通过任意 CIDR 放行。所有 DNS 结果均需合规，选择其中一个地址固定连接，保留原 Host 和 TLS SNI，禁用代理环境、重定向和连接复用；TLS 默认校验证书。连接后在发送 HTTP 请求前核对 socket 对端地址；仍应依赖独立网络控制降低非预期访问风险。

实现允许 HTTP，包括私网 HTTP：查询词和认证信息可能明文经过网络。生产优先 HTTPS；如必须 HTTP，需安全审批、隔离链路并避免传输敏感信息。查询参数认证可能暴露于上游或中间层日志，优先使用认证头，并检查上游日志策略。隔离 worker 以空环境启动，不继承代理或常规 CA 环境变量；通过 `BS_CUSTOM_SEARCH_CA_FILE` 显式指定 CA bundle，并在每个副本上确认文件可读、证书链有效。

每进程最多四个并发网络 worker，超出立即失败；worker 总时限 20 秒，连接/读/写/连接池各 5 秒，响应上限 1 MiB，拒绝压缩响应和非 2xx（包括重定向）。JSON 限深 32，结果最多 100 条；映射字段受长度限制。进程数增加会增加总并发，容量规划和上游限流需另行处理。

## 上线验证

- 在每个 API、Celery 和 Linsight 副本核对变量是否存在、key ID 和策略版本是否一致；不要打印 keyring 或完整进程环境。用受控服务、非生产测试凭据执行 Schema URL 导入、测试、保存、重新打开以及实际搜索；验证对应工作台、工作流和 Linsight 路径及引用。测试不会保存，保存也不要求在线测试。
- 分别验证 Schema 和搜索 origin 白名单缺失或互不授权时失败；验证无端口、未授权 origin/端口、未授权私网、禁止地址、混合合规和不合规 DNS 结果、无效 CIDR、重定向、超时、压缩及过大响应均失败；授权公网和私网分别成功。通过可观测的受控目标确认没有访问不允许的目标。
- 验证密钥缺失、错误、未知 ID、篡改或错误租户/分类时依赖密钥的操作失败；验证无认证搜索的 Schema proof 仍需要 keyring，并验证新旧 keyring 阶段、旧 proof 验证、新 key 替换、旧备份恢复和回滚。分别验证默认系统 CA、指定 bundle、错误或不可读 CA 及证书校验失败。不要在日志、测试报告、响应预览或截图中记录真实密钥、查询词及敏感上游响应。
- 使用受控的空数组、错误映射及正常 JSON 验证空结果与错误可区分；检查响应预览和结果对当前 key 的直接值、URL 编码及 Base64 回显的脱敏。检查非管理员和跨租户权限、旧客户端及子项覆盖场景；设置冲突或历史子项 extra 会返回 409，需处理后重试，勿直接清空数据。
- 本地测试入口可从 `src/backend` 执行 `uv run pytest test/tool/test_custom_web_search.py`；这不是部署端到端验证的替代品，需另行确认真实数据库、网络、证书及所有进程。

## 已知未解决事项

- 当前脱敏仅替换已知当前凭据的原文、URL 编码、表单编码和 Base64 形式；上游可分片或变形回显，也可能返回其他未知秘密。原始响应预览不能保证绝对无泄露，只使用可信上游和受控测试数据。固定参数、Schema、URL 和提示词中不要放秘密；有限检查不能证明不存在未知秘密。
- origin 白名单不是路径级授权；DNS、网络设备、TLS 和上游自身仍是信任边界。对端检查和 TLS 不能替代网络隔离及对上游服务的信任。
- 多租户共享工具与实际部署中的授权、两数据库兼容、备份恢复、真实网络及端到端路径仍须按环境验证；不要把设计文档中的计划当作已验收能力。历史子项覆盖目前阻止相关设置/预览，迁移策略尚未提供。
- 没有任何历史子记录（包括已删除记录）的 preset 无法安全识别种类：普通列表隐藏其 `extra`，旧配置写入会被拒绝，即使该 preset 实际并非搜索工具也受影响。具有历史子记录且可识别为非搜索的 preset 保持原行为。实际部署中的影响范围及迁移策略仍待核实，不要自行清除或伪造子记录。
- 不支持任意 OpenAPI、复杂嵌套请求、分页、非 JSON 或多服务并行；详细范围和待验收风险见 [设计文档](./design.md) 与 [任务清单](./tasks.md)。
