# 验证记录

日期：2026-10-20。本文保留首次本地验证结果；109:13001 最新验收基于真实 main 新测试库升级，见 [main 基线恢复与联调](./main-baseline-109-recovery-20261020.md)。[首次环境报告](./e2e-109-20261020.md) 保留历史追溯。

## 基线

| 仓库 | 工作区 | 分支 / 基线 |
| --- | --- | --- |
| BiSheng | /Users/zhangguoqing/.codex/worktrees/bisheng-work-110/bisheng | feat/bisheng-work-110，实施前 HEAD a2b7860d8efed08fdee41e9ecdf46560ed5ef0bb |
| Desktop | /Users/zhangguoqing/works/bisheng-work/.worktrees/dsh-without-gateway | codex/dsh-without-gateway，创建时 origin/V1.1.0 = 5ee11bddf915a29af6d9252ead9b3f8343dba544 |

用户指定的 v1.1.0 对应远端实际分支名 V1.1.0，已核对并从该分支创建。原客户端主工作区及其未提交文档未修改。

## 已执行

| 检查 | 实际结果 / 证据边界 |
| --- | --- |
| 后端 DSH 本地回归 | 532 passed、106 skipped、54 deselected；不包含未配置的外部数据库/Redis用例和原 test_dsh_e2e.py |
| 最终严格租户模式回归 | test_native_access.py 单独启用真实 SQLAlchemy 租户事件，11 passed；包含 Root 可见时会话不串租户 |
| Python → Desktop 契约 | 新服务真实签发 Token 响应，经客户端 contract.js 的 parseToken 校验；跨仓库测试通过 |
| 管理端 DSH 回归 | 35 files / 300 tests passed，包含额度界面、默认导航、设置、用量和模型审计 |
| 管理端类型 / 构建 | pnpm --filter bisheng typecheck、pnpm --filter bisheng build 通过 |
| 改动管理端文件 ESLint | 11 个仍存在的改动 TS/TSX 文件检查通过；未新增豁免 |
| 多语言 | pnpm check-i18n 通过，无新增 drift |
| 后端 lint | 改动的 52 个现存 Python 文件 Ruff 通过；DSH 模块整体 Ruff 通过 |
| 架构守卫 | 对 72 个现存修改源码/测试文件逐个运行；无 VIOLATION，仅原 test_profile_outbox.py 合成密码 fixture 的 RULE-7 WARNING |
| Alembic | main 原有 83 个文件不变，仅追加 work110_dsh_local_sessions；迁移/模型建表专项 14 passed、1 外部 MySQL skipped。旧 109 merge head 已撤回；实际新库 main 128 表 → 功能版本 143 表，唯一已有表变化为 dsh_model_call；重复 upgrade 结构不变 |
| Desktop 安装 | npm ci 成功，postinstall 的 patch-package、品牌资源与 Electron 安装步骤完整成功 |
| Desktop 类型 / 构建 | npm run typecheck、npm run build 通过 |
| Desktop 完整测试 | 225 files passed / 1 skipped；1931 passed / 2 skipped。覆盖企业连接、审计元数据和既有 Harness 子进程测试；不等同于原生 UI 联调 |
| 差异检查 | 两仓库 git diff --check 通过 |

后端原生认证测试运行真实 SQLite 事务、JWT 加解签、Repository 和 FastAPI TestClient 流程；Redis边界使用可控存储替身，平台自然人记录是合成记录。该结果证明本地实现逻辑和契约，不能证明真实 Redis Lua、MySQL/DM 行锁、平台登录及 Electron 组合部署已验收。

## 完整质量门禁的已有问题

本次运行了完整 pnpm lint 和平台 pnpm lint:prune，仍有 **93 个原有错误**，分布在以下未修改文件；git diff HEAD 已核对这些路径没有本次差异。没有手工修改 suppressions，也没有扩大修复范围。

- platform/src/components/bs-comp/chatComponent/CitationReferencesDrawer.tsx
- platform/src/controllers/API/index.ts
- platform/src/controllers/API/license.ts
- platform/src/pages/BuildPage/bench/WorkbenchSensitivePolicy.tsx
- platform/src/pages/BuildPage/flow/FlowChat/MessageMarkDown.tsx
- platform/src/test/f067LicenseBannerCopy.test.ts

完整 pnpm typecheck 在 platform 通过后，停在未修改的 client/src/hooks/useAiChat.test.ts:294：测试对象缺少 ChatMessage 必填字段。由于该命令使用 &&，后续 file-viewers 检查未由此命令执行。完整前端门禁不能报告通过。

## 可复跑的后端本地集合

在 src/backend 激活 Python 3.11 环境，设置指向独立测试配置的 config（不要借用生产服务）。可选设置 DSH_DESKTOP_SOURCE_DIR 为新客户端 worktree，以执行跨仓库解析校验。以下选择器只用于明确未提供外部资源的本地执行，不能替代 CI 的未过滤集成测试：

