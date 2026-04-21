# Tasks: 企业微信组织同步 Provider

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.1
**基线依赖**: [v2.5.0/F009-org-sync](../../v2.5.0/009-org-sync/)（必须已合并到 2.5.0-PM 并可运行）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已草 + R1~R5 对齐（2026-04-20） | spec §0 记录修订历史 |
| tasks.md | ✅ 已草 + R1~R5 对齐 | 8 个任务拆解不变，T001/T003/T005/T006/T007 文字更新 |
| 实现 | ✅ 完成（2026-04-20） | 8 / 8 完成；后端 91 单测 + 17 E2E 全绿，前端 TypeScript 无 error |

---

## 开发模式

- **后端 Test-First**：Provider 实现前先写单测（mock httpx），覆盖 AC-39~AC-58 的关键路径。
- **前端 Test-Alongside**：暂用手动验证 + E2E API 测试替代前端自动化。
- **真环境验证**：企微测试账号（corpid=`wwa04427c3f62b5769`, AgentId=`1000017`, Secret=`qVldC5Kp5houi1fG8yBvmZMaufN2KmFNkijdls1DdVc`）在 114 服务器网络环境下需验证可达；如需通过代理走企微 API，先在 `config.yaml` 补代理配置（本 Feature 不处理代理，只在实际偏差中记录）。

---

## Tasks

### 基础适配（无测试配对）

- [x] **T001**: `auth_config` WeCom 分支校验（**R2 修订：删除脱敏扩展**）
  **文件**: `src/backend/bisheng/org_sync/domain/schemas/org_sync_schema.py`
  **逻辑**:
  - `OrgSyncConfigCreate` 新增 `model_validator(mode='after')` `validate_auth_config`：当 `provider='wecom'` 时校验 `auth_config['corpid']` / `['corpsecret']` / `['agent_id']` 必须是非空字符串；`allow_dept_ids` 如存在必须是 `list[int]` 且每个元素 `isinstance(x, int)` 并且不是 bool（防 `True`/`False`）。
  - `OrgSyncConfigUpdate` 对称加分支，允许 `corpsecret='****'`（保留原值语义）。
  - **不改** `mask_sensitive_fields()`：F009 既有 `'secret' in key.lower()` 子串匹配已覆盖 `corpsecret`。
  - **不新增**常量：不需要 `WECOM_SENSITIVE_FIELDS`。
  - 写对应的 pytest 单测：`test/test_org_sync_wecom_schema.py` 覆盖 AC-36/37（缺失字段、非法 allow_dept_ids），并补一条 `test_wecom_corpsecret_auto_masked` 确保 `mask_sensitive_fields({'corpsecret': 'x', 'corpid': 'y'})['corpsecret'] == '****'`。
  **覆盖 AC**: AC-36, AC-37, AC-38（AC-57/58 通过 F009 既有脱敏自动覆盖）
  **依赖**: 无

- [x] **T002**: `OrgSyncService` 注入 `_config_id` 到 auth_config
  **文件**: `src/backend/bisheng/org_sync/domain/services/org_sync_service.py`
  **逻辑**:
  - 在 `execute_sync` / `test_connection` / `preview_remote_tree` 调 `get_provider(provider, auth_config)` 之前，先 `auth_config['_config_id'] = config.id`（只在内存字典改，不回写 DB）。
  - 加上注释：`_config_id 仅供 Provider 内部使用（如 WeCom Redis key），不加密不持久化。`
  - 回写 DB 前（`update_config`）主动 `auth_config.pop('_config_id', None)`。
  **覆盖 AC**: AC-50, AC-51, AC-52（间接支撑 Redis key 隔离）
  **依赖**: T001

### WeComProvider 实现（Test-First 配对）

