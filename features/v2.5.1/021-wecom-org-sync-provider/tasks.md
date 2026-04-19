# Tasks: 企业微信组织同步 Provider

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.1
**基线依赖**: [v2.5.0/F009-org-sync](../../v2.5.0/009-org-sync/)（必须已合并到 2.5.0-PM 并可运行）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已草 | 待 `/sdd-review spec` 评审 |
| tasks.md | ✅ 已草 | 待 `/sdd-review tasks` 评审 |
| 实现 | 🔲 未开始 | 0 / 8 完成 |

---

## 开发模式

- **后端 Test-First**：Provider 实现前先写单测（mock httpx），覆盖 AC-39~AC-58 的关键路径。
- **前端 Test-Alongside**：暂用手动验证 + E2E API 测试替代前端自动化。
- **真环境验证**：企微测试账号（corpid=`wwa04427c3f62b5769`, AgentId=`1000017`, Secret=`qVldC5Kp5houi1fG8yBvmZMaufN2KmFNkijdls1DdVc`）在 114 服务器网络环境下需验证可达；如需通过代理走企微 API，先在 `config.yaml` 补代理配置（本 Feature 不处理代理，只在实际偏差中记录）。

---

## Tasks

### 基础适配（无测试配对）

- [ ] **T001**: `auth_config` schema 校验 + 脱敏扩展
  **文件**: `src/backend/bisheng/org_sync/domain/schemas/org_sync_schema.py`
  **逻辑**:
  - 在 `OrgSyncConfigCreate` / `OrgSyncConfigUpdate` 的 `validate_auth_config` 校验器中，当 `provider='wecom'` 时必校验 `corpid` / `corpsecret` / `agent_id` 非空字符串；`allow_dept_ids` 如存在必须是 `list[int]`。
  - `mask_sensitive_fields()` 遇 `provider='wecom'` 时把 `corpsecret` 置为 `****`；保留 `corpid` / `agent_id` / `allow_dept_ids` 明文。
  - 为脱敏规则新增 `WECOM_SENSITIVE_FIELDS = ('corpsecret',)` 常量（与 Feishu 的 `FEISHU_SENSITIVE_FIELDS` 并列）。
  **覆盖 AC**: AC-36, AC-37, AC-38, AC-57, AC-58
  **依赖**: 无

- [ ] **T002**: `OrgSyncService` 注入 `_config_id` 到 auth_config
  **文件**: `src/backend/bisheng/org_sync/domain/services/org_sync_service.py`
  **逻辑**:
  - 在 `execute_sync` / `test_connection` / `preview_remote_tree` 调 `get_provider(provider, auth_config)` 之前，先 `auth_config['_config_id'] = config.id`（只在内存字典改，不回写 DB）。
  - 加上注释：`_config_id 仅供 Provider 内部使用（如 WeCom Redis key），不加密不持久化。`
  - 回写 DB 前（`update_config`）主动 `auth_config.pop('_config_id', None)`。
  **覆盖 AC**: AC-50, AC-51, AC-52（间接支撑 Redis key 隔离）
  **依赖**: T001

### WeComProvider 实现（Test-First 配对）

- [ ] **T003**: WeComProvider 单元测试
  **文件**: `src/backend/test/test_wecom_provider.py`
  **逻辑**: 使用 `respx` 或 `httpx.MockTransport` 桩住企微 API。
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

- [ ] **T004**: WeComProvider 实现
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

- [ ] **T005**: Platform 前端 API 层 + Store
  **文件**:
  - `src/frontend/platform/src/controllers/API/orgSync.ts`
  - `src/frontend/platform/src/store/orgSyncStore.ts`
  **逻辑**:
  - API 层封装 F009 的 9 个端点（list / detail / create / update / delete / test / execute / logs / remote-tree）；类型定义对齐 `OrgSyncConfigRead`。
  - Zustand store：`configs` / `currentConfig` / `loading` / `logs`；action `fetchConfigs` / `testConnection` / `execute`。
  **测试**: 无自动化；由 T006/T007 手动验证覆盖。
  **依赖**: T004

