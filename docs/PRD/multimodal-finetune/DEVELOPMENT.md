# 3.1 beta1 开发接续

更新时间：2026-11-20。当前为开发草稿，未合并、未声明生产验收完成。

## 分支与基线

- 毕昇：`dataelement/bisheng` 的 `feat/3.1.0-beta1-025-multimodal-finetune`（2026-11-20 从 `feat/3.1.0-beta1@4bfe411b10` 新拉，旧分支 `feat/multimodal-finetune-3.1.0-beta1` 的全部改动压成一组合入）。
- FT：`codesstar/bisheng-ft` 的 `feat/text-image-video-lora`，基于 `dataelement/bisheng-ft` 的 `main` 提交 `19495bda1755e40760021310c21fff1ee47b13e0`。FT 没有配套的 3.1 beta1 分支。
- 两个分支需配套运行。训练入口为 FT 的 `/v2.1/sft`，独立部署说明见 FT 仓库 `deploy/multimodal/README.md`。

新电脑获取源码：

```bash
git clone --branch feat/multimodal-finetune-3.1.0-beta1 https://github.com/dataelement/bisheng.git
git clone --branch feat/text-image-video-lora https://github.com/codesstar/bisheng-ft.git
```

使用原有 checkout 时先保存自己的未提交修改，再 fetch 并切到上述远程分支。运行配置、SSH 密钥、访问令牌和数据卷需通过企业已有安全渠道单独配置；仓库仅提供示例，不包含测试服务器访问资料。

## 本次迁移

迁入正式平台的前后端代码、数据集版本与导入、任务/日志/产物/推理接口、三语言页面、示例数据、FT 调用契约、迁移和测试。保留现有列表筛选和任务改名失败重试行为，适配 3.1 beta1 的 `@bisheng/ui` 组件与拒绝型请求错误处理。轮询不因翻译函数变化而反复清空详情。

数据库迁移 `v310b1_f025_multimodal_finetune`（文件 `v3_1_0b1_f025_multimodal_finetune.py`）接在 `v310b1_f016_dsh_call_pricing` 后，使用新版公共迁移工具和 JsonType。新增数据集表仍由项目模型初始化流程创建，需在实际部署时验证全新安装及已有数据库升级。

## 本次本机检查

- 毕昇后端：67 项通过，覆盖多模态契约、上传、数据导入、三模态交付及 Alembic 单 head。
- FT：24 项服务测试通过。
- 平台前端：22 项测试通过，覆盖数据集 API、创建与预览、列表筛选和改名失败重试。
- 平台 TypeScript：1328 个 strict 文件通过；变更文件 ESLint 通过，未修改历史 suppression 文件。
- 平台生产构建通过，存在大 chunk 提示；未做整仓依赖重新安装，使用本机已有依赖完成编译。
- 变更后端文件 Ruff、架构守卫和提交差异检查见 PR 验证记录。

复测命令：在 `src/backend` 执行 `python -m pytest test/finetune/test_finetune_multimodal_contract.py test/finetune/test_finetune_upload_validation.py test/finetune/test_three_modal_delivery.py test/finetune/test_dataset_import.py test/database/test_alembic_single_head.py -q`；在 `src/frontend/platform` 执行 `pnpm exec tsc-strict`、`pnpm build` 和相关 `vitest run`。后端测试需要按项目开发说明准备基础配置。在 FT 根目录执行 `python -m pytest tests/sft_server -q`。

## 2026-11-18 接续

- 合入 `feat/3.1.0-beta1@acefcd907d`（无冲突），功能改号 F025，清理过期的 ESLint 豁免。
- 新增数据直传：训练服务下载不到平台存储链接时，平台把训练数据和验证媒体推给它（FT `POST /v2.1/sft/probe`、`PUT /v2.1/sft/files/{sha256}`，引用 `ft-file://<sha256>`），任务详情显示本次用的是拉取还是直传；送不到时报 10131。
- 新增 SFTP 导入（账号密码，可选主机指纹校验，依赖 paramiko）。
- 两机实测：平台跑在开发机，FT 跑在 GPU 服务器（单卡 RTX 3090，与他人服务共卡），GPU 访问不到开发机。三类训练、产物检查、新样本推理全部通过平台完成并自动走直传；FTP、SFTP、S3 各 4 种导入组合通过，异常场景正确拦截。拉取模式在两机下尚未实测。
- 复测命令同上；FT 测试 29 项，平台 `test/finetune` 78 项。