- [x] **T003**: WeComProvider 单元测试（**R5 修订**）
  **文件**: `src/backend/test/test_wecom_provider.py`
  **逻辑**: 使用 `httpx.MockTransport`（标准库，零新增依赖）桩住企微 API；Redis 用 `fakeredis.aioredis.FakeRedis`，monkeypatch `bisheng.org_sync.domain.providers.wecom.get_redis_client` 返回含 `async_connection` 属性的 stub。
  用例清单：
  - `test_ensure_token_cache_hit` → AC-51：Redis 预置 token，`_ensure_token` 不调 gettoken
  - `test_ensure_token_first_call` → AC-50：首次调用写 Redis，TTL ≈ 6900s
  - `test_ensure_token_concurrent_lock` → AC-52：两个并发 `_ensure_token` 只触发一次 gettoken
  - `test_token_invalidate_on_42001` → AC-53：业务 API 返回 42001 → invalidate → 重新 gettoken → 重试一次
  - `test_rate_limit_backoff_45009` → AC-54：三次 45009 后一次成功；总延时 ≈ 1+2+4s
  - `test_rate_limit_exhausted` → AC-54：4 次全 45009 → `OrgSyncFetchError`
  - `test_auth_failed_40001` → AC-40：gettoken 返回 40013 → `OrgSyncAuthFailedError`，异常 msg 不含 corpsecret
  - `test_auth_failed_60011_visible_range` → AC-41：业务 API 返回 60011 → 错误消息含"可见范围"
  - `test_fetch_departments_default_root` → AC-42：root_dept_ids=None → 调 `id=1`，返回 DTO 列表，root 的 parent 为 None
  - `test_fetch_departments_multi_root_dedupe` → AC-43：两个 root 返回有交集 → 按 external_id 去重
  - `test_fetch_departments_id_to_string` → AC-44：响应 id=123（int） → DTO external_id='123'
  - `test_fetch_members_main_department` → AC-46：main_department=10 → primary='10'，其余 depts 进 secondary
  - `test_fetch_members_no_main_department` → AC-47：响应无 main_department → primary=str(department[0])
  - `test_fetch_members_status_mapping` → AC-48：status=1/2/4/5 → active/disabled/disabled/disabled
  - `test_fetch_members_dedupe_across_roots` → AC-49：userid "lisi" 在两个 root 下都返回 → DTO 合并 secondary
  - `test_test_connection_success` → AC-39：返回 connected=True + total_depts/total_members 且无 token 字段
  - `test_no_secret_leakage` → AC-58：遍历所有异常的 `str(exc)`、`repr(exc)`、mock 记录到的 log，断言均不含 corpsecret 原文
  **测试**: pytest `test/test_wecom_provider.py -v`
  **基础设施**: 依赖 F000 conftest（若 WeCom 测试需要 Redis mock，新增 `redis_mock` fixture，与 Feishu 测试共享）
  **依赖**: T001, T002

- [x] **T004**: WeComProvider 实现
  **文件**: `src/backend/bisheng/org_sync/domain/providers/wecom.py`
  **逻辑**:
  - 完全替换现有 stub（36 行 → 预计 250~300 行），参照 `feishu.py` 风格。
  - 常量：`WECOM_BASE_URL = 'https://qyapi.weixin.qq.com'`；`TOKEN_TTL_BUFFER = 300`；`MAX_RETRIES = 4`；`BACKOFF_BASE = 1`。
  - `__init__`：校验 `auth_config` 必填键，存 `_config_id` 到 `self._config_id`；`self._semaphore = asyncio.Semaphore(5)`。
  - `_ensure_token`：流程见 spec §7.1；获取锁失败 sleep 200ms 再读 Redis；仍为空抛 `OrgSyncProviderError`（避免死循环）。
  - `_request`：Semaphore 限并发 → 发请求 → 解析 `errcode`：
    - 0 → 返回 data
    - 42001 / 40014 → invalidate + 刷新 + 重试一次（尾递归或 while，防止无限）
    - 45009 / 45033 / 45011 → 指数退避
    - 40001 / 40013 / 60011 / 42009 → `OrgSyncAuthFailedError`
    - 其他 → `OrgSyncFetchError(msg=f"WeCom API error {errcode}: {errmsg}")`
  - `authenticate`：仅调 `_ensure_token` 一次，成功即 True。
  - `fetch_departments`：
    - 确定 roots = `root_dept_ids or auth_config.get('allow_dept_ids', [1])`
    - 对每个 root 调 `/cgi-bin/department/list?id={root}`
    - 合并去重，root 自身的 `parent_external_id` 置 None
  - `fetch_members`：
    - 确定 roots（同上）
    - 对每个 root 调 `/cgi-bin/user/list?department_id={root}&fetch_child=1`
    - 按 userid 去重；合并多 root 下的 secondary departments
    - `primary_dept_external_id` = `str(item.get('main_department') or (item['department'][0] if item['department'] else ''))`
  - `test_connection`：
    - `_ensure_token`
    - 调 `/cgi-bin/department/list?id={first_root}` 统计部门数 + 抽取 "企业名"（实际企微无此字段 → 使用 `main_department` 或 fallback `"企业微信"`）
    - 调 `/cgi-bin/user/simplelist?department_id={first_root}&fetch_child=1` 统计成员数
    - 返回 dict，显式移除任何 token 痕迹
  **测试**: T003 全部通过
  **覆盖 AC**: AC-39~AC-58
  **依赖**: T001, T002, T003

