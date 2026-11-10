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

`--profile-revision` 只接受正整数，默认 `1`。镜像 digest、CA 层、toolchain 或其它 profile 内容变化时必须使用新修订号，例如：

```bash
python scripts/bootstrap_f059_acceptance.py \
  --api-base "$API_BASE" --suite-dir "$SUITE_DIR" --env-file "$PLATFORM_ENV" \
  --profile-inventory "$UPDATED_INVENTORY_FILE" --profile-revision 2 --bootstrap
```

同一 code/revision 的内容不可覆盖；脚本不自动重试覆盖或偷偷增加 revision。重复相同修订和相同内容可复用。三个 profile 均以指定 revision 导入并设为默认；bundle manifest 显式引用 `e2e-f059-<language>@2`。**source-image 当前 schema 不允许 `delivery.profile` 字段**：K8s 兼容链路从当前语言默认 profile 解析并冻结，因此必须先完成新修订的 bootstrap/default 设置，再重新发布 source-image；不能向 manifest 添加非法字段。已冻结的旧版本不会因默认值变更而原地改镜像。

输出 `e2e.env`、marker、三个 profile 定义、五组源码包（完整镜像场景暂不生成）、`scenarios.json`，以及 `demo-image-v1/`、`demo-image-v2/` 构建上下文。bundle 和 npm 初始场景没有新增依赖；Python bundle 使用预制 runtime 中的标准库和 SDK/httpx，Node 只用内置模块。Docker source-image 使用裸 Python 基础镜像，必须另外提供下面的离线 vendor 材料；不能假定 bundle 的依赖会自动进入源码镜像。

### Docker source-image 的显式离线材料

Docker 兼容构建与 K8s 兼容组装的前置不同：

- Docker 通过 Engine Build API 按平台模板构建，固定基础镜像为本机 `python:3.11-slim`，不使用运行 profile 的 `app-python` 镜像。离线模式下构建网络为 `none`。必须先准备这个精确基础引用；导入另一个标签不代表已经满足。
- K8s source-image 从当前语言默认 profile 冻结运行环境并经受限 OCI 组装推送，仍须满足 profile、离线依赖、仓库及安装报告条件。`delivery.profile` 不是 source-image 的合法 manifest 字段。
- Python fixture 顶层导入真实 `bisheng_sdk`，并实际调用 SDK/附件接口。空 `requirements.txt` 加裸 Python 不能运行它；仅设置平台 simple index 地址也不能补齐禁网构建的依赖。

为此新增显式 `--source-wheelhouse DIR`。它只读取操作者提供的本地材料，不执行 wheel 代码、不调用 pip、不访问网络，也不读取或复制开发机 venv。脚本校验每个 wheel 的 SHA-256、纯 Python 标签、固定版本、完整集合、常规文件和许可证，拒绝 native wheel、`.pth`、软链接、路径穿越、文件覆盖及超限内容。SDK wheel 必须与本仓库 `bisheng_sdk-0.1.1-py3-none-any.whl` 完全一致。

本轮夹具只支持下列已准备的材料组合，不是通用依赖解析器；不能据此保证其他版本组合兼容：

| 分发包 | 固定版本 |
|---|---|
| bisheng-sdk | 0.1.1 |
| httpx | 0.28.1 |
| httpcore | 1.0.9 |
| h11 | 0.16.0 |
| anyio | 4.15.1 |
| idna | 3.20 |
| certifi | 2026.10.19 |
| typing_extensions | 4.16.0 |

在已验收、固定镜像身份的 Python preparer 中，从 `/opt/bisheng/wheelhouse` 只读提取这些原始 `py3-none-any.whl` 到操作者的专用材料目录。可以由操作者创建一个不启动的临时容器并 `docker cp`，随后仅删除记录的那个容器 ID；不要从任意 `site-packages`、开发 venv 或公网补包。保留来源镜像 digest/config ID、原生平台和材料 SHA 作为证据。

目录格式如下；哈希必须从实际文件计算，占位符不能使用：

```text
source-wheelhouse/
├── source-vendor.json
└── wheels/
    ├── bisheng_sdk-0.1.1-py3-none-any.whl
    └── ...其余七个固定 wheel
```

