# F059 专用验收夹具

这些文件用于新建的隔离测试实例。`bootstrap_f059_acceptance.py` 默认只在本机生成私有配置和应用包；只有 `--bootstrap` 会调用平台 API 创建测试数据。它不访问数据库、manager RPC、Docker 或 Kubernetes API，也不执行集群故障注入。

初始化成功、合同单测通过和本地协议烟测均不等于真实平台业务验收通过。真实验收由 `scripts/e2e_k8s_runtime.py` 通过发布、审批和应用入口执行并记录。

## 1. 前置环境与保护

- 使用全新迁移、单独配置的 backend/Celery/MySQL/Redis/MinIO/OpenFGA 测试实例。先启用多租户、OpenFGA、`open_platform` 和应用托管功能，并确认发布审批 worker 正常消费。
- backend 初始化通过 `settings.admin` 自动创建的 user 1 必须使用 `e2e-f059-` 用户名，密码从安全环境变量传入，不使用猜测的默认密码。
- `--env-file` 接受已有 **0600** 平台环境文件，只继承 `E2E_ADMIN_USERNAME`、`E2E_ADMIN_PASSWORD`，不会覆盖它们。输出须是另一个文件；不能用输出参数覆盖平台环境文件。
- API 地址只接受私网/回环字面 IP，拒绝 URL 中的用户名、密码、查询参数。套件目录名须包含 `e2e-f059`，生成的 marker 固定 API 地址和随机实例 ID。重复执行会校验 marker、保留密码、复用已创建的专用身份。
- API bootstrap 要求登录者是同名 user 1 且是全局超管；遇到非 `e2e-f059-` 用户、非 Root 的非测试租户或非测试应用会停止。它不是生产实例的数据准备工具。
- 全部用户名、租户代码和 slug 都以 `e2e-f059-` 开头。env、marker、bootstrap-state、源码压缩包均为 0600，目录为 0700。不要提交、打印、上传或粘贴 `e2e.env`。

运行脚本的 Python 环境只需要 `httpx`、`PyYAML`、`cryptography`；可使用 backend 的环境。参数不接收密码或 API key，避免出现在 shell 历史和进程参数中。

## 2. 准备镜像清单和应用包

安装者提供五个**实际已导入 CRI 并核对**的 amd64 镜像，写入 `inventory.json`。也可直接使用镜像发行脚本产生的 `runtime-images-amd64.json`，其 `platform` 和 `images` 字段相同。

```json
{
  "platform": "linux/amd64",
  "images": {
    "app-python": {"image": "registry/repository@sha256:<64 hex>", "image_id": "sha256:<64 hex>", "platform": "linux/amd64"},
    "app-python-preparer": {"image": "registry/repository@sha256:<64 hex>", "image_id": "sha256:<64 hex>", "platform": "linux/amd64"},
    "app-node": {"image": "registry/repository@sha256:<64 hex>", "image_id": "sha256:<64 hex>", "platform": "linux/amd64"},
    "app-node-preparer": {"image": "registry/repository@sha256:<64 hex>", "image_id": "sha256:<64 hex>", "platform": "linux/amd64"},
    "app-static": {"image": "registry/repository@sha256:<64 hex>", "image_id": "sha256:<64 hex>", "platform": "linux/amd64"}
  }
}
```

上面是格式说明，占位符不是可发布的 digest。`image` 的 OCI manifest digest 与 `image_id` 的配置 digest 含义不同，不能互相代填。清单只用于导入三个 `official=false`、仅 `linux/amd64` 的自定义 profile，并设为默认；不宣称官方双架构或跨节点已验证。后续 installer 和业务 E2E 仍须检查实际 Pod imageID。

先执行本地准备（`API_BASE`、`SUITE_DIR` 和 `PLATFORM_ENV` 由操作者设置为专用实例的地址和私有目录/文件路径）：

```bash
python scripts/bootstrap_f059_acceptance.py \
  --api-base "$API_BASE" \
  --suite-dir "$SUITE_DIR" \
  --env-file "$PLATFORM_ENV" \
  --profile-inventory "$INVENTORY_FILE" \
  --prepare-only
```

输出 `e2e.env`、marker、三个 profile 定义、五组源码包（完整镜像场景暂不生成）、`scenarios.json`，以及 `demo-image-v1/`、`demo-image-v2/` 构建上下文。源码和 npm 初始场景没有新增依赖；Python 直接使用预制 runtime 中的标准库和 SDK/httpx，Node 只用内置模块。不会为此访问公网包源。