### 前端管理台（手动验证）

- [x] **T005**: Platform 前端 API 层 + Store
  **文件**:
  - `src/frontend/platform/src/controllers/API/orgSync.ts`
  - `src/frontend/platform/src/store/orgSyncStore.tsx`（**R1 改 `.tsx` 与项目风格一致**）
  - `src/frontend/platform/src/types/api/orgSync.ts`（新增，类型定义就地）
  **逻辑**:
  - API 层封装 F009 的 9 个端点（list / detail / create / update / delete / test / execute / logs / remote-tree）；类型定义对齐 `OrgSyncConfigRead` / `OrgSyncLogRead`。
  - Zustand store：state `configs` / `currentConfig` / `loading` / `editLoading` / `logs` / `error`；action `fetchConfigs / create / update / delete / testConnection / execute / fetchLogs`。
  **自测**: `npm run build` 无 TypeScript error；import 顺序与别名 `@/controllers/API/orgSync` 可用
  **依赖**: T004

- [x] **T006**: Platform 前端 Tab + Dialog + FieldSets（**R1/R3 修订：Tab 模式 + 手工 Badge 列表**）
  **文件**:
  - `src/frontend/platform/src/pages/SystemPage/index.tsx`（插入 `orgSync` Tab）
  - `src/frontend/platform/src/pages/SystemPage/components/OrgSync/index.tsx`
  - `src/frontend/platform/src/pages/SystemPage/components/OrgSync/ProviderDialog.tsx`
  - `src/frontend/platform/src/pages/SystemPage/components/OrgSync/fieldsets/WeComFieldSet.tsx`
  - `src/frontend/platform/src/pages/SystemPage/components/OrgSync/fieldsets/FeishuFieldSet.tsx`
  - `src/frontend/platform/src/pages/SystemPage/components/OrgSync/fieldsets/GenericApiFieldSet.tsx`
  - `src/frontend/platform/src/pages/SystemPage/components/OrgSync/TestConnectionButton.tsx`
  - `src/frontend/platform/src/pages/SystemPage/components/OrgSync/SyncLogModal.tsx`
  - `src/frontend/platform/src/pages/SystemPage/components/OrgSync/useOrgSync.ts`
  **逻辑**:
  - SystemPage Tab 仅对 `isFullAdminShell = isSuperAdmin || isDeptAdmin` 可见；Tab 标题从 `orgSync` namespace 取。
  - Dialog 用 `bs-ui/dialog`，Provider 下拉切换字段组。
  - WeCom 字段组（R3 修订）：corpid/agent_id 普通 Input；corpsecret 编辑态 `defaultValue="****"`，提交时若值仍是 `****` 则 drop；allow_dept_ids 手工实现 Input(type=number) + Button(add) + Badge 列表（每个带 ✕）；空数组入库用 `[1]`。
  - 列表页列：`config_name / provider / sync_status / last_sync_at / actions(测试|同步|编辑|日志|删除)`。
  - Toast：`useToast()` 的 `toast / message`；Confirm：`bsConfirm`。
  **覆盖 AC**: AC-35, AC-36, AC-37, AC-38, AC-39, AC-40, AC-41
  **自测策略（auto mode）**：
  - `npm run build` 无 TypeScript error
  - 表单切换逻辑、corpsecret `****` 占位、Badge 列表 add/remove 通过 code review 确认
  - E2E 场景覆盖由 T008 API 测试模拟
  **依赖**: T005

- [x] **T007**: i18n 三语独立 `orgSync` namespace（**R4 修订**）
  **文件**:
  - `src/frontend/platform/public/locales/en-US/orgSync.json`（新建）
  - `src/frontend/platform/public/locales/zh-Hans/orgSync.json`（新建）
  - `src/frontend/platform/public/locales/ja/orgSync.json`（新建）
  - `src/frontend/platform/src/i18n.js`（注册新 namespace）
  **逻辑**: `orgSync.json` 涵盖字段标签、校验提示、按钮文字、Toast、同步状态、删除确认；组件通过 `useTranslation('orgSync')` 访问。三语齐全，≥30 key。
  **自测**: 三语 key 集合必须完全一致；grep 组件代码无硬编码中文字符串
  **依赖**: T006

