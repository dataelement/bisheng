# F118 真实测试脚本入口

当前状态：**脚本已编写；真实环境待执行（NOT_RUN）**。本文不执行或授权建表、部署、真实目录操作或授权操作。T078／T079 尚未勾选，整体仍为 NOT_READY。

## T078：真实存储

- 脚本：src/backend/test/integration/test_kunlian_consistency.py；夹具 kunlian_fixtures.py。
- 独立两个异步连接池、两个 Repository／Owner 实例及两个 Redis 客户端；不是两个部署进程。真实跨进程／浏览器两节点验收仍需 T080。
- 四组用例：租约竞争／接管与旧 fence、完整指针和失败保留；Owner 新投影／人工禁用与旧资料竞争；交接唯一、epoch／恢复、跨实例撤销与到期 CLOB 密文清理；真实签名验证实例共享 Redis nonce／TTL。
- 同一脚本分别以 MySQL 和 Linux DM8 配置执行并保存各自 JUnit；没有虚构现有中央 CI 门禁或已完成结果。

必要环境变量：

| 名称 | 要求 |
| --- | --- |
| F118_STORAGE | 只有 1 显式开启；缺省跳过 |
| F118_TEST_DATABASE_URL | 完整异步 URL；明确主机和用户名；mysql+asyncmy 或 dm+dmAsync；库／schema 名以 e2e_kunlian_ 开头 |
| F118_TEST_REDIS_URL | 明确主机及数字 DB，禁止 DB 0；仅使用专属测试 Redis |
| config | 按后端原装配要求提供测试 YAML；DSN 仍只取上面的测试变量，不使用应用默认连接 |

URL／密码通过安全环境注入，不写入仓库或命令行示例。DM8 URL 使用空 path 和 ?schema=E2E_KUNLIAN_...；复用项目实际 dmAsync 驱动，Linux 环境须记录 dmPython／dmSQLAlchemy 版本，dmPython 不得低于项目要求。当前机器未执行真实 MySQL／DM8／Redis。

数据库须事先经过另行批准的流程准备九张新表及现有 User／UserRole 等依赖，fixture 只检查存在性，不 create_all、不迁移表。每个用例生成随机 e2e-kunlian- 连接／身份；使用合成令牌验证密文存储，不代表上游身份或租户 Owner 已验收。清理严格限定本次连接、已登记身份及其创建用户；出现意外人工角色关联时停止并失败，不删除该授权。Redis 只清理本次随机签名 nonce 键。

未来受控执行命令（cwd 为 src/backend，环境参数已安全注入）：

~~~bash
F118_STORAGE=1 .venv/bin/python -m pytest \
  --confcutdir=test/integration test/integration/test_kunlian_consistency.py \
  -q -rs --tb=short --junitxml=/tmp/f118-storage-result.xml
~~~

confcutdir 用于排除 test/conftest.py 的预模拟导入链；不得使用它的 SQLite fixture 作为真实库。没有环境先保持开关关闭；开启后缺参数、缺表、驱动／连接失败或竞争结果错误均失败，不自动降级跳过。真实运行前须确认专属数据操作范围；本轮仅编写和离线验证。

## T079：真实 API、Worker 与 OP 交接

- 脚本：src/backend/test/e2e/test_e2e_kunlian_identity.py；助手 helpers/kunlian.py。
- 已实现目录缺失拒绝和补同步需求、显式映射、完整批次及投影、无菜单拒绝、A／B 身份和 C 固定租户反例、工作流读取／编辑入口及 F048 visible／use／edit／publish 授权检查、停用保留 Grant／资产、停用期间人工撤权后恢复不补回、新会话、本地退出与旧 Cookie 重放、退票交接和真实 OP 回调。
- 不签发测试 JWT，不把外部 Token 放进业务请求；Cookie 只由真实网关回调写入，写请求从辅助接口获取 X-CSRF-Token。
- 同步先调用管理 API 持久登记需求，再通过真实 Broker send_task 并读取 Worker 成功回执；还须轮询 SQL 状态发布新完整批次、完成投影。若 Beat 已占租约，允许任务回执为 FETCHING，但仍须等到新批次实际发布。HTTP 202 或任务已入队均不算通过。
- 本脚本检查 use 动作授权，不运行空图工作流。真实 WS 运行、前端页面行为、AT 五分钟到期、两进程接续及状态传播时效仍按 T080 清单执行；不能据本脚本声明这些边界完成。

必要环境变量：

| 名称 | 要求 |
| --- | --- |
| F118_E2E | 只有 1 显式开启；缺省跳过 |
| F118_E2E_MANIFEST | 当前用户拥有的 0600 JSON 文件，格式如下 |
| F118_E2E_CONTROL_DIR | 当前用户拥有、非符号链接的 0700 私有交接目录 |
| F118_E2E_ADMIN_TOKEN | 专用部署的当前全局管理员本地凭据；无默认密码／Token 回退 |
| F118_E2E_BROKER_URL | 同一专用部署的实际 Redis／AMQP Broker；禁止内存替代 |
| F118_E2E_RESULT_BACKEND | 该 Worker 实际使用的网络 Redis 结果后端，允许 JSON 结果读取 |
| F118_E2E_CHECKPOINT_TIMEOUT | 可选，默认 600 秒，范围 5—1800；只是操作预算，不是传播 SLA |

manifest 示例全部为虚构值，不表示可用环境：