### 完整应用镜像

`Dockerfile.demo` 基于清单中的固定 `app-python` 镜像，包含实际 demo 源码和版本。由操作者分别构建并导入/推送 v1 和 v2，取得各自固定 digest，再重复准备：

```bash
python scripts/bootstrap_f059_acceptance.py \
  --api-base "$API_BASE" --suite-dir "$SUITE_DIR" --env-file "$PLATFORM_ENV" \
  --profile-inventory "$INVENTORY_FILE" \
  --demo-image "$DEMO_IMAGE_V1_DIGEST_REF" \
  --demo-image-v2 "$DEMO_IMAGE_V2_DIGEST_REF" --prepare-only
```

基础镜像通过构建参数 `BASE_IMAGE` 传给 Dockerfile；脚本不构建、推送镜像，也不伪造 digest。`--demo-image` 缺失时不生成完整镜像场景；仅传一个 digest 时 v2 会使用同一镜像，因此只能验证重发布，不能作为镜像代码更新证据。正式升级验收应提供两个不同的真实镜像。

## 3. 通过真实 API 初始化

在对应专用平台启动后，使用相同参数将 `--prepare-only` 改为 `--bootstrap`。bootstrap 的实际操作：

1. 公共 RSA 接口和密码登录 → user 1 和全局超管身份核验 → 用户、租户、应用库存保护检查。
2. `POST /departments/` 创建两个测试部门；使用 **Department.id 整数**调用 `POST /departments/{id}/mount-tenant`，生成两个非 Root 租户。旧 `POST /tenants/` 返回 410，不使用该入口。
3. 使用现有兼容接口 `POST /departments/local-members`，body 携带外部 `dept_id`、唯一 `person_id`、RSA 密文密码和普通默认角色。创建 owner、nonowner、foreign、approver 四个自然人，逐人登录验证所属 leaf tenant，拒绝 Root/超管身份。
4. 仅给 approver 授予测试子租户管理员；取种子 `app_publish_request` 场景，确认唯一启用 catch-all route 为 `flow`，将流程改为明确指定 approver 的一个人工 OR 节点。遇到 pass route 或多个启用分支会停止，不设置自动审批。
5. 在 owner 租户建立由 owner 承担资源归属的 ServiceAccount，签发仅 `app:manage` 的 key，立即保存到私有 env；`/api/v2/auth/whoami` 复核 mode-S、tenant 和 resource owner。自然人 PAT 不用于替代 mode-S。
6. 全局超管通过 `/runtime/profiles` 导入三个固定自定义 profile，再按当前 generation 设置默认。相同 code/revision 内容改变会由平台拒绝，不能覆盖已冻结 profile。

`bootstrap-state.json` 保存 API 准备阶段的非秘密 ID 和结果，不保存密码、JWT 或 API key。部分失败可修复原因后重复执行；不会自动删除业务数据或绕过审批。

只有未启用 `settings.admin` 自动初始化、确认数据库里确实没有任何用户的独立实例才使用 `--register-first-admin`。该显式选项经真实 `/user/regist` 注册首个用户，不做 SQL bootstrap；默认关闭，不应在已有管理员的 189 实例上使用。

## 4. 应用场景和真实检查

| 场景 | 运行方式 | 验证点 |
|---|---|---|
| Python bundle | profile + 源码 + 空 requirements | HTTP、SQLite `items`、SDK 身份/真实附件往返、WebSocket、v1/v2 |
| Node bundle | profile + 内置模块/空 npm lock | HTTP、WebSocket、v1/v2 |
| static bundle | profile + `index.html`/`health` | 默认静态启动入口、HTTP、v1/v2 |
| Python image | 完整固定镜像 | 同 Python 正线，两个镜像升级 |
| Python source-image | 平台兼容组装流程 | 同 Python 正线，实际组装及运行 |
| missing-dependency | 无可用 wheel 的固定假依赖 | 发布预检必须失败，`16227` / `precheck_build` |

Python `items` 是真实 SQLite 表，重启仅 `INSERT OR IGNORE`，不会覆盖验收写入的数据；`/items` 返回实际查询结果。`/ws` 实现实际 echo；SDK `/sdk/storage-roundtrip` 真正执行 put/get/stat/list/delete 并逐字节检查，不会固定返回成功。初始健康探活不要求访问者身份。

