# Tasks: 个人技能上传与技能中心

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)
**版本**: v3.0.0-beta3

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-10-19 审查后确认不改 |
| design.md | ✅ 已评审 | 2026-10-19 审查后确认不改 |
| tasks.md | ✅ 已拆解 | 2026-10-19 按 tasks-checklist 拆解；47 项 |
| 实现 | ✅ 完成 | 47 / 47 完成。偏差处理见 design.md 顶部调整原则 + `docs/SDD-Guide.md` §3-§4 |

---

## 开发模式

- 按 Wave 组织。同一 Wave 内无相互依赖的任务可并行。
- 后端 Test-First：测试任务在配对实现之前。测试放 `src/backend/test/linsight/`（已有目录），`asyncio_mode=auto`。不新建根级 `test/` 文件。
- 设计论证指向 design 的决策或章节，这里不复述理由。
- 本 Feature 无 Platform 页面。管理端技能页不改；个人技能不得出现在管理列表里，由 T007、T013、T025 保证。
- 前端只改 `src/frontend/client/`。页面结构沿用已合入的技能中心，数据源从浏览器换成服务端（design 决策 6）。
- 新的用户可见句子进 client 三语 `src/frontend/client/src/locales/{zh-Hans,en,ja}/translation.json`，复用已有 `com_skill_center_*`。错误码文案只改 `src/frontend/packages/locales` 的 `api_errors`，不手改生成物。
- 不新增 YAML 顶层键。配额 20 个、200 MiB（209715200 字节）写在服务代码里。
- 多 agent 并行时禁止仓库级 git 写操作（根 `AGENTS.md` §7）。

---

## Tasks

### Wave 1 — 基础设施（无测试配对，互不依赖）

- [x] **T001**: `linsight_skill` 归属列与迁移
  **文件**: `src/backend/bisheng/linsight/domain/models/linsight_skill.py`，`src/backend/bisheng/core/database/alembic/versions/v3_0_0b3_f076_linsight_skill_owner.py`
  **逻辑**: 增加非空 `owner_user_id`（默认 0）和可空 `last_import_id`。唯一约束从 `uq_linsight_skill_tenant_name (tenant_id, name)` 改为 `(tenant_id, owner_user_id, name)`。另加 `(tenant_id, owner_user_id, last_import_id)`：MySQL 与 DM8 上两行空的 `last_import_id` 都要能插入（design §7.4）。升级前若同租户同名已有重复行则中止，不填业务数据；存量行 `owner_user_id` 填 0。降级删两个新约束、恢复旧约束、删这两列。不搬对象。本任务只改模型和迁移，不改 DAO 方法（T007）。租户技能管理的请求和响应不加字段（design §6，release-contract 里这张表的个人技能归属 F076，存量行仍是租户技能）。
  **测试**: MySQL 与 DM8 各执行一次 upgrade / downgrade；两行空 `last_import_id` 同时成功。DM8 若把空值当成相等，停下，不要自行换成另一种唯一约束。
  **依赖**: 无

- [x] **T002**: 会话版本技能快照列
  **文件**: `src/backend/bisheng/linsight/domain/models/linsight_session_version.py`，`src/backend/bisheng/core/database/alembic/versions/v3_0_0b3_f076_session_skill_snapshot.py`
  **逻辑**: 增加可空 JSON 列 `skill_snapshot`。每一项是 `{name, skill_id, owner_user_id, content_hash}`，表示这个会话目录属于哪一行（design §7.8）。不回填。原 `skills` 列仍只存勾选的技能名，本任务不改它的含义。对外的 dump 不输出这一列。降级删列。
  **测试**: MySQL 与 DM8 各执行一次 upgrade / downgrade
  **依赖**: 无

- [x] **T003**: 个人技能错误码类
  **文件**: `src/backend/bisheng/common/errcode/linsight.py`
  **逻辑**: 新增 11061 个数超出、11062 容量超出、11063 压缩包已加密、11064 版本过期、11065 类型与内容不一致、11066 同一次导入的文件不一致、11067 压缩包损坏、11068 缺少 `SKILL.md`、11069 路径越界、11071 文件为 0 字节、11072 压缩包内含多份技能、11073 `SKILL.md` 超过 1 MiB、11074 条目超过 1000。11052、11059 增加 `limit_mb`，经基类 kwargs 进入响应 `data`。不改 11051、11053、11054、11055 的码，不改 11060、11070 的类和文案。用户能看到的句子只写在 T004，不在 `status_message` 再写一句中文（design §6）。
  **依赖**: 无

- [x] **T004**: 错误码三语文案
  **文件**: `src/frontend/packages/locales/src/api_errors/zh-Hans.json`，`src/frontend/packages/locales/src/api_errors/en.json`，`src/frontend/packages/locales/src/api_errors/ja.json`
  **逻辑**: 为 T003 的新码补齐三语。11052 改为「技能文件超过 {{limit_mb}} MiB，请精简后重新上传」，11059 改为「技能包解压后超过 {{limit_mb}} MiB，请精简后重试」。11068 的中文是「压缩包中缺少 SKILL.md，请检查后重新上传。」11064 的中文是「该 Skill 已更新，请刷新后重试」。11063 说明压缩包已加密、请解除密码后重新选择。跑既有生成脚本，不手改 `platform/public/locales/*/api_errors.json` 和 `client/src/locales/*/api_errors.gen.json`。`pnpm check-i18n` 通过。与 T011 同一 PR 提交，避免页面留下未替换的 `{{limit_mb}}`。
  **依赖**: 无

