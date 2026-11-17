# 3.1 beta1 开发接续

更新时间：2026-11-17。当前为开发草稿，未合并、未声明生产验收完成。

## 分支与基线

- 毕昇：`dataelement/bisheng` 的 `feat/multimodal-finetune-3.1.0-beta1`，父提交为 `feat/3.1.0-beta1` 的 `c0a32dd061b223238c200cbbcf8b3e0595a20704`。
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

数据库迁移 `f111_multimodal_finetune` 接在 `v310b1_f016_dsh_call_pricing` 后，使用新版公共迁移工具和 JsonType。新增数据集表仍由项目模型初始化流程创建，需在实际部署时验证全新安装及已有数据库升级。

## 本次本机检查

- 毕昇后端：67 项通过，覆盖多模态契约、上传、数据导入、三模态交付及 Alembic 单 head。
- FT：24 项服务测试通过。
- 平台前端：22 项测试通过，覆盖数据集 API、创建与预览、列表筛选和改名失败重试。
- 平台 TypeScript：1328 个 strict 文件通过；变更文件 ESLint 通过，未修改历史 suppression 文件。
- 平台生产构建通过，存在大 chunk 提示；未做整仓依赖重新安装，使用本机已有依赖完成编译。
- 变更后端文件 Ruff、架构守卫和提交差异检查见 PR 验证记录。

复测命令：在 `src/backend` 执行 `python -m pytest test/finetune/test_finetune_multimodal_contract.py test/finetune/test_finetune_upload_validation.py test/finetune/test_three_modal_delivery.py test/finetune/test_dataset_import.py test/database/test_alembic_single_head.py -q`；在 `src/frontend/platform` 执行 `pnpm exec tsc-strict`、`pnpm build` 和相关 `vitest run`。后端测试需要按项目开发说明准备基础配置。在 FT 根目录执行 `python -m pytest tests/sft_server -q`。

## 尚待完成

1. 全新环境执行 frozen-lockfile 安装并构建；本机检查不能替代干净环境 CI。
2. 3.1 beta1 平台实际数据库升级（MySQL/DM）及登录网页 E2E：导入→版本持久化/复用→预检→真实训练→产物→新样本推理。
3. 真实权限和跨租户隔离、取消/重启恢复、FTPS 证书握手和客户网络配置验收。
4. 使用本次分支重新跑文本、图文、视频小样本训练。历史环境完成过这三类训练与重载，但本次迁移未重新占用 GPU，不能把历史结果当作本分支整体验收。

不包含模拟训练路径、音频能力或自动发布到业务推理服务。历史任务清单引用的原始证据因包含环境信息未提交；勿把勾选记录等同于本分支已验收。