- [ ] **T006**: Platform 前端表单页面
  **文件**:
  - `src/frontend/platform/src/pages/SystemPage/OrgSyncPage/index.tsx`
  - `src/frontend/platform/src/pages/SystemPage/OrgSyncPage/ConfigFormModal.tsx`
  - `src/frontend/platform/src/pages/SystemPage/OrgSyncPage/components/WeComFieldSet.tsx`
  - `src/frontend/platform/src/pages/SystemPage/OrgSyncPage/components/FeishuFieldSet.tsx`
  - `src/frontend/platform/src/pages/SystemPage/OrgSyncPage/components/GenericApiFieldSet.tsx`
  - `src/frontend/platform/src/pages/SystemPage/OrgSyncPage/TestConnectionButton.tsx`
  - `src/frontend/platform/src/pages/SystemPage/OrgSyncPage/SyncHistoryTable.tsx`
  - `src/frontend/platform/src/pages/SystemPage/OrgSyncPage/hooks/useOrgSyncConfig.ts`
  - `src/frontend/platform/src/components/bs-comp/menus/index.tsx`（或现有菜单入口，添加"组织同步"项）
  **逻辑**:
  - 表单使用 Radix Form（bs-ui），Provider 下拉切换字段组。
  - WeCom 字段组：corpid（input）、corpsecret（input type=password，编辑态显示 `****` 占位，用户清空再输或留空提交 → 表单提交时若值是 `****` 则不带该字段）、agent_id（input）、allow_dept_ids（`bs-ui` Tags 输入，回车成项，校验整数）。
  - 列表页：按 F009 `OrgSyncConfigRead` 渲染，列 `config_name / provider / sync_status / last_sync_at / actions`。
  - Toast：`toast({ title, variant: 'success'|'error' })`（见规则文件 `.claude/rules/platform-frontend.md`）。
  - Confirm：`bsConfirm`（删除、重置）。
  **覆盖 AC**: AC-35, AC-36, AC-37, AC-38, AC-39, AC-40, AC-41
  **手动验证清单**:
  1. 访问 http://192.168.106.114:3001/system/org-sync → 能看到列表页（空态）
  2. 点击"新建"，Provider 选"企业微信" → 显示 4 个字段；缺 corpid 提交 → toast 报错 22006
  3. 填入测试配置（corpid=`wwa04427c3f62b5769` / AgentId=`1000017` / Secret=`qVldC5Kp5houi1fG8yBvmZMaufN2KmFNkijdls1DdVc`），保存 → 列表出现新条目
  4. 点击"测试连接" → toast 显示 total_depts 与 total_members；浏览器 Network 面板检查响应体无 token
  5. 编辑该配置 → corpsecret 字段显示 `****`；不改直接保存不覆盖原值；改写 → 保存生效
  6. 点击"立即同步" → 弹出确认 → 同步开始；查看"同步历史"显示 running → success
  7. 同步后到"系统管理 → 成员" 查看是否新增企微成员（source=wecom 标签）
  8. 切 Provider 下拉到飞书，字段组切换；GenericAPI 同上
  9. 三语切换：en-US / zh-Hans / ja，字段标签、Toast、按钮文案全部无原文泄露
  **依赖**: T005

- [ ] **T007**: i18n 文案 + 菜单登记
  **文件**:
  - `src/frontend/platform/public/locales/en-US/bs.json`
  - `src/frontend/platform/public/locales/zh-Hans/bs.json`
  - `src/frontend/platform/public/locales/ja/bs.json`
  **逻辑**: 新增 namespace key `orgSync.*`（字段标签、校验提示、Toast、菜单项标题、同步状态中英日）。至少 30 个 key 对齐三语。
  **手动验证**: `/i18n-localizer` skill 检查无硬编码中文残留；三语切换无 key fallback
  **依赖**: T006

### E2E 与校验

- [ ] **T008**: E2E 测试 — WeCom 全流程
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

> 完成后，在此记录实现与 spec.md 的偏差，供后续参考。

- **偏差 1**: _（待填）_

---

## 分支与 PR

- **Feature 分支**：`feat/v2.5.1/021-wecom-org-sync-provider`，基于 `2.5.0-PM`
- **合并目标**：`2.5.0-PM`
- **PR 触发**：全部 8 个任务完成 + `/e2e-test` 通过 + `/code-review --base 2.5.0-PM` 通过