- [x] **T005**: 把 `linsight_skill` 补进 edit / delete 的资源范围
  **文件**: `src/backend/bisheng/permission/domain/services/catalog_policy.py`
  **逻辑**: `edit` 的资源范围加入 `linsight_skill`。`delete` 目前等于 `MIGRATED_RESOURCE_TYPES`，而 catalog 校验拒绝该集合以外的类型，所以把 `linsight_skill` 加入 `MIGRATED_RESOURCE_TYPES`，`delete` 和 `manage_permission` 会一并带上它。不新建资源类型，不加授权页面。本期仍不按人把个人技能授给别人；单条操作的归属核对在 T023。企业技能的使用继续不读这条所有者记录（design 决策 5、§5）。跑 `src/backend/test/permission/` 里按该集合参数化的用例；失败时只补这个类型在 catalog 上的最小登记，不把知识库的授权流程抄过来。
  **依赖**: 无

### Wave 2 — 归属查询与对象存储（依赖 Wave 1）

- [x] **T006**: DAO 归属条件测试
  **文件**: `src/backend/test/linsight/test_skill_owner_dao.py`
  **逻辑**: 同一租户造三行同名技能：企业 `owner_user_id=0`、用户 A、用户 B。`get_by_name`、`set_enabled`、`set_default_checked`、`delete_by_name`、`list_enabled`、`get_page` 只命中调用方指定的归属。不带 `tenant_id` 和 `owner_user_id` 的批量更新不得改到别的行。子租户查询看不到根租户的行。默认管理查询只看到 `owner_user_id=0`。
  **覆盖 AC**: AC-05, AC-10, AC-12
  **依赖**: T001

- [x] **T007**: DAO 查询带上归属
  **文件**: `src/backend/bisheng/linsight/domain/models/linsight_skill.py`
  **逻辑**: 只改 DAO 方法，不动 T001 的列。`get_by_name`、`set_enabled`、`set_default_checked`、`delete_by_name`、`list_enabled`、`get_page` 增加归属条件，并保留 `strict_tenant_filter()`。批量更新显式带 `tenant_id` 和 `owner_user_id`。管理端调用固定 `owner_user_id=0`，旧请求响应不加字段（design §4.3、§5、§6）。
  **测试**: T006 全部通过；`test/linsight/test_skill_dao.py`、`test_skill_api.py`、`test_skill_list_paging.py` 不回归
  **覆盖 AC**: AC-05, AC-10, AC-12
  **依赖**: T001, T006

- [x] **T008**: 个人技能包存储与校验测试
  **文件**: `src/backend/test/linsight/test_personal_skill_store.py`
  **逻辑**: 个人对象键是 `linsight/personal-skills/{租户}/{用户}/{名字}/{哈希}.zip`，删除只删这个前缀，不删 `linsight/skills/{租户}/{名字}/` 下的企业包，也不删其他用户。个人上限固定：上传超过 52428800 字节为 11052 且 `data.limit_mb` 为 50；解压超过 209715200 字节为 11059 且 `limit_mb` 为 200；`SKILL.md` 超过 1048576 字节为 11073；条目超过 1000 为 11074。企业路径仍用系统配置的上限，`limit_mb` 等于那份配置。加密条目为 11063，损坏为 11067，缺少 `SKILL.md` 为 11068，路径越界为 11069，0 字节为 11071，多份技能为 11072，扩展名或 MIME 与内容不符为 11065（允许的 MIME 组合见 design §7.5）。这些失败都不调用对象写入。扩展名不是 `.md`、`.zip`、`.skill` 时拒绝。
  **覆盖 AC**: AC-03, AC-04, AC-16, AC-23
  **依赖**: T003, T004

- [x] **T009**: `SkillStore` 按归属选择前缀和上限
  **文件**: `src/backend/bisheng/linsight/domain/services/skill_store.py`
  **逻辑**: 对象键、本地缓存、读取和删除按 `owner_user_id` 选前缀。`0` 仍用 `linsight/skills`，存量对象不搬。个人上传用 T008 的固定上限，不读系统配置里更大的默认值。解压和路径校验沿用现有函数，不另写一套（design §4.3、§5）。
  **测试**: T008 中属于 `SkillStore` 的用例通过；`test_skill_store.py`、`test_skill_upload_limit.py` 不回归
  **覆盖 AC**: AC-03, AC-04, AC-16, AC-23
  **依赖**: T001, T008

- [x] **T010**: 现有体积错误补 `limit_mb` 的测试
  **文件**: `src/backend/test/linsight/test_skill_limit_mb.py`
  **逻辑**: 管理端上传、`SkillService` 创建、GitHub 导入三处抛出 11052 或 11059 时，响应 `data.limit_mb` 等于该路径当时使用的上限。个人路径不在本测试里（T008 已覆盖）。
  **覆盖 AC**: AC-04
  **依赖**: T003, T004

