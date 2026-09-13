# F066 E2E 验收清单

**分支**: `feat/3.0.0-beta1-066-pat-data-scope-and-ai-access`（基线 `8db764f2b`）
**状态**: 已在 105(DM8,`feat/cofco-909-3.0.0-beta1` 部署)全量执行完毕(2026-09-13)。API 9 项与浏览器主流程全部通过;逐项状态见下。执行中抓获并修复超管短路旁路一处(`business_authorization.py`,详见 design.md 修订)。

## 一、已通过的自动化(本地,SQLite + FakeRedis + 桩 FGA)

| 套件 | 结果 | 覆盖 |
|---|---|---|
| `test/permission/test_data_scope_enforcement.py` | 8 passed | 判定先于超管短路/批量静默收窄/清单交集/未注册协议拒绝/默认档零变化(AC-P23/P24/P26) |
| `test/open_api/test_data_scope_resolver.py` | 4 passed | 口径 A 三类资源 + 部门空间剪除 + 他人内容按父放行 + 请求内 memo(AC-P25) |
| `test/open_api/test_data_scope_matrix.py` | 4 passed | 注册表分类断言(AC-R3)+ 闸口→权限层→传输接线:默认不变/收窄次请求生效且可逆/管理员同收窄/403+26044 防枚举(AC-P24/P26/R2) |
| `test/open_api/test_pat_tenant_setting.py` | 6 passed | 缺键=all_visible 混版兼容(AC-R1)/未知值 fail-closed/preserve 语义/变更审计(AC-R6/P28) |
| `test/open_api/test_data_scope_static_guard.py` | 3 passed | v2 链路 is_global_super 消费钉死(AC-R3 静态防线) |
| `test/open_api/test_skill_pack.py` | 4 passed | zip 含渲染后 api.md/中文触发词/先清单流程/错误体透出(AC-R4) |
| open_api 全量 + knowledge 差集 | 与基线差集为零 | 回归 |
| platform vitest 9 passed / client jest 18 passed | 全绿 | 收紧确认流/PUT 载荷/吊销确认;管理员确认门控/收窄降级/一键复制(AC-P28/P29/P31/R7 自动化半边) |
| `pnpm check-i18n` | OK | 三语齐平(AC-R5) |

## 二、真实环境执行项(部署后逐项打勾)

### API(可脚本化)
- [x] alembic 升级后存量租户 `pat_data_scope='all_visible'`,PAT 行为与升级前一致(AC-P23)
- [x] 管理端 PUT 收窄后 ≤5s:员工 PAT `POST /api/v2/filelib/retrieve` 打他人库 → HTTP 403 + 26044,响应无资源存在性信息;打自建库 → 正常(AC-P24)
- [x] `GET /api/v2/filelib/?type=3` 与 `?type=0` 收窄后只回本人创建(部门绑定空间不在);`file/list` 对他人库 26044(AC-P24/P27)
- [x] 本人空间内他人上传的文件可检索(AC-P25);`detail_qa`/`query_qa` 对他人 QA 库拒绝(AC-P27)
- [x] 租户管理员与全局超管的 PAT 在收窄档下同样 26044,列表只见自建(AC-P26,含 get_knowledge/系统空间两收口)
- [x] 改回 all_visible 后同一把密钥即时恢复,不需重签(AC-P24)
- [x] 策略变更审计:audit_log 出现 `open_api.pat.settings.update` 含 before/after 三字段(AC-P28)
- [~] 异步执行面(工作流内检索,若挂接)在收窄后同样受限(execution_context 重取)——真实环境未挂接工作流场景,由单测保障(`test_data_scope_matrix.py` 重取用例)
- [x] 技能包下载 zip:SKILL.md 中文触发词、references/api.md 已按实例渲染;search.py `--list-knowledge-bases` 可用,403 时透出 26044 响应体(AC-R4)

### 浏览器(手动)
- [x] client 知识库页侧边栏「连接 AI 助手」入口(双闸显隐);设置页「AI 助手接入」一级分区;两处开同一弹窗(AC-P30)
- [x] 空态两步指引;安装指令含技能包地址与 `settings/ai-access?connect=1` 深链;旧 `?api-token=1` 重定向到 `settings/ai-access` 并自动拉起弹窗;`?connect=1` 消费后从 URL 清除(AC-R7)
- [x] 普通员工:生成→一次性红条+四态范围卡+风险红条+「一键复制,发给 AI 助手」;不勾保存关不掉(AC-P31)
- [x] 管理员(默认档):顶部加重条含实际天数(7 天,过期时间实测 +7d);生成先过「你正在以管理员身份生成密钥」勾选确认(未勾「确认生成」置灰)。收窄档降级半边未在真实环境走查,由 client jest 覆盖(AC-P26/P31)
- [ ] 租户关停:知识库页入口消失,设置分区保留关停解释;部署关停两处均不出现(AC-P30)——未实测(105 租户 1 生产性开启,关停走查影响其他使用者;显隐双闸逻辑由 client jest 覆盖)
- [x] 全界面无「个人 API 令牌/个人访问令牌」与裸 `knowledge:read`;管理员警示无「不会继承管理员特权」旧句(AC-P29)
- [x] platform:「AI 助手接入」Tab,「使用策略」卡收紧确认弹窗与立即生效 toast;台账分页/吊销确认/「管理员持有」徽标(AC-P28)
- [~] 端到端 AC-P21 复验:真 Agent(Claude Code)闭环未跑;等价链路已覆盖——技能包 zip 内 search.py 以员工 PAT 实测检索/清单/26044 透出(API S1-S4),「最后使用」时间在管理台账实证更新

### 已知环境注意
- mac 本地 platform `tsc-strict` 因 beta1 既有 `ApiRequestExamples.tsx`/`apiRequestExamples.ts` 大小写冲突报错(Linux CI 不受影响);worktree 内 client `tsc-strict` 的 `@bisheng/ui` 解析错误为环境性。两者均非 F066 引入。

## 三、真实环境执行记录(2026-09-13,105/DM8)

- 执行身份:测试夹具 `f066e2e_emp`(150057)/`f066e2e_adm`(150058,AdminRole);测试库 kb=182、空间 184/185。执行后两把测试密钥已在管理台账吊销(吊销确认弹窗即本次实测),策略已回 `all_visible`,审计留有完整 before/after 链。
- 途中抓获真缺陷一处:`permission/application/business_authorization.py` 两处 `if actor.super_admin: return True` 在 data_scope 判定之前放行(第四旁路,单+批)。已修为 `actor.super_admin and actor.data_scope == DATA_SCOPE_ALL`,补回归两例与静态守卫第三断言;修复已推 `feat/cofco-909-3.0.0-beta1` 并重新部署后复验通过。
- UI 保存链路实证:platform 收紧→红色确认弹窗→toast「已保存。设置对所有已发放的密钥立即生效。」→DB `pat_data_scope='personal_only'`→审计 `open_api.pat.settings.update`(operator=150058,before/after 齐);放宽方向直接保存不弹确认,可逆。
- 环境注意(非 F066):密码登录自 `94323e3ec` 起只查 `user.external_id`,裸 ORM 造的夹具用户必须补 `external_id=user_name` 才能登录;`f066e2e_adm` 首次登录跳 `/admin` 曾回落登录页一次,重试即成,未再复现。
