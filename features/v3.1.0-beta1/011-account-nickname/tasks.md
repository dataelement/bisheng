# Tasks：账号与昵称规则及前后端统一

**关联**：[规格](./spec.md) · [设计](./design.md) · [参考用例](./test-cases.md)

## 状态

| 步骤 | 状态 | 备注 |
| --- | --- | --- |
| discovery.md | ✅ 已确认 | 用户确认完整范围。 |
| spec.md | ✅ 已评审 | 用户确认 32 条 AC。 |
| design.md | ✅ 已评审 | 用户回复「确认设计，开始实现」。 |
| test-cases.md | ✅ 已检查 | 40 条八列参考用例，均待实际执行。 |
| tasks.md | ✅ 已拆解 | 按原子任务审查，见 tasks-review.md。 |
| 实现 | 🔲 进行中 | 51 / 53 完成；代码实现与本地验证完成，真实 HTTP E2E 与发布审查待目标环境执行。 |

按依赖顺序执行；后端测试先于配对业务实现。新增模型/错误码属于基础设施。每项最多两个主要源文件；生成的锁文件和翻译产物随所属任务更新。无 Worker 新增逻辑，不改变 Celery tenant_id 传递。

保留共享发版线工作区及其他任务修改，不切分、暂存或清理它们。设计论证见 design.md；这里记录执行与验证。

- [x] **T001：身份元数据与模型**（基础设施）
  **文件**：`src/backend/bisheng/user/domain/models/user.py`；`src/backend/bisheng/user/domain/models/account_identity.py`。
  **逻辑与验证**：新增三个默认元数据列、精确登记及写锁模型；旧列长度和值不变，扩展来源唯一约束。
  **覆盖 AC:** AC-08, AC-09, AC-10, AC-14, AC-32
  **依赖:** 无

- [x] **T002：错误码与直接依赖**（基础设施）
  **文件**：`src/backend/bisheng/common/errcode/user.py`；`src/backend/pyproject.toml`。
  **逻辑与验证**：声明 10612～10615 及已锁定 regex 直接依赖；不更换其他依赖版本。
  **覆盖 AC:** AC-02, AC-03, AC-04, AC-31
  **依赖:** T001

- [x] **T003：字段规则测试先行**（后端测试）
  **文件**：`src/backend/test/user/test_identity_rules.py`。
  **逻辑与验证**：先运行缺失规则模块的红测试；覆盖 1/64/65 账号、1/32/33 昵称、Unicode、不可见、原值 no-op、四类密码与 128 上限。
  **覆盖 AC:** AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-29, AC-31
  **依赖:** T002

- [x] **T004：纯字段规则**（后端 Domain）
  **文件**：`src/backend/bisheng/user/domain/rules/identity.py`。
  **逻辑与验证**：实现 validate_account、validate_nickname、validate_nickname_change、password_meets_policy；保留原文并返回明确领域错误，运行 T003。
  **覆盖 AC:** AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-29, AC-31
  **依赖:** T003

- [x] **T005：共享规则包元数据**（基础设施）
  **文件**：`src/frontend/packages/identity/package.json`；`src/frontend/packages/identity/tsconfig.json`。
  **逻辑与验证**：创建无 React 依赖工作区包，直接导出 rules.ts，复用工作区 TypeScript/Vitest。
  **覆盖 AC:** AC-04, AC-28, AC-31
  **依赖:** 无

- [x] **T006：共享规则单元测试先行**（前端测试）
  **文件**：`src/frontend/packages/identity/src/rules.test.ts`。
  **逻辑与验证**：编写与后端同组字符、长度、密码样本及空白过滤断言，不混入规则实现。
  **覆盖 AC:** AC-02, AC-03, AC-04, AC-05, AC-07, AC-28, AC-29, AC-31
  **依赖:** T005