## 2026-11-19 接续

- 远程数据直达训练服务：FTP/FTPS、SFTP、S3 导入时平台只读清单、核对每个文件存在并记录大小、取前 3 条样本做预览，存成一个小的「导入计划」版本；开始训练时用户再输一次密码或密钥，只随本次任务发给 FT，FT 先登录并读一个文件（失败报 10132、不建任务），再直接从数据源下载并核对大小。文本远程清单仍存成平台内的 JSON 版本。
- 本地上传上限 2 GiB（JSON/JSONL 200 MiB），服务端流式哈希和检查，预览改为服务端保存的预览包（浏览器不再读整包）；不做断点续传。
- nginx 给 `/api/v1/finetune/job` 和 `/api/v1/finetune/job/file` 单独 2100m 与 1800 秒（docker、前端镜像、helm 三处）：2 GiB 包第一次训练时，创建任务要等平台把包直传给 FT。
- FT 镜像需要 paramiko、minio（`deploy/multimodal/Dockerfile` 已加）；GPU 服务器必须能访问数据源。
- 两机实测：FT 和临时 FTP/SFTP/S3 数据源在 GPU 服务器，平台在开发机。6 种远程导入（含 0.9 GB、1700 张图的 SFTP 数据集）全部训练成功，平台只读了清单和预览图；错误密码、缺密码、导入后来源文件被改都被正确拦下；1.5 GB 本地包经 nginx 上传并训练成功；GPU 任务目录和日志、平台日志均未发现数据源密码。顺带修复 FT 对只有 instruction/output 的文本行报 `KeyError: 'input'`。
- 复测：FT 测试 43 项，平台 `test/finetune` 92 项，创建页相关前端测试 22 项。

## 2026-11-20 接续

- 恢复 Freeze 和全量：新训练服务上文本模型可选 LoRA / Freeze / 全量，图文、视频模型可选 LoRA / Freeze（全量单卡放不下，页面置灰并说明）。全量默认学习率 1e-5；Freeze 新增「可训练层数」。两者都产出完整模型，推理验证直接加载任务目录里的模型。
- 登记的训练服务太旧（没有能力目录接口）时报 10133，提示升级训练服务。
- 真机：Qwen3-0.6B 全量、Freeze 和 Qwen2.5-VL-3B 图文 Freeze 各 4 步训练并完成新样本推理。FT 测试 47 项、平台 `test/finetune` 93 项。

## 2026-11-20 改到最新 beta1

- 从 `feat/3.1.0-beta1@4bfe411b10` 新拉分支，合入时与上游 11-18～11-19 的微调权限和租户隔离改动（5 个提交）冲突，按「保留上游权限 + 补回 F025 功能」逐处合并，详见 design.md「合入 beta1 的权限与隔离」。
- 上游测试的训练文件样例原来是空列表 `[]`，F025 会拒收空数据，改为一条合法样例；上游测试夹具补建数据集版本表。
- 复测：后端 `test/finetune` + 迁移单 head + 请求范围登记 266 项通过（`requestScopeRoutes.json` 按路由重新生成，新增 9 条）；前端微调相关 99 项通过，全量失败的 21 个测试文件与干净 beta1 完全相同；lint（已 prune）、typecheck、check-i18n 通过。

## 尚待完成

1. 全新环境执行 frozen-lockfile 安装并构建；本机检查不能替代干净环境 CI。
2. 3.1 beta1 平台实际数据库升级（MySQL/DM）及登录网页 E2E：导入→版本持久化/复用→预检→真实训练→产物→新样本推理。
3. 真实权限和跨租户隔离、取消/重启恢复、FTPS 证书握手、真实 OSS 账号、商业版网关的上传大小与超时、helm 模板渲染和客户网络配置验收。
5. 合入最新 `feat/3.1.0-beta1`（2026-11-19 已领先本分支 137 个提交）。
4. ~~使用本次分支重新跑文本、图文、视频小样本训练~~：2026-11-18 已在 GPU 上通过平台完成（见上节）。仍需在拉取模式的部署（GPU 能访问平台存储）下再跑一轮。

不包含模拟训练路径、音频能力或自动发布到业务推理服务。历史任务清单引用的原始证据因包含环境信息未提交；勿把勾选记录等同于本分支已验收。