### E2E 与校验

- [x] **T008**: E2E 测试 — WeCom 全流程
  **文件**: `src/backend/test/e2e/test_e2e_org_sync_wecom.py`
  **逻辑**: 参考 `test/e2e/test_e2e_org_sync.py` 的 Feishu 用例结构。
  - 场景 1：admin 创建 WeCom 配置（mock 企微 API 返回 200/合法数据） → 列表返回 corpsecret=`****`
  - 场景 2：test_connection → 返回 connected=True
  - 场景 3：execute → 轮询 `org_sync_log` 直到 status=success → 检查 `user` 表新增记录 `source='wecom'`
  - 场景 4：modify → corpsecret 传 `****` → DB 中保持原值（解密 + 比对）
  - 场景 5：两个 tenant 各配一个 WeCom 配置 → 同步互不影响（验证 Redis key 隔离）
  - 场景 6：跑一次 partial 失败（mock 企微对 user/list 返回 45009 × 5） → `org_sync_log.status='partial'`，error_details 有记录
  **执行**: `.venv/bin/pytest test/e2e/test_e2e_org_sync_wecom.py -v -s`
  **覆盖 AC**: AC-35~AC-58 端到端
  **依赖**: T004, T006（前端不通过时跳过场景 1 的 UI 复核，仅跑 API 用例）

---

## 实际偏差记录

> 2026-04-20 开发完成后登记。spec § 0 已记录 R1~R5 修订，本节只列实施过程中与 spec / tasks.md 进一步出入的点。

- **偏差 1 — 抛弃 `fakeredis.aioredis`**：pyproject.toml 声明 `fakeredis[lua]>=2.21`，但 `pip install` 后 `import fakeredis` 触发 `TypeError: metaclass conflict`（redis-py 7.0.1 与 fakeredis 2.35 的元类冲突）。改为在 `test_wecom_provider.py` 内写 `_InMemoryAsyncRedis` 小型存根（覆盖 `get / set(nx/ex) / delete / ttl`），零外部依赖、29/29 用例全绿。后续如需共享 fixture 可提到 `conftest.py`。
- **偏差 2 — 前端 `TFunction` 签名太严**：i18next 在 TypeScript 严格模式下推导出的 `TFunction<'orgSync', undefined>` 无法匹配自定义 `(key, def?) => string`，tsc 报 TS2345。改为 fieldset 校验函数接受 `t: any`（局部 eslint-disable），避免污染调用侧。
- **偏差 3 — 前端 `message({variant})` 必须带 `description`**：`Toast` 类型强制要求 `description: string | string[]`。所有成功/失败提示补 `description`，不影响用户视觉。
- **偏差 4 — `update_config` 扩展**：spec §7.4 只要求 Service 层 inject/pop `_config_id`，实际发现 `sync_config.py` 的 `update_config` 端点合并 `auth_config` 时需额外处理 ① 客户端漏传的 `_config_id` ② secret 字段传 `****` 时应保留原值。新增 2 处防御性 pop / drop 逻辑；测试覆盖在 `test_e2e_org_sync_wecom.py::test_full_wecom_lifecycle`。
- **偏差 5 — 114 backend 需手动重启**：E2E 需要 114 uvicorn 加载新的 WeCom / schema / service 代码；`deploy.sh` 走 CI 自动部署流程，但未 push 的开发阶段需手工 `pkill + setsid uvicorn` 重启（已在本轮开发完成；请留意测试服的沙箱状态）。
- **偏差 6 — 企微测试账号未做 live E2E**：`E2E_WECOM_TEST_LIVE` 默认关闭。真实 corpid/corpsecret 的 AC-39 校验通过 tasks.md 记录的账号人工触发（`POST /api/v1/org-sync/configs/{id}/test`），或在 CI 里注入环境变量后启用 `TestWeComLiveConnection`。本次开发未执行 live 调用，避免污染外部企微工作台。

---

## 分支与 PR

- **Feature 分支**：`feat/v2.5.1/021-wecom-org-sync-provider`，基于 `2.5.0-PM`
- **合并目标**：`2.5.0-PM`
- **PR 触发**：全部 8 个任务完成 + `/e2e-test` 通过 + `/code-review --base 2.5.0-PM` 通过