可选模型/检索：准备包时附加真实 `--model-name` 和可重复的 `--knowledge-id`。这会写入 manifest 的真实 capability 声明，并增加 `/sdk/model`、`/sdk/retrieve` 场景检查。模型必须已有可调用配置，知识库需有 owner 可见权限与已入库内容；不要为通过验收伪造模型或返回常量。默认未配置时接口明确返回 409，suite 不将这些可选检查计为已测。

- 检索实际使用 `bisheng_sdk.retrieve.search`。
- 模型使用 SDK 的身份上下文和运行期真实 `OPENAI_BASE_URL`、`OPENAI_API_KEY`，向 OpenAI 兼容端点发送实际请求并转发访问者 OBO。SDK 公开模块没有 model 方法，不虚构 SDK 接口。
- SDK 本地附件烟测只证明本地目录后端；平台附件、OBO、egress、权限拒绝链路必须由实际应用入口 E2E 另外证明。

## 5. 执行业务 E2E

在可信 shell 中加载本脚本生成的 env（shell quoting 已由脚本处理），不要开启 `set -x`：

```bash
set -a
source "$SUITE_DIR/e2e.env"
set +a
python scripts/e2e_k8s_runtime.py --stage installation --evidence "$SUITE_DIR/evidence.json"
python scripts/e2e_k8s_runtime.py --stage platform --evidence "$SUITE_DIR/evidence.json"
```

故障/升级由主操作者串行操作集群；用同一 journal 在前后各执行一次观察：

```bash
python scripts/e2e_k8s_runtime.py --stage fault-upgrade --event manager-restart --checkpoint before --evidence "$SUITE_DIR/evidence.json"
# Operator performs the scoped real restart, then waits for recovery.
python scripts/e2e_k8s_runtime.py --stage fault-upgrade --event manager-restart --checkpoint after --evidence "$SUITE_DIR/evidence.json"
```

`platform` 保留上线实例供故障/升级检查；`all` 的 finally 会清理，因此需要中间故障注入时使用分阶段入口。`cleanup` 只通过真实平台 API 清理该 journal 的 `e2e-f059-` 应用，保留证据文件；不会移除测试部门、人员、profile 或平台存储配置。

## 6. 离线新增依赖

首次最小包无需新增 wheel。新增第三方依赖必须提前在匹配 profile/Python ABI/目标架构的可信环境下载完整 wheel 闭包，生成锁文件和每个文件的真实 SHA256；无匹配 wheel 时需要先在可信构建环境生成 wheel，不能让目标离线机器临时访问公网或假装安装成功。

`offline-manifest.example.json` 只是占位模板，必须填入平台实际 resolve 的 `profile_id`、`profile_digest`、`platform`、`abi`，以及所有 wheel 的真实大小/哈希后命名为 `offline.json`。归档应包含 `offline.json` 和 `wheels/*.whl`，禁止凭据配置/符号链接/路径穿越。整个归档也要计算真实 SHA256。

用 owner JWT 将原始归档流上传 `/api/v1/apps/{app_id}/runtime/materials?profile=e2e-f059-python311%401&platform=linux%2Famd64&sha256=<archive SHA256>`（不是 multipart），将返回 `artifact_id` 填到应用 manifest 的 `delivery.dependencies.offline_artifacts` 中。需在首次应用创建后上传私有物料；公共物料由超管显式上传 `/api/v1/runtime/materials/public`，两种 scope 不能混淆。

requirements/显式 lock 中使用真实 `package==version --hash=sha256:<wheel SHA256>`。`delivery.dependencies.lock` 指向包内锁文件。物料完成格式与哈希校验只是可供准备，依赖闭包仍须在目标 preparer 内实际离线解析、安装和验证。

## 7. 本地验证

```bash
python -m pytest -q -o addopts='' scripts/fixtures/f059/test_bootstrap.py
node --check scripts/fixtures/f059/node_demo.js
```

合同测试用 MockTransport/严格 API double，不访问远端；Python 协议烟测仅监听 loopback、使用临时 SQLite 和本地 SDK 存储目录。完整的 189/109 部署、准入、网络隔离和权限 E2E 不包含在这些测试结论中。