- [x] **T011**: 现有三处体积错误带上 `limit_mb`
  **文件**: `src/backend/bisheng/linsight/api/endpoints/skill.py`，`src/backend/bisheng/linsight/domain/services/skill_service.py`，`src/backend/bisheng/linsight/domain/services/github_skill_fetcher.py`
  **逻辑**: 这三处抛 11052、11059 时传入实际上限的 MiB 数。企业路径用系统配置，不改成个人技能的 50 / 200。不改这三处以外的校验结果。与 T004 同一 PR。
  **测试**: T010 全部通过
  **覆盖 AC**: AC-04
  **依赖**: T003, T004, T010

### Wave 3 — 个人技能服务（依赖 Wave 2、T005）

- [x] **T012**: 重名范围测试
  **文件**: `src/backend/test/linsight/test_skill_duplicate_scope.py`
  **逻辑**: 个人技能可以与本租户企业技能同名，也可以与其他用户的个人技能同名，两种都不返回 11055。同一归属下技能标识重复仍返回 11055。展示名相同而技能标识不同时，按新技能保存。两个请求同时写入同一用户的同一技能标识，只成功一行，后到的请求得到明确失败，不留下半份包。
  **覆盖 AC**: AC-12, AC-14
  **依赖**: T007

- [x] **T013**: 重名检查收进同一归属
  **文件**: `src/backend/bisheng/linsight/domain/services/skill_service.py`
  **逻辑**: `_check_duplicate` 只在同一 `owner_user_id` 内检查技能标识和展示名。管理端调用仍传 `owner_user_id=0`。不改管理端创建的其他步骤（design 决策 2、§4.3）。
  **测试**: T012 全部通过；`test_skill_api.py`、`test_skill_service.py` 不回归
  **覆盖 AC**: AC-12, AC-14
  **依赖**: T007, T012

- [x] **T014**: 创建、配额、导入标识测试
  **文件**: `src/backend/test/linsight/test_personal_skill_create.py`
  **逻辑**: 校验通过的 `.md` / `.zip` / `.skill` 写入当前用户名下，再次列出仍在，不依赖调用方缓存。当前租户已有 20 个或上传字节合计达到 209715200 时拒绝新增，已有行不变；停用的个人技能计入，企业技能不计入；超出个数为 11061，超出容量为 11062。校验失败、调用方取消、同名未确认时不写对象，并删掉本次解压临时目录。同名个人技能返回 11055，`data` 带 `skill_id` 和 `content_hash`，不写对象；与企业技能同名不走 11055。`import_id` 已保存且哈希一致时返回原技能，不再插第二行；查不到返回 11053；同一 `import_id` 配不同文件返回 11066 且不覆盖。并发同名只留一行。创建成功写一条审计：操作者、租户、技能 ID、来源、内容哈希、结果；正文和文件字节不在日志里。审计插入失败不把已保存的技能改成失败。另一租户列不出这些行。
  **覆盖 AC**: AC-01, AC-02, AC-05, AC-13, AC-14, AC-16, AC-17, AC-24
  **依赖**: T003, T007, T009

- [x] **T015**: `PersonalSkillService` 创建、用量和导入查询
  **文件**: `src/backend/bisheng/linsight/domain/services/personal_skill_service.py`
  **逻辑**: 新增该服务，本任务只加 `create`、`usage`、`find_by_import`，以及内部的 `_load_own_skill`：按当前租户加载行，没有这行或归属不是本人就返回 11053。后续 T017、T019 只用这个加载；T023 在归属通过后补 `require_business_action`，不改这里的创建流程。`create` 写 `owner_user_id=当前用户`，复用 `SkillService` 已有的 `authorize_created`（资源类型 `linsight_skill`，所有者是上传者），不新写 OpenFGA。个数和容量与插入放在同一事务，超出则回滚并返回 11061 或 11062。同名返回 11055 且带 `skill_id`、`content_hash`。成功后把 `import_id` 写入 `last_import_id`，并按 design §7.1 记审计。请求结束删除解压临时目录。校验未通过不调用对象写入。`usage` 返回已用个数、已用字节和上限 20、209715200。
  **测试**: T014 全部通过
  **覆盖 AC**: AC-01, AC-02, AC-05, AC-13, AC-14, AC-16, AC-17, AC-24
  **依赖**: T005, T009, T013, T014

- [x] **T016**: 覆盖更新测试
  **文件**: `src/backend/test/linsight/test_personal_skill_overwrite.py`
  **逻辑**: `expected_content_hash` 与当前行不一致时不写对象、不改行，返回 11064。一致时先写新对象，再改哈希、对象路径和大小；技能 ID 和启停状态不变。行更新成功后删除旧哈希的对象；新旧哈希相同则不删。替换后合计容量超过 209715200 时拒绝，旧对象和旧行都保留，返回 11062。个数不变。覆盖成功记一条审计。行更新失败时旧哈希仍指向旧对象。他人的技能 ID 返回 11053，且不调用 `require_business_action`。
  **覆盖 AC**: AC-14, AC-17, AC-18
  **依赖**: T003, T015

