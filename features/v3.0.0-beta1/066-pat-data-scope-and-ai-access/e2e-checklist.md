# F066 E2E 验收清单

**分支**: `feat/3.0.0-beta1-066-pat-data-scope-and-ai-access`（基线 `8db764f2b`）
**状态**: API 侧自动化已在本地全绿(2026-09-13);真实环境(含中间件)全量执行**待部署**。

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
- [ ] alembic 升级后存量租户 `pat_data_scope='all_visible'`,PAT 行为与升级前一致(AC-P23)
- [ ] 管理端 PUT 收窄后 ≤5s:员工 PAT `POST /api/v2/filelib/retrieve` 打他人库 → HTTP 403 + 26044,响应无资源存在性信息;打自建库 → 正常(AC-P24)
- [ ] `GET /api/v2/filelib/?type=3` 与 `?type=0` 收窄后只回本人创建(部门绑定空间不在);`file/list` 对他人库 26044(AC-P24/P27)
- [ ] 本人空间内他人上传的文件可检索(AC-P25);`detail_qa`/`query_qa` 对他人 QA 库拒绝(AC-P27)
- [ ] 租户管理员与全局超管的 PAT 在收窄档下同样 26044,列表只见自建(AC-P26,含 get_knowledge/系统空间两收口)
- [ ] 改回 all_visible 后同一把密钥即时恢复,不需重签(AC-P24)
- [ ] 策略变更审计:audit_log 出现 `open_api.pat.settings.update` 含 before/after 三字段(AC-P28)
- [ ] 异步执行面(工作流内检索,若挂接)在收窄后同样受限(execution_context 重取)
- [ ] 技能包下载 zip:SKILL.md 中文触发词、references/api.md 已按实例渲染;search.py `--list-knowledge-bases` 可用,403 时透出 26044 响应体(AC-R4)

### 浏览器(手动)
- [ ] client 知识库页侧边栏「连接 AI 助手」入口(双闸显隐);设置页「AI 助手接入」一级分区;两处开同一弹窗(AC-P30)
- [ ] 空态两步指引;安装指令含技能包地址与 `settings/ai-access?connect=1` 深链;旧 `?api-token=1` 仍拉起(重定向)(AC-R7)
- [ ] 普通员工:生成→一次性红条+四态范围卡+风险红条+「一键复制,发给 AI 助手」;不勾保存关不掉(AC-P31)
- [ ] 管理员(默认档):顶部加重条含实际天数;生成先过勾选确认;收窄档降级为普通流程且范围卡显限定文案(AC-P26/P31)
- [ ] 租户关停:知识库页入口消失,设置分区保留关停解释;部署关停两处均不出现(AC-P30)
- [ ] 全界面无「个人 API 令牌/个人访问令牌」与裸 `knowledge:read`;管理员警示无「不会继承管理员特权」旧句(AC-P29)
- [ ] platform:「AI 助手接入」Tab,「使用策略」卡收紧确认弹窗与立即生效 toast;台账分页/吊销确认/「管理员持有」徽标(AC-P28)
- [ ] 端到端 AC-P21 复验:Claude Code 装包→配密钥→中文提问「帮我在知识库里查…」触发检索并回引用

### 已知环境注意
- mac 本地 platform `tsc-strict` 因 beta1 既有 `ApiRequestExamples.tsx`/`apiRequestExamples.ts` 大小写冲突报错(Linux CI 不受影响);worktree 内 client `tsc-strict` 的 `@bisheng/ui` 解析错误为环境性。两者均非 F066 引入。
