# 验收测试用例：平台管理员（运营岗）

输入：已确认需求（11 项管理端权限、非超管、入口+接口 403）+ `design.md`。  
状态：**实现前矩阵，尚未执行，不得勾「已通过」。**  
规格仅在毕昇 worktree 本地 `specs/056-platform-operator-role/`（`features/` 若 ignore 则不进远程）。

## 夹具约定

| 代号 | 身份 | 做法 |
|---|---|---|
| U-anon | 未登录 | 无 Cookie |
| U-user | 普通用户 | 仅 `DefaultRole`（普通用户），无「平台管理员」、非 `AdminRole` |
| U-ops | 平台管理员 | `role.role_name` 精确为 `平台管理员`；**无** `AdminRole`；`is_admin()` 必须为 false |
| U-portal | 门户整页「管理员」 | `role_name=管理员`，非超管 |
| U-super | 真超管 | `AdminRole=1` 或 `is_global_super` |

U-ops 同时保留普通用户角色，以便前台可登录。验收库：毕昇 `config.yaml` **171 MySQL**。门户 BFF 写配置最终落毕昇 `config`（`key=shougang_portal_config`）。

失败期望一律：**拒绝（401/403 或业务码）且目标表无脏行；响应不回无权正文（配置全文、密钥、他人流水）。**

---

## 需求追踪

| 方案 AC | 覆盖用例 |
|---|---|
| 角色名「平台管理员」，租户内不重复 | AT-01, AT-02, AT-03 |
| 保留名不可改名/删除 | AT-04 |
| 不是超管 | AT-10, AT-11, AT-32 |
| 能进 11 项且写穿 | AT-20～AT-30 |
| 不能进禁止模块 | AT-40～AT-48 |
| 入口隐藏 + 接口 403 | AT-50～AT-54 |
| 三 iframe 能开；approval/sys 进不去 | AT-60～AT-63 |
| 积分/迁移认运营身份而非 `is_admin()` | AT-21, AT-22, AT-10 |
| 超管不变 | AT-70, AT-71 |
| 解绑后失效 | AT-80 |

无通知/待办面。无 DDL。DM8：本需求无新 SQL 方言，P2 回归即可。

---

## 跨模块影响（测试必须覆盖的波及，不单测改过的文件）

| 改动点 | 受影响 | 风险 | 测什么 |
|---|---|---|---|
| `/user/info` 的 `role` 标签 | 门户会话、`isPortalAdmin` | 自定义角色下发成 `"[id]"` 则整页进不去；误并入 `ADMIN_ROLES` 则全开 | AT-12, AT-50, AT-40 |
| `require_platform_admin` 扩资格 | 积分管理 + **专家问答违规删除若误扩** | 垂直越权 | AT-21, AT-48 |
| `require_system_admin` 扩资格 | 迁移全库 | 现网单测会拒绝展示角色名，实现后必须改测 | AT-22, AT-23 |
| `get_admin_user` **不**扩 | `PUT /shougang-portal/config` | 用户 Cookie 直打可改首页 | AT-11 |
| BFF `admin_config` 拆 ACL | 问答可写 vs 导航/数据源不可写 | 漏 path 则改禁止配置或泄露密钥 | AT-24, AT-40, AT-45 |
| `userContext` standalone | 三 iframe vs 审批/系统壳 | 只改路由不够 | AT-60, AT-62 |
| 角色 WEB_MENU 剥离 | Platform 侧栏 | 误勾 `board`/`sys` 从后台直进 | AT-32 |

---

## 用例矩阵