- [x] **T007：共享规则实现**（前端共享）
  **文件**：`src/frontend/packages/identity/src/rules.ts`；`src/frontend/packages/identity/eslint.config.mjs`。
  **逻辑与验证**：实现纯校验、字符计数和五类密码检查；只返回标识，测试 T006 通过。
  **覆盖 AC:** AC-02, AC-03, AC-04, AC-05, AC-07, AC-28, AC-29, AC-31
  **依赖:** T006

- [x] **T008：账号存储测试先行**（后端测试）
  **文件**：`src/backend/test/user/test_account_identity_repository.py`。
  **逻辑与验证**：隔离 SQLite fixture 使用真实 User 和登记模型，验证占用、精确键、候选、回滚及旧列；两库并发由集成标记覆盖。
  **覆盖 AC:** AC-08, AC-09, AC-10, AC-12, AC-13, AC-14, AC-32
  **依赖:** T001, T004

- [x] **T009：账号事务存储**（后端 Domain）
  **文件**：`src/backend/bisheng/user/domain/repositories/account_identity_repository.py`。
  **逻辑与验证**：实现锁行初始化、identity_transaction、全实例占用、exact/legacy 解析及 User+登记+初始绑定原子插入，运行 T008。
  **覆盖 AC:** AC-08, AC-09, AC-10, AC-12, AC-13, AC-14, AC-32
  **依赖:** T008

- [x] **T010：迁移图与幂等测试先行**（后端测试）
  **文件**：`src/backend/test/database/test_f011_account_identity_migration.py`。
  **逻辑与验证**：读取真实 Alembic 单头；测试已存在列/索引跳过、默认版本、无原值回填及降级保护。
  **覆盖 AC:** AC-14, AC-32
  **依赖:** T001

- [x] **T011：身份字段 DDL**（基础设施）
  **文件**：`src/backend/bisheng/core/database/alembic/versions/v3_1_0_f011_account_identity.py`。
  **逻辑与验证**：挂当前真实 head，用助手增列与替换索引；默认值保留历史。有 v1 数据禁止直接回退旧索引，升级说明解释前向修复。
  **覆盖 AC:** AC-14, AC-32
  **依赖:** T010

- [x] **T012：账号业务及登录回归先行**（后端测试）
  **文件**：`src/backend/test/user/test_account_identity_service.py`；`src/backend/test/user/test_account_login_rules.py`。
  **逻辑与验证**：验证唯一可登录候选、禁用、歧义、旧长账号、新值不 trim 与初始化；模拟验证码及密码门禁，不探测多身份密码。
  **覆盖 AC:** AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-26, AC-29, AC-31
  **依赖:** T009

- [x] **T013：统一账号业务**（后端 Domain）
  **文件**：`src/backend/bisheng/user/domain/services/account_identity_service.py`。
  **逻辑与验证**：连接规则与 repository，固定本地 v1/外部 v0，精确解析并拒绝歧义，兼容按角色组创建。运行 T012。
  **覆盖 AC:** AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-26, AC-29, AC-31
  **依赖:** T012

- [x] **T014：注册登录与旧 DAO 适配**（后端 Domain）
  **文件**：`src/backend/bisheng/user/domain/services/user.py`；`src/backend/bisheng/user/domain/models/user.py`。
  **逻辑与验证**：注册取消 30 限制及 trim，调用身份事务；登录唯一解析后保留原次数/密码/租户/会话；旧创建 DAO 仅委托新存储。
  **覆盖 AC:** AC-02, AC-03, AC-04, AC-05, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-26, AC-29, AC-31
  **依赖:** T013

- [x] **T015：后台本地创建接入**（后端 Domain）
  **文件**：`src/backend/bisheng/department/domain/services/department_service.py`；`src/backend/bisheng/department/domain/schemas/department_schema.py`。
  **逻辑与验证**：两个 local-members 共用 create_local；保留角色、来源和部门校验，创建昵称 32，编辑 DTO 可接收未变历史值。
  **覆盖 AC:** AC-02, AC-03, AC-04, AC-05, AC-08, AC-14, AC-20, AC-26, AC-29, AC-31
  **依赖:** T014