```python
import pytest

class LocalOnly:
    def pytest_collection_modifyitems(self, config, items):
        keep, excluded = [], []
        for item in items:
            params = getattr(getattr(item, "callspec", None), "params", {})
            external = any(value == "external" for value in params.values() if isinstance(value, str))
            needs_store = {"dsh_redis_url", "dsh_database_url"} & set(item.fixturenames)
            (excluded if external or needs_store else keep).append(item)
        items[:] = keep
        config.hook.pytest_deselected(items=excluded)

raise SystemExit(pytest.main([
    "test/dsh", "--ignore=test/dsh/test_dsh_e2e.py", "-q", "-p", "no:cacheprovider"
], plugins=[LocalOnly()]))
```

外部 SQL fixture 必须使用以 dsh_test_ 开头的隔离库；Redis 必须显式提供 DSH_TEST_REDIS_URL 和 DSH_TEST_REDIS_ISOLATED=1。生产地址不能用于这些测试。

## AC 证据与未完成项

| AC | 本地证据 | 真实环境补验 |
| --- | --- | --- |
| AC-01 | native_access 的浏览器确认、PKCE、ticket、换证；Celery 无 Gateway 配置导入 | 无 Gateway 部署上的实际平台登录 + Electron 回调 |
| AC-02 | refresh 轮换/重放提交撤销、幂等退出、设备独立、worker 关闭 | MySQL/DM 并发 refresh、崩溃恢复 |
| AC-03 | 当前身份、错误 JWT 用途/结构、跨租户及 Root 会话隔离、原浏览器 CSRF 测试 | 真实账号停用、转租户、PAT/SAK 拒绝 |
| AC-04 | 授权重试无 HTTP 调用，不再查询人数或占席；新成员继承 | 第 11 位及更多成员在无 License 环境登录调用 |
| AC-05 | user_grant_switch 和 subject_policy 的低个人额度覆盖及取消继承 | 部门 100 万、个人 30 万 / 200 万界面和模型调用 |
| AC-06 | SQL 两成员独立策略、现有 tenant/user/model/month 键与计量代码保留 | 真实 Redis 独立余额，来源变更不重置累计 |
| AC-07 | 个人 enabled=true 零额度拒绝；enabled=false 恢复部门 | 原生客户端列表和调用拒绝展示 |
| AC-08 | 模型采集、标题、树与审计管理回归；Desktop 完整审计测试 | 实际正文持久化、解密及父子会话/标题查验 |
| AC-09 | 无席位 Principal 的模型调用；历史字段可空且正版本仍受约束 | 存量用量、Redis 积压投影和 DM DDL 预演 |
| AC-10 | 商业 UI/API和后台资料任务退出；模型审计入口与 worker 保留 | 检查部署代理和手工 Beat 配置，无远程重试 |
| AC-11 | /api/dsh 与 /api/v1/dsh 共享行为；Desktop 新路径 mock HTTP 回归 | 旧安装包经兼容别名重新登录 |

## 原生 UI / 发布检查清单（按实际覆盖更新）

- [x] 完全停止 Gateway，移除 Gateway HMAC，代理认证路径到 Python；从平台原生登录开始完成 DSH 登录。
- [ ] 新旧客户端登录、刷新、退出及本人设备撤销；两个设备互不影响；跨副本重启凭证仍可验证。
- [x] 部门与个人额度配置、个人零额度和恢复继承；两个成员实际调用模型并核对各自余额。
- [ ] 当月用尽、降低额度、UNKNOWN 与 SSE 中断，核对实际结算及历史记录未归零。
- [ ] 查看模型审计正文、message_sources、父子会话和标题；插件市场及工作台使用同一本地身份。
- [ ] MySQL/DM 升级预演、行锁并发、ROLE 运维迁移和回退数据兼容。

发布步骤见 [deployment.md](./deployment.md)。当前状态是代码实现、本地验证及本次要求的 109 真实链路验证完成；其余发布清单及全仓原有前端门禁问题仍保留。

## main 基线修正

2026-10-20 按 main 与 work-110 的实际模型差异移除 13 个外来/重复迁移，仅保留已有模型调用表的 DDL。修正后本地 DSH 回归 529 passed、107 skipped、54 deselected；跳过项与外部数据库/Redis等显式前置条件相关。历史 109 结果保留作追溯，完整归档及新库升级过程见 [main 基线恢复记录](./main-baseline-109-recovery-20261020.md)。

新库实际验收完成：6 个迁移检查 + 1 个真实登录/额度/调用/审计端到端场景共 7 passed；本地 Electron 重新登录并完成 qwen-max 调用，审计正文解密核验通过。个人 10000 优先于部门 100000、取消个人配置继承部门、两个成员分别使用 30 Token 及用量不清零均已在新库验证。原库保留 2132 条调用、917 条审计请求。证据及归档位置见上述 main 基线记录；这些结果替代旧跨版本线直接升级的部署结论，不扩大其余发布检查的通过范围。