- [x] **T017**: 覆盖更新
  **文件**: `src/backend/bisheng/linsight/domain/services/personal_skill_service.py`
  **逻辑**: 增加 `overwrite`，加载行只用 T015 的 `_load_own_skill`。顺序按 design §7.2：哈希不一致直接 11064；一致则先写新对象，再改行，保留技能 ID 和启停状态；行更新成功后删旧对象，新旧哈希相同不删，删除失败留给 T035 清扫。容量按新文件重算。本任务不在 `_load_own_skill` 里调用统一授权。
  **测试**: T016 全部通过
  **覆盖 AC**: AC-14, AC-17, AC-18
  **依赖**: T015, T016

- [x] **T018**: 启停与删除测试
  **文件**: `src/backend/test/linsight/test_personal_skill_lifecycle.py`
  **逻辑**: 目标状态与当前相同则返回当前技能，不报错，不改 `update_time`，不记审计。状态确有变化时记一条审计。当前用户名下已没有该 ID 的删除，返回与成功相同的空结果，响应无名称和正文。他人的删除也是这条空结果，不是 11054。启停打到不存在的 ID 返回 11053。删除成功后该行不在，并在本次请求删除该行指向的对象；其他用户的行还在。没有技能行指向这个对象时同样删除对象。停用后行还在，`enabled` 为 false。技能中心和任务候选是否还能看见，由 T020 断言，本测试直接查行和对象。
  **覆盖 AC**: AC-09, AC-10, AC-15, AC-17, AC-19
  **依赖**: T015, T003

- [x] **T019**: 启停与删除
  **文件**: `src/backend/bisheng/linsight/domain/services/personal_skill_service.py`
  **逻辑**: 增加 `set_enabled` 和 `delete`，加载行只用 `_load_own_skill`。重复提交的结果按 design §7.3。删除在本次请求删除对象，不查哪些会话未结束（design §5、§7.8）。停用不删对象、不删会话目录。不在本任务里做列表过滤。
  **测试**: T018 全部通过
  **覆盖 AC**: AC-09, AC-10, AC-15, AC-17, AC-19
  **依赖**: T015, T018

- [x] **T020**: 技能中心列表与任务候选测试
  **文件**: `src/backend/test/linsight/test_personal_skill_lists.py`
  **逻辑**: 技能中心返回本租户已启用企业技能，加上本人全部个人技能（含停用和启停状态）；不含其他用户的个人技能，不含已停用的企业技能。任务候选只含已启用的企业技能和已启用的个人技能。同名且个人技能已启用时，技能中心两边都在，任务候选只留个人技能；个人技能停用或删除后，候选改为企业技能。搜索只匹配当前页签的名称、技能标识和用途说明。管理员停用企业技能后，该技能离开所有用户的候选，这些用户的个人技能仍在。页签数量等于这两组的个数。
  **覆盖 AC**: AC-06, AC-07, AC-09, AC-11, AC-12, AC-26
  **依赖**: T007, T019

- [x] **T021**: 两个读取方法
  **文件**: `src/backend/bisheng/linsight/domain/services/personal_skill_service.py`
  **逻辑**: 增加 `list_center` 和 `list_candidates`，共用同一套归属条件（design 决策 3）。列表一次查询，不逐条调用 `require_business_action`。同名去重只发生在 `list_candidates`。`GET /api/v1/linsight/skill/selectable` 不在本任务修改。
  **测试**: T020 全部通过
  **覆盖 AC**: AC-06, AC-07, AC-09, AC-11, AC-12, AC-26
  **依赖**: T007, T019, T020

- [x] **T022**: 单条读取与授权顺序测试
  **文件**: `src/backend/test/linsight/test_personal_skill_access.py`
  **逻辑**: 当前租户没有这行，或 `owner_user_id` 不是当前用户：详情、读文件、更新、启停、删除都返回 11053，响应无名称、正文和对象地址，且断言没有调用 `require_business_action`。归属是本人时，这五项都先调用它，资源类型 `linsight_skill`，资源编号是技能 ID；详情、读文件、更新、启停的动作是 `edit`，删除是 `delete`。技能行还在但对象读不出时，详情返回 200 且 `bundle_missing=true`，不是 11053。企业技能被停用或删除后，按该技能 ID 取详情得到可区分的结果（停用为 `enabled=false` 的 200，删除为 11053），供前端回列表。
  **覆盖 AC**: AC-08, AC-21, AC-22
  **依赖**: T005, T017, T019

- [x] **T023**: 详情、读文件和统一授权
  **文件**: `src/backend/bisheng/linsight/domain/services/personal_skill_service.py`
  **逻辑**: 增加 `get` 和 `read_file`。只改 `_load_own_skill`：归属通过后再 `require_business_action`（design 决策 5）。不改 T017、T019 里覆盖、启停、删除的其余步骤。`get` 在对象缺失时返回 `bundle_missing=true`。不把企业技能的使用改成这条授权。
  **测试**: T022 全部通过；T016、T018 仍通过
  **覆盖 AC**: AC-08, AC-21, AC-22
  **依赖**: T005, T017, T019, T022