- [x] **T016：兼容创建协议**（后端 API）
  **文件**：`src/backend/bisheng/api/v1/schemas.py`；`src/backend/bisheng/user/api/user.py`。
  **逻辑与验证**：user/create 可传独立 external_id，未传保留兼容且校验两个用途；旧 SSO 创建接统一存储，保留认证门禁。
  **覆盖 AC:** AC-04, AC-08, AC-15, AC-26, AC-31
  **依赖:** T014

- [x] **T017：SSO 身份回归先行**（后端测试）
  **文件**：`src/backend/test/sso_sync/test_account_identity_compatibility.py`。
  **逻辑与验证**：测试 v0 原匹配、v1 精确绑定、旧 SSO 改名后身份不变及同名歧义；并发创建见 T048。
  **覆盖 AC:** AC-09, AC-10, AC-13, AC-25, AC-26, AC-32
  **依赖:** T013

- [x] **T018：SSO 账号适配**（后端 Domain）
  **文件**：`src/backend/bisheng/sso_sync/domain/services/login_sync_service.py`。
  **逻辑与验证**：统一外部候选解析与创建最终查重，保留合法来源迁移及后续同步。运行 T017。
  **覆盖 AC:** AC-09, AC-10, AC-13, AC-25, AC-26, AC-32
  **依赖:** T017

- [x] **T019：改名与原子存储测试先行**（后端测试）
  **文件**：`src/backend/test/user/test_nickname_service.py`；`src/backend/test/user/test_nickname_repository.py`。
  **逻辑与验证**：验证原值 no-op、历史非法原值、实际改名保护、审计/DSH 同提交及存储失败回滚。
  **覆盖 AC:** AC-04, AC-06, AC-07, AC-18, AC-19, AC-22, AC-23, AC-24, AC-25, AC-32
  **依赖:** T004, T009

- [x] **T020：昵称事务存储**（后端 Domain）
  **文件**：`src/backend/bisheng/user/domain/repositories/nickname_repository.py`。
  **逻辑与验证**：锁 User 后比较原值、校验，在独立事务内提交昵称、保护标记、资料版本及组织快照审计；不接受调用方的人员关联事务。运行 T019。
  **覆盖 AC:** AC-04, AC-06, AC-07, AC-18, AC-19, AC-22, AC-23, AC-24, AC-25, AC-32
  **依赖:** T019

- [x] **T021：昵称领域服务**（后端 Domain）
  **文件**：`src/backend/bisheng/user/domain/services/nickname_service.py`。
  **逻辑与验证**：认证本人目标派生，受管人员由原部门服务授权；不改账号/权限/密码，不增 token_version。
  **覆盖 AC:** AC-04, AC-06, AC-07, AC-18, AC-19, AC-22, AC-23, AC-24, AC-25, AC-32
  **依赖:** T020

- [x] **T022：本人 API 测试先行**（后端测试）
  **文件**：`src/backend/test/user/test_nickname_api.py`。
  **逻辑与验证**：真实 FastAPI 路由与隔离 repository，成功/拒绝配对，额外字段拒绝及 GET 最终状态、envelope 断言。
  **覆盖 AC:** AC-16, AC-17, AC-18, AC-22, AC-23, AC-24, AC-31
  **依赖:** T021

- [x] **T023：本人昵称接口与请求模型**（后端 API）
  **文件**：`src/backend/bisheng/user/api/endpoints/profile.py`；`src/backend/bisheng/user/domain/schemas/nickname.py`。
  **逻辑与验证**：PATCH /user/profile/nickname 使用 UserPayload，extra forbid，只收 user_name；返回最小资料。运行 T022。
  **覆盖 AC:** AC-16, AC-17, AC-18, AC-22, AC-23, AC-24, AC-31
  **依赖:** T022