```json
{
  "format": "f059-source-wheelhouse-v1",
  "python": "3.11",
  "wheels": {
    "wheels/bisheng_sdk-0.1.1-py3-none-any.whl": "sha256:<actual file digest>",
    "wheels/httpx-0.28.1-py3-none-any.whl": "sha256:<actual file digest>"
  }
}
```

上面的 JSON 仅展示两项写法，实际必须列齐八项。八个 wheel 保持原始字节（含 `.dist-info`、证书和许可证），放入 `_vendor/wheels/`，通过 Python zipimport 加载，不在构建时展开或安装。SDK wheel 未携带许可证文件，脚本另外将仓库的 Apache-2.0 `LICENSE` 放到 `_vendor/licenses/bisheng-sdk/LICENSE`，不修改 wheel 本身。目录和文件不得经过软链接。

```bash
python scripts/bootstrap_f059_acceptance.py \
  --api-base "$API_BASE" --suite-dir "$SUITE_DIR" --env-file "$PLATFORM_ENV" \
  --profile-inventory "$INVENTORY_FILE" --profile-revision "$PROFILE_REVISION" \
  --source-wheelhouse "$SOURCE_WHEELHOUSE" \
  --demo-image "$DEMO_IMAGE_V1_DIGEST_REF" --demo-image-v2 "$DEMO_IMAGE_V2_DIGEST_REF" \
  --prepare-only
```

只有 source-image 的 v1/v2 包增加原始 wheel、SDK 许可、经过校验的材料清单和 `main.py` 的 zipimport 路径引导；其 `requirements.txt` 保持为空，平台模板仍从裸基础镜像构建。bundle、完整镜像和 SDK 正向断言不变。未传材料时仍生成兼容现有 K8s profile 的 source-image 场景，但 `scenarios.json` 明确标注 `docker-vendor-unprovided-kubernetes-profile-required`，不表示 Docker 前置已满足。

现有发布扫描器将这八个 wheel 逐项记录为 `binary` 跳过，不打开依赖源码扫描；不能写成全部源码扫描通过。应用自身的 `main.py`、manifest 等仍按原规则扫描，真实形态的密钥必须被拒绝，不增加忽略目录或修改 SDK。材料完整性和来源由逐 wheel 哈希、仓库 SDK 字节核验及许可证证据负责。此前直接展开 SDK 的方案在三处环境变量/请求头常量遇到扫描假阳性，原失败证据应保留。

在发布前，用实际打包的源码和材料在**裸 Python 基础镜像、禁网、非 root、只读根文件系统**条件下执行真实 SDK import、HTTP/SQLite/本地附件、WebSocket，以及 certifi 证书资源读取和本地可信/不可信 CA 配对 TLS 烟测。该结果只证明这组材料可以运行；平台 OBO、附件存储、权限和审批仍由真实平台 E2E 验证。若已有发布尝试，不要原地改旧包/旧 journal，使用新的应用 suffix 和独立证据批次，保留原失败记录。

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

下例 `%401` 表示 `@1`；使用 revision 2 时应改为 `%402`，并重新 resolve 对应 profile 后制作物料，不能复用旧修订的 profile_digest。用 owner JWT 将原始归档流上传 `/api/v1/apps/{app_id}/runtime/materials?profile=e2e-f059-python311%401&platform=linux%2Famd64&sha256=<archive SHA256>`（不是 multipart），将返回 `artifact_id` 填到应用 manifest 的 `delivery.dependencies.offline_artifacts` 中。需在首次应用创建后上传私有物料；公共物料由超管显式上传 `/api/v1/runtime/materials/public`，两种 scope 不能混淆。

requirements/显式 lock 中使用真实 `package==version --hash=sha256:<wheel SHA256>`。`delivery.dependencies.lock` 指向包内锁文件。物料完成格式与哈希校验只是可供准备，依赖闭包仍须在目标 preparer 内实际离线解析、安装和验证。

## 7. 本地验证

```bash
python -m pytest -q -o addopts='' scripts/fixtures/f059/test_bootstrap.py
node --check scripts/fixtures/f059/node_demo.js
```

合同测试用 MockTransport/严格 API double，不访问远端；Python 协议烟测仅监听 loopback、使用临时 SQLite 和本地 SDK 存储目录。完整的 189/109 部署、准入、网络隔离和权限 E2E 不包含在这些测试结论中。