### Wave 4 — 接口（依赖 Wave 3）

- [x] **T024**: 个人技能接口测试
  **文件**: `src/backend/test/linsight/test_personal_skill_api.py`
  **逻辑**: 普通登录用户可调用下面这些路径；未登录拒绝。管理端 `GET/POST/PUT/PATCH/DELETE /api/v1/linsight/skill` 的响应与改前一致，列表里没有个人技能。`GET /selectable` 仍只返回本租户已启用企业技能。新路径：`POST /personal` 创建，同名时 11055 且不写对象；`POST /personal/{id}/overwrite`；`GET /personal/import/{import_id}`；`GET /personal/usage`；`GET /center`；`GET /candidates`；`GET /personal/{id}`；`GET /personal/{id}/file`；`PATCH /personal/{id}/status`；`DELETE /personal/{id}`。字面路径不被 `/{name}` 吃掉。错误响应使用 T004 的译文。
  **覆盖 AC**: AC-01, AC-02, AC-06, AC-08, AC-13, AC-14
  **依赖**: T015, T017, T019, T021, T023

- [x] **T025**: 个人技能路由
  **文件**: `src/backend/bisheng/linsight/api/endpoints/personal_skill.py`，`src/backend/bisheng/linsight/api/router.py`
  **逻辑**: 新路由用普通登录用户，委托 `PersonalSkillService`，接口层不访问仓库。路径与 T024 一致，注册顺序保证 `center`、`candidates`、`personal` 不会被现有 `/{name}` 当成技能名。不改 `skill.py` 里管理端和 `/selectable` 的响应形状（design §6；输入框、装载和开放接口改读 `list_candidates`，见 T027、T029）。
  **测试**: T024 全部通过
  **覆盖 AC**: AC-01, AC-02, AC-06, AC-08, AC-13, AC-14
  **依赖**: T015, T017, T019, T021, T023, T024

- [x] **T026**: 开放接口任务候选测试
  **文件**: `src/backend/test/open_api/test_task_mode_personal_skills.py`
  **逻辑**: `run_mode=task` 的可用技能和提交校验改读当前调用方的 `list_candidates`。调用方自己已启用的个人技能可用；其他用户的个人技能按不存在拒绝，不出现在可用列表。已停用的个人技能不可用。同名时只出现个人技能。请求字段仍是技能名，不改开放接口的请求体。日常模式响应不变。
  **覆盖 AC**: AC-08, AC-11, AC-12
  **依赖**: T021

- [x] **T027**: 开放接口改读任务候选
  **文件**: `src/backend/bisheng/open_api/domain/services/task_mode_service.py`
  **逻辑**: `enabled_skill_rows` 改为当前身份的 `list_candidates`。个人技能只对所有者生效。不改请求 schema，不改日常模式。
  **测试**: T026 全部通过；`test/open_api/` 里既有任务模式用例不回归
  **覆盖 AC**: AC-08, AC-11, AC-12
  **依赖**: T021, T026

### Wave 5 — 任务装载与运行时拒绝（依赖 T002、T021、T019）

- [x] **T028**: 整包拷入与恢复测试
  **文件**: `src/backend/test/linsight/test_personal_skill_provisioning.py`
  **逻辑**: 新建任务把每个任务候选的整包拷进 `/skills/{名字}/`，名称和用途说明进入名单。同名只拷个人技能。停用或删除的个人技能不拷。装载写入 `skill_snapshot`（技能名、技能 ID、归属用户、内容哈希）。请求带企业技能的 `skill_id`、同名个人技能被拷入时，会话 `skills` 列写入留下的个人技能目录名；只传技能名的旧请求仍按名字写入。同一次会话恢复或继续时，快照里已有的目录不再写入另一行技能；同名企业技能因此不会混进该目录。拷贝发生在建立代码执行器、拍下 E2B `file_list` 之前，清单里能看到技能包。不另调模型生成名单。
  **覆盖 AC**: AC-09, AC-11, AC-12, AC-15
  **依赖**: T002, T009, T021

- [x] **T029**: 整包拷入与恢复时不覆盖已有目录
  **文件**: `src/backend/bisheng/linsight/domain/services/skill_provisioning.py`，`src/backend/bisheng/linsight/domain/services/workbench_impl.py`，`src/backend/bisheng/linsight/domain/schemas/linsight_schema.py`
  **逻辑**: `materialize_session_skills` 改为拷入 `list_candidates` 的整包，并写 `skill_snapshot`。恢复和继续提问时跳过快照里已有的目录名（design §7.8）。`workbench_impl` 里给 E2B 拍 `file_list` 的调用保持在拷贝之后；不改单个文件 5 MiB 的限制。既有四个调用点仍调用这一个函数。`linsight_schema.py` 的提交请求增加可选 `skill_ids`。装载时把这些 ID 换成实际拷入的目录名，写入现有 `skills` 列；同名时勾了企业技能 ID，列里写留下的个人技能目录名。只传技能名的旧请求原样写入该列。
  **测试**: T028 全部通过；`test_skill_provisioning.py` 不回归
  **覆盖 AC**: AC-09, AC-11, AC-12, AC-15
  **依赖**: T002, T009, T021, T028