- [x] **T024：延迟同步保护测试先行**（后端测试）
  **文件**：`src/backend/test/user/test_nickname_sync.py`。
  **逻辑与验证**：先读同步后人工改名再提交旧对象；验证昵称标记保留、邮箱继续更新、原值不变不重验。
  **覆盖 AC:** AC-04, AC-06, AC-07, AC-22, AC-25, AC-32
  **依赖:** T021

- [x] **T025：资料更新保护参数**（后端 Domain）
  **文件**：`src/backend/bisheng/user/domain/repositories/dsh_profile.py`；`src/backend/bisheng/user/domain/services/user.py`。
  **逻辑与验证**：显式区分同步来源，在用户锁内跳过受保护名称；复用版本事务，保留其他变更。运行 T024。
  **覆盖 AC:** AC-04, AC-06, AC-07, AC-22, AC-25, AC-32
  **依赖:** T024

- [x] **T026：SSO 昵称同步接入**（后端 Domain）
  **文件**：`src/backend/bisheng/sso_sync/domain/services/login_sync_service.py`。
  **逻辑与验证**：不在 attrs 中 trim 或先行覆盖受保护昵称；新/实际新值统一校验，来源身份不清洗。
  **覆盖 AC:** AC-04, AC-06, AC-07, AC-25, AC-32
  **依赖:** T018, T025

- [x] **T027：组合编辑回滚测试先行**（后端测试）
  **文件**：`src/backend/test/department/test_member_nickname_edit.py`。
  **逻辑与验证**：管理员权限、来源、历史 no-op；非法角色/部门及故障注入证明无部分改名，模拟原权限初始化。
  **覆盖 AC:** AC-06, AC-07, AC-19, AC-22, AC-23, AC-24, AC-25
  **依赖:** T021

- [x] **T028：人员编辑与昵称末尾提交**（后端 Domain）
  **文件**：`src/backend/bisheng/user/domain/services/nickname_service.py`；`src/backend/bisheng/department/domain/services/department_service.py`。
  **逻辑与验证**：按已确认调整先校验昵称，完成原所属人员操作后，独立原子提交昵称及审计；请求来源由 department_member endpoint 透传。角色/部门/组的原事务不改。运行 T027。
  **覆盖 AC:** AC-06, AC-07, AC-19, AC-22, AC-23, AC-24, AC-25
  **依赖:** T027

- [x] **T029：工作区依赖接线**（前端 Platform）
  **文件**：`src/frontend/platform/package.json`；`src/frontend/client/package.json`。
  **逻辑与验证**：两端显式依赖 @bisheng/identity；pnpm 仅更新对应工作区锁记录并保留既有可选 canvas 隔离。
  **覆盖 AC:** AC-04, AC-28, AC-31
  **依赖:** T007

- [x] **T030：注册共享规则与问号**（前端 Platform）
  **文件**：`src/frontend/platform/src/pages/LoginPage/registrationRules.ts`；`src/frontend/platform/src/pages/LoginPage/RegistrationForm.tsx`。
  **逻辑与验证**：薄适配共享错误码；保持 320/medium、两项密码强度和显隐；问号支持悬浮/焦点及点击展开，原 F010 测试回归。
  **覆盖 AC:** AC-02, AC-03, AC-04, AC-05, AC-27, AC-28, AC-29, AC-30, AC-31
  **依赖:** T029

- [x] **T031：创建本地人员页面**（前端 Platform）
  **文件**：`src/frontend/platform/src/pages/DepartmentPage/components/CreateLocalMemberDialog.tsx`；`src/frontend/platform/src/pages/DepartmentPage/components/IdentityDialogs.test.tsx`。
  **逻辑与验证**：独立账号/昵称、规则和错误、空白过滤、密码显隐、防重复；保留角色及完整账号结果。
  **覆盖 AC:** AC-01, AC-02, AC-03, AC-04, AC-05, AC-20, AC-23, AC-27, AC-29, AC-31
  **依赖:** T015, T029