| ID | P | 层级 | 身份 | 追溯 | 步骤 / 输入 | 期望 HTTP | 期望落库 / 副作用 | 再打一枪 | 现状 |
|---|---|---|---|---|---|---|---|---|---|
| AT-01 | P0 | 接口+落库 | U-super | 创建保留名 | 创建 `role_name=平台管理员` | 200，返回该名 | `role` 一行，`role_name` 精确四字 | 再创建同名（任意 department）→ 24002，行数仍 1 | 缺口；`test_role_service.py` 仅有同 scope 重名 |
| AT-02 | P0 | 接口+落库 | U-super | 与「管理员」不冲突 | 已有 `管理员`，再创建 `平台管理员` | 200 | 两行并存 | `GET` 角色列表两名都在 | 缺口 |
| AT-03 | P0 | 单元 | — | 精确匹配 | `has_platform_operator_role`：`平台管理员` true；`管理员` / `系统管理员` / `xx平台管理员` / 空格变体 trim 后全等才 true | — | 不写库 | substring 不得 true | 缺口（新 helper） |
| AT-04 | P1 | 接口+落库 | U-super | 保留名保护 | 对 AT-01 角色改名或删除 | 24004（或方案等价码） | `role_name` 仍为 `平台管理员` | 绑定用户后资格仍在 | 缺口 |
| AT-10 | P0 | 接口 | U-ops | 不是超管 | `GET /api/v1/user/info` | 200，`role=平台管理员`，`role_names` 含该名；**无** `role=admin` | 不写 `userrole.role_id=1` | 服务端 `is_admin()` false（测依赖或受保护接口） | 缺口；现网自定义角色 `role` 为 id 列表 |
| AT-11 | P0 | 接口 | U-ops | 不扩 `get_admin_user` | 用户 Cookie `PUT /api/v1/shougang-portal/config` 改 `domains` | 403，无配置正文 | `config.value` 与调用前一致 | 再 GET internal/超管读，导航未变 | 缺口；现 `test_portal_config` 有超管依赖可对照 |
| AT-12 | P0 | 接口 | U-ops | 门户吃得到身份 | 门户登录后会话 `user.role` 或 `role_names` | 门户 `/api/v1/auth/me`（或现网会话接口）含运营岗 | 门户无角色表 | 刷新会话仍为运营岗 | 缺口；BFF 现只抄 `role` 字符串 |
| AT-20 | P0 | UI | U-ops | 11 项入口 | 打开 `/admin` | 200 页 | 侧栏仅 11 项中的 1–10；有迁移入口（第 11 项） | 禁止项菜单节点不存在 | 缺口；现 `NAV_GROUPS` 全渲染。`adminAccess.test.ts` 需扩展且 **不得** 把该名并入 `isPortalAdmin` |
| AT-21 | P0 | 接口+落库 | U-ops | 2 积分管理 | `POST /api/v1/points/admin/adjust` 合法调账 | 200 | `user_point_log` 新增对应 `delta`；账户余额一致 | 再 GET `/admin/users/{id}/detail` 与表一致；普通用户打同一接口 18201 且 log 行数不变 | 缺口；现闸门只认超管。`test_department_org_level.py` 需改夹具 |
| AT-22 | P0 | 接口+落库 | U-ops | 11 迁移全库 | `GET /knowledge/migrations/spaces` 能列出非本人库；`POST /batches` 建批 | 200 | `knowledge_migration_batch` 一行，操作者为 U-ops | 再 GET 该 `batch_no` 仍在；U-user 建批 403 且表无新行 | 缺口；`test_knowledge_migration_auth.py` **现拒绝展示角色**，实现后改为运营岗通过、账号名旁路仍拒 |
| AT-23 | P0 | 接口 | U-ops | 迁移全库列表 | spaces 含无个人权限的库（与超管同一列表口径） | 200，可选库不按个人 ReBAC 收窄 | 不写 | U-user 403 | 缺口 |
| AT-24 | P0 | 接口+落库 | U-ops | 3 问答配置 | 门户 `POST /api/v1/admin/config/qa` 改欢迎语 | 200 | 毕昇 `config` JSON 内 `qa` 已更新；`domains` 未变 | 再 GET `/qa` 与库一致；U-user 403 且 `qa` 回滚/未变 | 缺口；扩 `test_admin_config_api.py` |
| AT-25 | P0 | 接口+落库 | U-ops | 4 写作模板 | `POST /qa` 改 `templates`（与问答同一文档） | 200 | `config` 模板数组变更 | 再读一致；禁止 path 仍 403 | 可与 AT-24 同文件两条 |
| AT-26 | P0 | 接口+落库 | U-ops | 5 应用配置 | `POST /admin/config/agent-config` | 200 | `config` 内 agent 变更 | 再 GET 一致 | 缺口 |
| AT-27 | P0 | 接口+落库 | U-ops | 6 知识分类 | `POST /admin/config/document-types` | 200 | `config` 内 document_types 变更 | 再 GET 一致 | 缺口 |
| AT-28 | P0 | 接口+落库 | U-ops | 7 水印 | `POST /admin/config/watermark` | 200 | `config` 内 watermark 变更 | 再 GET 一致 | 缺口 |
| AT-29 | P0 | 接口+落库 | U-ops | 8 字典 | 毕昇 `POST /api/v1/dictoption/create` | 200 | `system_dictionary` 新行 | 再 GET by type 见该行；U-user 19102 且无新行 | 缺口；`test_dictionary_router.py` 扩管理员夹具 |
| AT-30 | P1 | 接口 | U-ops | 1/9/10 iframe API | 看板列表（等同超管可见范围）；敏感词 GET/PUT；tag-console 管理接口各一成功 | 200 | 看板/策略/标签按现超管语义落库或可读 | U-user 未授权 | 缺口。PUT 敏感词须查 `sensitive_word_policy` |
| AT-40 | P0 | 接口+落库 | U-ops | 禁止：首页导航 | `POST /admin/config/domains` | 403，无 domains 正文 | `config` 内 domains 不变 | 再 POST 一次仍不变 | 缺口 |
| AT-41 | P0 | 接口+落库 | U-ops | 禁止：推荐/搜索/轮播/展示 | `POST` recommendation、search、banners、display 各一 | 403 | 对应 JSON 块不变 | 再读 | 缺口（可 parametrize） |
| AT-42 | P0 | 接口+落库 | U-ops | 禁止：课程 | 现网课程写接口 | 403 | 课程表行数不变 | 再写仍拒 | 缺口 |
| AT-43 | P0 | 接口 | U-ops | 禁止：自动发布/科室绑定/业务域 | 对应 POST/DELETE | 403 | 绑定表/规则不变 | 再打 | 缺口 |
| AT-44 | P0 | 接口 | U-ops | 禁止：回收站 | `/api/v1/...` 回收站写 | 403 | 回收记录不变 | — | 缺口 |
| AT-45 | P0 | 接口 | U-ops | 禁止：数据源密钥 | `GET /admin/config/bisheng`、`GET /rest-auth`、`GET /admin/config` 全量 | 403，body 无密码/token | 不写 | 超管 GET 仍有配置（脱敏规则同现网） | 缺口 **P0 防泄露** |
| AT-46 | P0 | 接口 | U-ops | 禁止：站点/集成/统一认证 | 对应 GET/POST | 403 | 配置不变 | — | 缺口 |
| AT-47 | P0 | 接口 | U-ops | 禁止：审批/系统 standalone 后端 | 审批、系统配置现网超管 API | 403 | 不写 | 不扩 `can_platform_operate` 到这些模块 | 缺口 |
| AT-48 | P0 | 接口+UI | U-ops | 禁止：专家问答违规删除 | 调现网超管扣分/删问接口；UI 无违规删按钮 | 403 或 18201（保持超管码） | 问答/积分表无违规删产生的行 | `is_platform_super_admin` 仍不含运营岗 | 缺口。现 `adminAccess.test.ts` 超管判定不得把 U-ops 算进去 |
| AT-50 | P0 | 单元/UI | U-ops | `isPortalAdmin` 不含该名 | `isPortalAdmin({role:'平台管理员'})===false`；`canEnterAdminShell===true` | — | — | 「管理员」仍 true | 缺口；改 `adminAccess.test.ts` |
| AT-51 | P0 | UI | U-ops | 直链禁止 section | `/admin?section=site`（或 domains） | 无权限模块页 | 不请求禁止 API（或请求被 403） | 侧栏仍无该项 | 缺口 |
| AT-52 | P0 | UI | U-ops | Header | 有「知识管理后台」「迁移记录」；无回收站；无毕昇管理后台外链 | — | — | U-user 无后台/迁移 | 缺口；改 Header 源码断言 + `knowledgeMigrationAccess.test.ts` |
| AT-53 | P0 | UI | U-user | 整页仍拒 | `/admin`、`/knowledge-migrations` | 无权限 | 不写 | 登录用户前台仍可用 | 现网已有，保持 |
| AT-54 | P0 | UI | U-anon | 未登录 | `/admin` | 去登录 | 不写 | — | 现网已有 |
| AT-60 | P0 | UI+接口 | U-ops | iframe 三页能开 | 打开三条 `/platform/standalone/{dashboard,knowledge-tag-library,content-security}` | 页能渲染；内接口 200 | 见 AT-30 | 无管理端 WEB_MENU 时也不得踢到 workspace | 缺口；Platform `userContext` |
| AT-62 | P0 | UI | U-ops | approval/sys 进不去 | 打开 `/platform/standalone/approval`、`/sys`、有壳 `/dashboard` | 403 或踢走 workspace | 不加载审批/系统页 | 后端仍 403 | 缺口 |
| AT-63 | P1 | UI | U-ops | 不从毕昇侧栏进 | 登录 Platform 非 standalone | 踢走 workspace / 无管理侧栏 | `roleaccess` 无 board/sys | 有 shell 的 `/dashboard` 进不去 | 缺口 |
| AT-70 | P0 | 接口+落库 | U-super | 超管积分/迁移/配置仍开 | 调账、建迁移、POST domains、GET bisheng | 200 | 与现网一致落库 | 再读一致 | 现网覆盖，回归勿破 |
| AT-71 | P0 | UI | U-super / U-portal | 整页管理员菜单全开 | `/admin` 全部 NAV_GROUPS | 开 | — | 回收站、外链仍开（U-portal 按现网） | 现网；加回归断言「未误删整页资格」 |
| AT-80 | P0 | 接口+落库 | U-ops→解绑 | 解绑失效 | 超管从 `userrole` 去掉该角色后，原用户调积分 adjust、POST /qa | 18201 / 403 | 无新 log、`config.qa` 不变 | `/user/info.role` 不再是平台管理员 | 缺口 |
| AT-81 | P1 | 接口 | U-ops+U-super 同一人 | 超管优先 | 同时绑 AdminRole 与平台管理员 | `/user/info.role=admin` | 禁止模块也可写（超管） | `is_admin()` true | 缺口 |
| AT-90 | P2 | 单元 | — | WEB_MENU 剥离 | 保存该角色菜单含 `board`,`sys` | 200，返回菜单无管理端 key | `roleaccess` 无这些 third_id | 再读 WEB_MENU | 缺口 |
| AT-91 | P2 | 单元 | — | 不把该名加入 ADMIN_ROLES | 源码/单测：`ADMIN_ROLES` 仍三元；BFF `is_portal_admin_role('平台管理员')` false | — | — | — | 缺口 |