- [x] **T030**: 勾选强调与工具不可用测试
  **文件**: `src/backend/test/linsight/test_skill_selection_prompt.py`
  **逻辑**: 外层中间件按勾选在 “Available Skills” 对应行后追加「用户选中了这个技能」，不改 `SKILL.md` 文件。未勾选的候选仍在名单里，但没有这句。勾选按技能 ID 比对，先换成实际拷入的目录名；勾的是被同名个人技能盖住的企业技能时，这句话落在留下的个人技能上。只传技能名的旧请求按名字匹配留下的目录。检查点里已有 `skills_metadata` 时不重扫磁盘。`allowed-tools` 里有本次任务没有的工具时，该行加「该技能需要的工具当前不可用」；没有声明则不加。不因此拒绝任务。真正调用到缺失工具时，结果用同一句，不用堆栈。
  **覆盖 AC**: AC-11, AC-25, AC-26
  **依赖**: T002, T029

- [x] **T031**: 包一层技能名单中间件
  **文件**: `src/backend/bisheng/linsight/domain/services/agent_factory.py`
  **逻辑**: 在现有 `SkillsMiddleware` 外面包一层，按会话 `skills` 列里的目录名追加两句。同名覆盖后，该列已是 T029 留下的目录名。不改 deepagents 里的 `SkillsMiddleware`，不把勾选写进技能包，不加请求字段（design §7.8）。
  **测试**: T030 全部通过
  **覆盖 AC**: AC-11, AC-25, AC-26
  **依赖**: T029, T030

- [x] **T032**: 读取和代码执行前拒绝测试
  **文件**: `src/backend/test/linsight/test_skill_runtime_guard.py`
  **逻辑**: `read_file` 读到 `/skills/{名字}/` 时，按 `skill_snapshot` 里的技能 ID 查行，该行已停用或已删除则拒绝这次读取。同名的企业技能仍启用时也不放行，因为目录里是个人技能的文件。代码执行器执行前做同一次检查：脚本路径 `skills/{名字}/...` 命中已停用或已删除的快照行则拒绝执行。快照里没有的路径不拦截。已返回给模型的内容不回收。
  **覆盖 AC**: AC-09, AC-15
  **依赖**: T002, T019, T029

- [x] **T033**: 两处运行时检查
  **文件**: `src/backend/bisheng/linsight/domain/services/workspace_backend.py`，`src/backend/bisheng/linsight/domain/services/skill_runtime_guard.py`
  **逻辑**: `WorkspaceBackend.read` / `aread` 在路径落在 `/skills/{名字}/` 时调用守卫。新建 `skill_runtime_guard.py`，在 `bisheng_code_interpreter` 执行前扫描本次代码引用的 `skills/{名字}/`，按快照拒绝。不改 `bisheng_langchain` 里的执行器。只拦 `read_file` 不够，两处都要有（design §5、§7.8）。
  **测试**: T032 全部通过
  **覆盖 AC**: AC-09, AC-15
  **依赖**: T029, T032

### Wave 6 — 无主对象清扫（依赖 T009）

- [x] **T034**: 无主个人技能对象清扫测试
  **文件**: `src/backend/test/linsight/test_personal_skill_orphan_sweep.py`
  **逻辑**: `linsight/personal-skills/{租户}/{用户}/{名字}/` 下，没有任何技能行的 `content_hash` 指向的对象会被删掉。仍被当前行指向的哈希不删。企业前缀 `linsight/skills/` 不在清扫范围内。任务按租户执行：只删该租户前缀下的无主对象。
  **覆盖 AC**: AC-16
  **依赖**: T001, T009

- [x] **T035**: 按租户清扫无主对象
  **文件**: `src/backend/bisheng/worker/linsight/personal_skill_sweep.py`，`src/backend/bisheng/core/config/settings.py`
  **逻辑**: Beat 按租户各发一条子任务。子任务参数带 `tenant_id`，发布时写入 Celery headers，worker 的 `task_prerun` 经 `worker/tenant_context.py` 恢复 `current_tenant_id` 后再查技能行。不在一条任务里跨租户查询。不新增 YAML 顶层键，默认调度写在 `settings.py` 既有 `beat_schedule` 默认项旁。清扫失败只记日志，不影响用户请求里已经返回的删除结果（design §5）。
  **测试**: T034 全部通过
  **覆盖 AC**: AC-16
  **约束**: `tenant_id` 走 Celery headers → ContextVar，不从任务体内临时改租户后再漏回默认租户
  **依赖**: T009, T034

### Wave 7 — 客户端（手动验证；测试用 mock，不依赖后端进程）

接口形状以 T024 为准：技能中心分 `personal` 与 `enterprise` 两组，带 `source`、`enabled`、`content_hash`、`bundle_missing` 和两个页签计数；任务候选按技能 ID 返回、不按名字合并；用量为已用个数 / 20、已用字节 / 209715200。