- [x] **T032：后台编辑昵称**（前端 Platform）
  **文件**：`src/frontend/platform/src/pages/DepartmentPage/components/OrganizationMemberEditDialog.tsx`；`src/frontend/platform/src/pages/DepartmentPage/components/IdentityDialogs.test.tsx`。
  **逻辑与验证**：昵称规则及系统内真实改名说明、只读账号；旧值不预清洗，失败保留草稿，沿用来源门禁。
  **覆盖 AC:** AC-01, AC-04, AC-05, AC-06, AC-07, AC-19, AC-22, AC-23, AC-27, AC-31
  **依赖:** T028, T029

- [x] **T033：成员列表与事件**（前端 Platform）
  **文件**：`src/frontend/platform/src/pages/DepartmentPage/components/MemberTableView.tsx`；`src/frontend/platform/src/pages/DepartmentPage/components/MemberTable.test.tsx`。
  **逻辑与验证**：昵称/账号两列和全文、双字段搜索、受权限控制的行点击，行内按钮开关不冒泡；保留并行组织搜索改动。
  **覆盖 AC:** AC-01, AC-21, AC-22, AC-27
  **依赖:** T032

- [x] **T034：兼容创建 UI 与 API**（前端 Platform）
  **文件**：`src/frontend/platform/src/pages/SystemPage/components/CreateUser.tsx`；`src/frontend/platform/src/controllers/API/user.ts`。
  **逻辑与验证**：追踪可达性并接独立账号字段和统一校验，保持现有 API 包装及拒绝处理。
  **覆盖 AC:** AC-01, AC-02, AC-03, AC-04, AC-05, AC-20, AC-26, AC-29, AC-31
  **依赖:** T016, T029

- [x] **T035：当前资料类型与 API**（前端 Client）
  **文件**：`src/frontend/client/src/api/user.ts`；`src/frontend/client/src/types/chat/types.ts`。
  **逻辑与验证**：增加本人改名函数与真实 external_id 类型，不新增 HTTP/store 旁路。
  **覆盖 AC:** AC-16, AC-18, AC-22, AC-23, AC-31
  **依赖:** T023

- [x] **T036：资料映射接线**（前端 Client）
  **文件**：`src/frontend/client/src/api/chat/data-service.ts`；`src/frontend/client/src/api/chat/data-service.identity.test.ts`。
  **逻辑与验证**：在实际 /user/info 映射点保留 external_id，若实际文件位置不同按调用链更新本条路径，禁止昵称兜底成账号。
  **覆盖 AC:** AC-16, AC-22, AC-27
  **依赖:** T035

- [x] **T037：昵称编辑组件与测试**（前端 Client）
  **文件**：`src/frontend/client/src/components/Settings/sections/NicknameEditor.tsx`；`src/frontend/client/src/components/Settings/sections/NicknameEditor.test.tsx`。
  **逻辑与验证**：展开编辑、计数规则、生效说明、取消/Esc、失败重试；成功更新现有 query/Recoil 用户，禁止新 atom。
  **覆盖 AC:** AC-04, AC-05, AC-06, AC-07, AC-17, AC-18, AC-22, AC-23, AC-27, AC-31
  **依赖:** T029, T035

- [x] **T038：个人账号页面**（前端 Client）
  **文件**：`src/frontend/client/src/components/Settings/sections/AccountSection.tsx`；`src/frontend/client/src/pages/settings/sections/AccountPane.tsx`。
  **逻辑与验证**：默认查看昵称/只读真实账号，接编辑器，账号提示不可修改；保留头像、密码及其他既有功能。
  **覆盖 AC:** AC-01, AC-16, AC-17, AC-22, AC-27
  **依赖:** T036, T037

- [x] **T039：桌面共用入口与回归**（前端 Client）
  **文件**：`src/frontend/client/src/pages/settings/sections/DesktopSettingsPane.tsx`；`src/frontend/client/src/pages/settings/sections/AccountPane.test.tsx`。
  **逻辑与验证**：向共用 AccountSection 传真实账号，桌面与网页行为一致，回归原设置路由。
  **覆盖 AC:** AC-16, AC-17, AC-22, AC-27
  **依赖:** T038