---

## 11 项与用例对照（防漏模块）

| # | 模块 | 成功用例 | 失败对照 |
|---|---|---|---|
| 1 | 数据看板 | AT-30, AT-60 | AT-62 有壳后台 |
| 2 | 积分管理 | AT-21 | AT-48 专家问答违规删；U-user 18201 |
| 3 | 问答配置 | AT-24 | AT-40 导航 |
| 4 | 写作模板 | AT-25 | 同左 |
| 5 | 应用配置 | AT-26 | AT-41 |
| 6 | 知识分类 | AT-27 | AT-41 |
| 7 | 水印设置 | AT-28 | AT-45 数据源 |
| 8 | 字典配置 | AT-29 | U-user 19102 |
| 9 | 内容与安全审查 | AT-30, AT-60 | AT-62 |
| 10 | 标签管理 | AT-30, AT-60 | AT-62 |
| 11 | 迁移记录/新建迁移 | AT-22, AT-23, AT-52 | U-user 403；解绑 AT-80 |

---

## 建议测试文件（实现阶段再写，本步不落测试代码）

**毕昇（新文件，勿追加巨石）：**

- `test/user/test_platform_operator_identity.py` — AT-03, AT-10, AT-11, AT-81
- `test/role/test_platform_operator_reserved_name.py` — AT-01, AT-02, AT-04, AT-90
- `test/points/test_platform_operator_points_admin.py` — AT-21, AT-80（调账+查表）
- `test/knowledge/test_platform_operator_migration.py` — AT-22, AT-23；并改 `test_knowledge_migration_auth.py`
- `test/dictionary/test_platform_operator_dictionary.py` — AT-29
- `test/workstation/test_platform_operator_tag_and_sensitive.py` — AT-30 中标签/敏感词
- Platform：`src/frontend/platform/src/test/` standalone 白名单 — AT-60, AT-62

**门户：**

- 扩 `frontend/tests/adminAccess.test.ts`、`knowledgeMigrationAccess.test.ts` — AT-50, AT-52
- 扩 `backend/tests/test_admin_config_api.py`（及 qa/agent 分测）— AT-24～AT-28, AT-40～AT-46
- 课程/回收站拒绝 — AT-42, AT-44

**UI 手测（无稳定 iframe E2E 时书面降级，不把未跑的勾完成）：** AT-20, AT-51, AT-60, AT-62, AT-63, AT-71。

---

## 明确不测（非目标）

- 种子插入「平台管理员」角色行。
- 按库收窄迁移。
- 公开发现开关、用户角色管理、OpenFGA 新 relation。
- 性能压测（现 `perf_admin_write.py` 不改口径）。

下一步：用例确认后拆 `tasks.md`，再写代码。P0 写库条必须 171 MySQL 流转，mock 仓储不算过门。