- [x] **T036**: 输入框勾选测试
  **文件**: `src/frontend/client/src/components/Skills/__tests__/skillMenuSelection.test.tsx`
  **逻辑**: 点一行切换勾选，菜单不关闭，不跳进技能中心详情。同名的企业技能和个人技能各一行，并标来源。个人技能停用后只剩企业技能那一行。名称或说明被截断时，悬停或聚焦在右侧展开全文，不打开详情。
  **覆盖 AC**: AC-26
  **依赖**: 无

- [x] **T037**: 技能中心页面测试
  **文件**: `src/frontend/client/src/pages/skills/SkillCenterPage.test.tsx`
  **逻辑**: mock 服务端数据。页签为「我的技能」和「技能广场」；「我的技能」分「我创建的」「企业提供」，计数分别是个人技能个数和企业技能个数。搜索只筛当前页签，切换页签清空搜索词。删除确认文案是「删除‘{名称}’后，后续任务将无法使用该 Skill，已有对话和生成结果保留。」按钮为【取消】【删除】。删除请求失败时卡片还在，并提示「删除失败，请重试」。`bundle_missing` 时说明原因并提供【更新技能】。当前详情对应的技能已删除，或企业技能已停用、已删除时，提示原因并回到列表，其他技能仍在。用户停用自己的个人技能时留在详情里，只更新开关。
  **覆盖 AC**: AC-06, AC-07, AC-20, AC-21, AC-22
  **依赖**: 无

- [x] **T038**: 去掉预览开关的测试
  **文件**: `src/frontend/client/src/components/Skills/__tests__/skillPreviewConfig.test.ts`，`src/frontend/client/src/layouts/skillCenterNavigation.test.tsx`
  **逻辑**: 技能中心入口不再读取 `skillCenterPreviewEnabled`。导航在该字段缺失时仍显示技能中心。
  **覆盖 AC**: AC-02, AC-06
  **依赖**: 无

- [x] **T039**: 技能中心改为调用服务端
  **文件**: `src/frontend/client/src/api/skillCenter.ts`，`src/frontend/client/src/components/Skills/useSkillCenter.ts`，`src/frontend/client/src/components/Skills/skillPreviewStore.ts`
  **逻辑**: 列表、详情、用量、创建、覆盖、启停、删除、按 `import_id` 查询都走 T025 的接口，使用现有 `request`，不直接 `import axios`。去掉 IndexedDB 读写；`skillPreviewStore.ts` 无引用后删除。保存成功才算添加成功。
  **覆盖 AC**: AC-01, AC-02, AC-06
  **手动验证**: 在一台浏览器保存后，换一台浏览器打开技能中心仍能看到；断网时不把失败显示成已保存
  **依赖**: T025, T037

- [x] **T040**: 技能中心页面接上服务端数据
  **文件**: `src/frontend/client/src/pages/skills/SkillCenterPage.tsx`，`src/frontend/client/src/pages/skills/SkillList.tsx`，`src/frontend/client/src/pages/skills/SkillGrid.tsx`
  **逻辑**: 数据源换成 T039。页面结构不改：两组列表、广场只读卡片、点击整行或卡片打开详情、搜索和排序留下。页签计数用接口返回的个数。
  **覆盖 AC**: AC-06, AC-07, AC-12
  **手动验证**: 同名技能在「我的技能」两组都出现并标来源，「技能广场」只有企业技能；搜索不带出另一个页签的结果；切换页签后搜索框为空
  **依赖**: T037, T039

- [x] **T041**: 上传弹窗
  **文件**: `src/frontend/client/src/components/Skills/SkillUploadDialog.tsx`
  **逻辑**: 打开时展示已用个数 / 20 和已用容量 / 200 MiB。一次保存生成 `import_id`，重试沿用同一个；重试前先按 `import_id` 查询，已成功则不再提交。11055 时先提示已存在，确认后才调用覆盖，并带上当时的 `content_hash`。未确认不发保存请求。11064 显示「该 Skill 已更新，请刷新后重试」。校验失败的译文显示在文件区，并提供【重新选择】。文件区走现有 `translateApiErrorMessage`，让 11052、11059、11073、11074 代入 `limit_mb`，不在组件里写死这四句。取消关闭弹窗且不发保存请求。
  **覆盖 AC**: AC-04, AC-13, AC-14, AC-16, AC-18, AC-23, AC-24
  **手动验证**: 超过 20 个或 200 MiB 时按钮不可提交并看到对应错误；故意上传超限文件时，文件区出现带具体数字的那一句，不是 `{{limit_mb}}`，也不是通用的校验失败；取消后刷新，技能条数不变；同名先出现提示，取消后旧技能还在，确认后 ID 不变、启停状态不变
  **依赖**: T004, T039

- [x] **T042**: 详情里的删除、缺文件和失效
  **文件**: `src/frontend/client/src/components/Skills/SkillDetails.tsx`
  **逻辑**: 删除确认句和按钮按 AC-20。失败保留详情并提示「删除失败，请重试」。`bundle_missing` 时提供【更新技能】，走 T041 的覆盖，带当前 `content_hash`。当前技能已删除，或企业技能已停用、已删除时，提示原因并关闭详情回到列表。用户停用自己的个人技能时不关闭详情。本文件里新增的中文改走 T047 的键，不新增硬编码中文。
  **覆盖 AC**: AC-20, AC-21, AC-22
  **手动验证**: 按 AC-20、AC-21、AC-22 各走一遍；停用自己的技能后开关关掉且详情仍在
  **依赖**: T037, T039, T041