- [x] **T040：平台中文与英文**（前端 Platform）
  **文件**：`src/frontend/platform/public/locales/zh-Hans/bs.json`；`src/frontend/platform/public/locales/en-US/bs.json`。
  **逻辑与验证**：新增 accountIdentity 嵌套键，相关用户名显示为昵称、人员 ID 显示为账号，保留内部 ID 标签。
  **覆盖 AC:** AC-01, AC-19, AC-20, AC-21, AC-27, AC-28, AC-29, AC-31
  **依赖:** T030, T031, T032, T033, T034

- [x] **T041：平台日文及共享中文错误**（前端 Platform）
  **文件**：`src/frontend/platform/public/locales/ja/bs.json`；`src/frontend/packages/locales/src/api_errors/zh-Hans.json`。
  **逻辑与验证**：三语语义一致，错误来源仅共享 api_errors。
  **覆盖 AC:** AC-01, AC-27, AC-31
  **依赖:** T040

- [x] **T042：共享英文与日文错误**（前端共享）
  **文件**：`src/frontend/packages/locales/src/api_errors/en.json`；`src/frontend/packages/locales/src/api_errors/ja.json`。
  **逻辑与验证**：增加 10612～10615 并生成两端产物，禁止手改生成 JSON。
  **覆盖 AC:** AC-01, AC-31
  **依赖:** T041

- [x] **T043：Client 中文与英文**（前端 Client）
  **文件**：`src/frontend/client/src/locales/zh-Hans/translation.json`；`src/frontend/client/src/locales/en/translation.json`。
  **逻辑与验证**：在实际 client locale 源新增嵌套 accountIdentity 键；沿用原 flat key，不扩展 flat keys。实际扩展名以当前源核对。
  **覆盖 AC:** AC-01, AC-16, AC-17, AC-22, AC-23, AC-27, AC-31
  **依赖:** T037, T038

- [x] **T044：Client 日文及回归**（前端 Client）
  **文件**：`src/frontend/client/src/locales/ja/translation.json`；`src/frontend/client/src/components/Settings/sections/AccountSection.test.tsx`。
  **逻辑与验证**：补齐日语并测试当前账号展示、只读/编辑切换和失败状态。实际 locale 源核对后更新路径。
  **覆盖 AC:** AC-01, AC-16, AC-17, AC-22, AC-23, AC-27, AC-31
  **依赖:** T043

- [x] **T045：资料刷新及协议回归**（前端测试）
  **文件**：`src/frontend/platform/src/hooks/useCurrentIdentityRefresh.test.tsx`；`src/frontend/client/src/api/user.identity.test.ts`。
  **逻辑与验证**：测试聚焦读取、匿名不请求、身份不符拒绝和本人改名协议异常。
  **覆盖 AC:** AC-16, AC-22, AC-23, AC-31
  **依赖:** T035, T038

- [x] **T046：平台资料聚焦刷新**（前端 Platform）
  **文件**：`src/frontend/platform/src/hooks/useCurrentIdentityRefresh.ts`；`src/frontend/platform/src/contexts/userContext.tsx`。
  **逻辑与验证**：复用登录资料，在聚焦时读取最新昵称；不覆盖其他身份及权限状态。
  **覆盖 AC:** AC-22, AC-23
  **依赖:** T045

- [x] **T047：Client 聚焦与昵称首字**（前端 Client）
  **文件**：`src/frontend/client/src/hooks/queries/auth/queries.ts`；`src/frontend/client/src/components/ui/Avatar.tsx`。
  **逻辑与验证**：沿用现有用户查询聚焦刷新；头像首字按 Unicode 码点读取，不切断补充平面字符。
  **覆盖 AC:** AC-04, AC-22, AC-27
  **依赖:** T039, T045