~~~json
{
  "origin": "https://e2e-kunlian.invalid",
  "connection_id": "e2e-kunlian-run",
  "external_tenant_id": "opaque-test-tenant-id",
  "local_tenant_id": 2001,
  "foreign_local_tenant_id": 2002,
  "expected_member_count": 4,
  "return_to": "/workspace",
  "actors": {
    "a": {"user_id": 10001, "name": "e2e-kunlian-a"},
    "b": {"user_id": 10002, "name": "e2e-kunlian-b"},
    "c": {"name": "e2e-kunlian-c"},
    "missing": {"name": "e2e-kunlian-fresh-probe"}
  }
}
~~~

用户和两本地租户须预先准备且不与业务共用；本地 tenant_code／tenant_name 及账号名称使用 e2e-kunlian- 前缀，两个本地租户必须不同。外部 tenant_id 保留真实不透明标识，不强制其变成测试名称。A／B 是已登记登录范围内的普通用户，不能是全局／租户管理员；C 属于另一外部租户。A／B 稳定 user_id 已在专属环境预备阶段确认。

missing 是每轮独立准备的真实 OIDC 探针，属于允许登录范围，但从未被本地已发布目录覆盖；首次回调前暂停专属环境自动目录调度，Worker 保持可用。回调拒绝并登记补同步后再恢复调度，后续完整同步应包括该探针。不能把已有 A 从目录中删掉来替代该前提：已有绑定缺失会成为 UNKNOWN 并拒绝身份，不等于首次目录未就绪；更不能删除历史绑定来制造场景。重复运行需准备新的 missing 探针，或确认前次从未被发布。上游目录包含其他租户事实，expected_member_count 必须计入 missing 并来自专属已知数据；后台未映射记录不会据此自动建租户。

现有上游材料未提供可自动化的管理／登录界面契约，因此采用**操作侧协作**，不虚构昆联管理接口，也不调用任意 shell 命令：

1. 测试写入随机 run_id／nonce 的 *.request.json（0600），含 phase 和本次操作要求。测试只接受对应 *.reply.json 中相同 nonce、ok=true 的确认；错误确认、超时均失败。
2. 准备目录、仅授菜单、停用和恢复等阶段由已批准的测试操作侧执行真实操作。普通阶段回执只需 nonce／ok；回执本身不算业务通过，脚本随后独立请求真实 API。
3. oidc-a／b／c 阶段的请求包含真实网关生成的 authorization_url。操作侧在真实 OP 完成指定账号登录，**截获而不访问网关回调**，将完整 callback_url 写入回执。测试客户端持有其自己发起事务的绑定 Cookie，并亲自请求回调完成换码／交接。不能让浏览器先消费一次回调再把 URL 交测试，否则应按重放失败。可由专用浏览器自动化执行，但不要猜测生产页面选择器。
4. op-logout 阶段同理：操作侧打开 logout_url，确认真实 OP 退出，截获尚未请求的 logout_callback_url；测试客户端随后验证受绑定回调。此 URL 可能含 Hint，必须留在私有交接目录，不能发到普通日志／聊天或未脱敏 HAR。
5. 操作侧以 0600 临时文件完整写入后原子改名为对应 reply 文件。消费后测试删除本次 request／reply，不读其他 run 的回执；不对目录做批量清理。state 事务最多五分钟，授权码还受上游约一分钟有效期约束；交接须满足两者，600 秒操作预算不会延长任一服务器期限。

最小回执格式：

~~~json
{"nonce": "从本次 request 读取", "ok": true}
~~~

OIDC／退出阶段分别附加 callback_url 或 logout_callback_url。不要填假 code／假 Cookie。测试未关闭 TLS 校验或跟随任意重定向，专用环境证书须被系统信任。

未来受控执行命令（cwd 为 src/backend，所有必要环境已注入）：

~~~bash
F118_E2E=1 .venv/bin/python -m pytest \
  --confcutdir=test/e2e test/e2e/test_e2e_kunlian_identity.py \
  -q -rs --tb=short --junitxml=/tmp/f118-api-e2e-result.xml
~~~

串行执行，不用 xdist；测试过程中不能由另一套用例修改同一连接／菜单／账号。保持真实 Worker、Beat、Redis 和 OpenFGA 可用，结果后端须与 Worker 匹配。同步验证的总超时从首个状态请求开始，包含 Broker 投递及结果轮询；生产者关闭隐式发布重试，网络连接／读取另限 5 秒。超时不会自动取消已发送的真实任务，须查关联状态。A／B 的 API 操作必须在当前 AT 有效期内完成；发生到期应视为该次执行失败并从清洁准备阶段重新运行，不把到期拒绝冒充停用传播合格。T080 另行核对实际到期和状态语义。

工作流使用每次 UUID 名称，创建后登记精确 id／name／owner／tenant；teardown 再次 GET 核验全部归属才 DELETE，并由原权限能力清理其附属授权。没有全前缀删除或猜测其他资源的清理。POST 创建结果若网络不明，JUnit 中记录的 workflow_test_name 用于人工核查遗留，只能在确认同名、同创建者及同租户后清理；不能盲重试或删除他人数据。上游测试状态、预备账号／映射／菜单不由脚本批量删除，操作侧在运行前后按自己的专属基线复核恢复。

执行不要加 --showlocals、完整 HTTP DEBUG 或抓取未脱敏凭据。证据记录组件版本、数据库／驱动、两实例条件、命令、JUnit、关联 ID 和脱敏结果；真实运行及容量／浏览器检查未完成之前，tasks 仍未完成。