- [x] **T043**: 输入框恢复勾选
  **文件**: `src/frontend/client/src/components/Skills/SkillMenuPanel.tsx`，`src/frontend/client/src/components/Skills/SkillMenuRow.tsx`
  **逻辑**: 数据改为 T025 的任务候选。点一行切换勾选并保持菜单打开，不 `navigate` 到详情。勾选沿用现有任务请求里的技能名单，并额外提交 `skill_ids`。同名两行都显示。底部【上传技能】【管理技能】保留，管理技能仍打开技能中心。详情只从技能中心的卡片进入。
  **覆盖 AC**: AC-11, AC-26
  **手动验证**: 点一行后菜单还在，输入框上方出现或取消该技能；再点进技能中心才打开详情；个人技能停用后菜单只剩同名企业技能
  **依赖**: T036, T039

- [x] **T044**: 去掉预览开关
  **文件**: `src/frontend/client/src/components/Skills/types.ts`，`src/frontend/client/src/vite-env.d.ts`，`src/frontend/client/src/routes/index.tsx`
  **逻辑**: 删除 `skillCenterPreviewEnabled`。技能中心路由不再包在这个开关里。不改 `public/assets/bisheng/config.js`（那是本地未提交覆盖）；字段删掉后不再被读取。
  **测试**: T038 全部通过
  **覆盖 AC**: AC-02, AC-06
  **依赖**: T038

- [x] **T045**: 侧栏入口去掉预览开关
  **文件**: `src/frontend/client/src/layouts/MainLayout.tsx`，`src/frontend/client/src/components/Skills/SkillMenuEntries.tsx`
  **逻辑**: 这两处不再按 `skillCenterPreviewEnabled` 决定出不出现技能中心。入口始终在。不改【+】菜单里的勾选行为（T046）。
  **测试**: T038 全部通过
  **覆盖 AC**: AC-06
  **手动验证**: 侧栏能进入技能中心，不依赖本地 config.js 里的开关
  **依赖**: T038, T044

- [x] **T046**: 【+】菜单去掉预览分叉
  **文件**: `src/frontend/client/src/components/Linsight/Input/PlusMenu.tsx`，`src/frontend/client/src/components/Chat/Input/ChatKnowledge.tsx`
  **逻辑**: 去掉按 `skillCenterPreviewEnabled` 分叉的两套技能菜单。桌面和移动宽度都使用 T043 的勾选菜单。不改知识库菜单的其他行为。
  **测试**: T036、T038 全部通过
  **覆盖 AC**: AC-26
  **手动验证**: 桌面和移动宽度下，【+】里的技能行可以勾选，菜单不关闭
  **依赖**: T036, T038, T043, T044

- [x] **T047**: 上传、删除和缺文件的三语文案
  **文件**: `src/frontend/client/src/locales/zh-Hans/translation.json`，`src/frontend/client/src/locales/en/translation.json`，`src/frontend/client/src/locales/ja/translation.json`
  **逻辑**: 补齐 T041、T042 新出现的句子。删除确认句的中文用 AC-20 的原文，`{名称}` 为展示名。失败句为「删除失败，请重试」。三语键同时补上。不改 `api_errors`。
  **覆盖 AC**: AC-20, AC-21
  **依赖**: T041, T042

---

## AC 追溯

| AC | 测试任务 |
|----|----------|
| AC-01 | T014, T024 |
| AC-02 | T014, T024, T038 |
| AC-03 | T008 |
| AC-04 | T008, T010 |
| AC-05 | T006, T014 |
| AC-06 | T020, T024, T037, T038 |
| AC-07 | T020, T037 |
| AC-08 | T022, T024, T026 |
| AC-09 | T018, T020, T028, T032 |
| AC-10 | T006, T018 |
| AC-11 | T020, T026, T028, T030 |
| AC-12 | T006, T012, T020, T026, T028 |
| AC-13 | T014, T024 |
| AC-14 | T012, T014, T016, T024 |
| AC-15 | T018, T028, T032 |
| AC-16 | T008, T014, T034 |
| AC-17 | T014, T016, T018 |
| AC-18 | T016 |
| AC-19 | T018 |
| AC-20 | T037 |
| AC-21 | T022, T037 |
| AC-22 | T022, T037 |
| AC-23 | T008 |
| AC-24 | T014 |
| AC-25 | T030 |
| AC-26 | T020, T030, T036 |

---

## 实际偏差记录

> 只留一行指针，论证在 design.md。推翻已确认的决策时，先停下与用户重新确认。

- 输入框菜单读技能中心里已启用的个人技能和企业技能，不读 `/candidates`。候选接口在同名时只留个人技能，菜单需要两行（AC-26）。提交的 `skill_ids` 仍交给装载，装载按候选规则同名只拷个人包。