- [x] **T048：兼容适配与双库验证入口**（后端测试）
  **文件**：`src/backend/test/user/test_legacy_identity_adapters.py`；`src/backend/test/user/test_account_identity_dual_db.py`。
  **逻辑与验证**：验证旧 DAO 不绕过新规则、原文账号检索及范围；编写仅接受专用空测试库的 MySQL/DM8 并发测试。真实双库未配置时明确跳过，执行结果另记。
  **覆盖 AC:** AC-08, AC-09, AC-10, AC-14, AC-21, AC-26, AC-32
  **依赖:** T009, T014

- [x] **T049：原有注册与 SSO 回归接线**（后端测试）
  **文件**：`src/backend/test/user/test_first_registration_admin.py`；`src/backend/test/sso/test_sso_login_sync_service.py`。
  **逻辑与验证**：沿用首次管理员、后续默认角色和同步来源语义，更新服务边界 mock；原有失败必须与 HEAD 对比，不计为本功能通过。
  **覆盖 AC:** AC-15, AC-25, AC-26
  **依赖:** T014, T018

- [x] **T050：质量检查与标签调用链**（验证）
  **文件**：`features/v3.1.0-beta1/011-account-nickname/verification.md`。
  **逻辑与验证**：运行相关后端/前端测试、根 lint/typecheck/check-i18n、迁移单头、架构 guard 和 UI优化检测；逐个核实名称、搜索及现有导出调用，记录范围与结果。
  **覆盖 AC:** AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32
  **依赖:** T011, T014, T015, T016, T026, T028, T034, T039, T042, T044, T046, T047, T048, T049

- [ ] **T051：API E2E**（后端测试）
  **文件**：`src/backend/test/e2e/test_e2e_account_nickname.py`。
  **逻辑与验证**：复用 e2e helpers，隔离合成数据前缀/租户，JWT 认证、允许拒绝配对、envelope/具体错误码和 GET 最终状态；不写公司真实用户。
  **覆盖 AC:** AC-04, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-18, AC-19, AC-22, AC-23, AC-24, AC-25, AC-26, AC-29, AC-31, AC-32
  **依赖:** T050

- [x] **T052：浏览器交互 E2E**（前端测试）
  **文件**：`features/v3.1.0-beta1/011-account-nickname/verification.md`。
  **逻辑与验证**：按参考用例对两端真实组件页面执行输入/粘贴/键盘/规则/显隐/保存失败/列表事件验证，保存截图及断言，标明 fixture 与公司联调边界。
  **覆盖 AC:** AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-16, AC-17, AC-19, AC-20, AC-21, AC-22, AC-23, AC-27, AC-28, AC-29, AC-30, AC-31
  **依赖:** T050

- [ ] **T053：目标环境验收后的发布审查**（交付）
  **文件**：`features/v3.1.0-beta1/011-account-nickname/upgrade.md`；`features/v3.1.0-beta1/011-account-nickname/design.md`。
  **逻辑与验证**：本地代码审查及升级说明已完成。待 T051 和双库实测通过后，复核实际构建、停写升级与回退条件，再完成发布审查；不自动部署共享服务。
  **覆盖 AC:** AC-08, AC-09, AC-10, AC-14, AC-22, AC-24, AC-25, AC-32
  **依赖:** T051, T052

## 实际偏差记录

用户已明确回复「采用建议，聚焦账号昵称」。后台组合编辑按 design-adjustment.md 完成接入与故障回归；保留一个保存按钮。

已补充可达旧 SSO 的识别名称保留、当前部门账号检索、两端资料聚焦刷新及验证入口，技术合同见 design.md。任务粒度由 48 调整为 53，覆盖目标不扩展。T051、T053 保持未完成：目标环境 HTTP E2E 及发布审查不计为本地通过；当前证据和跳过项见 verification.md。

T049 的扩展回归有两项既有 SSO 部门授权断言失败，已在 HEAD 源码与原测试中复现；该结果不记为通过。
