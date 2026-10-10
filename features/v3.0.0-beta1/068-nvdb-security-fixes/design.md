# Design: NVDB 漏洞修复（F068）

**关联规格**: [spec.md](./spec.md)
**版本**: v3.0.0-beta2

> 本文档是 How 的唯一真相。接手时先读这里。

---

## 0. 调整原则

- 每个漏洞只修根因所在的那一层，另加一道"最后一道门"式的防御（接口层拒绝 + 数据层再校验），不顺手重构周边。
- 不引入新表、新错误码、新对外 API、新前端改动。
- 代码节点 RCE 根因不在本 Feature（用户明确要求另议）。

---

## 1. V1 JWT 密钥（AC-01～05）

**根因**：`Settings.jwt_secret` 在代码里有默认值（2.4 为 `secret`，2.6+ 为 `secret_cF2k…`），且默认部署不覆盖；令牌校验只看 `user_id`，伪造 `user_id=1` 即超管。

**决策 1 — 默认值置空，两个历史值列入黑名单。**
`bisheng/core/config/settings.py` `jwt_secret: str = ""`。新模块 `bisheng/user/domain/services/jwt_secret.py` 持有 `LEGACY_JWT_SECRETS`，命中即视为未配置。

**决策 2 — 未配置时生成一次、存系统配置表。**
`ConfigKeyEnum.JWT_SECRET = "jwt_secret"`，值为 `secrets.token_urlsafe(48)`。选配置表而非本地文件：api / worker / linsight worker 是不同进程甚至不同节点，必须共用同一份；配置表本来就是它们的共同真相源。首次启动多进程竞争插入时靠 `key` 唯一约束，输家捕获 `IntegrityError` 后回读胜者的值。

**决策 3 — 解析顺序与缓存策略。**
`resolve_jwt_secret()`：yaml 值（非黑名单）→ 进程内缓存的生成值 → 读库 / 生成。yaml 值每次实时读、不缓存（读的是内存对象，零成本；也让测试替换 `settings` 后立刻生效），只缓存生成值。`AuthJwt.__init__` 改为调用它；模块内的 DAO / 数据库导入延迟到真正落库时才发生，避免把数据库包拉进早期导入链。

**决策 4 — 影响面。**
只有登录 cookie 走这把密钥。PAT / 开放 API 凭据是库表比对，不受影响。升级后旧 cookie 失效 = 全员重登，写进发版说明。

**坑 1**：`test/tenant/test_tenant_auth.py` 用"模块未导入时才预置 MagicMock"的方式隔离 `config_service`；合跑时拿到的是真实 settings，密钥为空就会去碰库。已加 autouse fixture 钉住密钥。以后新 JWT 测试一律用 `conftest.mock_settings` 或显式 `monkeypatch settings.jwt_secret`。

---

## 2. V2 排序参数 SQL 注入（AC-06～08）

**根因**：`SpaceFileDao.order_field_text()` 把 `order_field` / `order_sort` 原样 f-string 进 `ORDER BY`，`/space/{id}/children` 与 `/space/{id}/search` 直接透传查询参数。

**决策 5 — 两道门。**
- 接口层：`knowledge_space_file.py` 定义 `SpaceFileOrderField = Literal["file_type","file_name","file_size","update_time","create_time"]`、`SpaceFileOrderSort = Literal["asc","desc","ASC","DESC"]`，两个端点的参数改用这两个类型 → FastAPI 对集合外值返回 422。
- 数据层：`order_field_text()` 开头按同一集合校验，不通过抛 `ValueError`。`knowledge_file.py` 里另一处调用同一函数，自动受保护。

取值集合来源：client `SortType` 枚举（file_name / file_type / file_size / update_time）+ 既有 `update_time` 默认排序 + `create_time`（表上有列、语义合理）。大小写两种方向都收，是为了不改前端。

---

## 3. V3 HTML 任意文件读取（AC-09～10）

**根因**：`HTML2MarkdownConverter.convert()` 把源 HTML 所在目录以 `file://` URI 作为 `base_url`，`_download_media_file()` 对 `file` scheme 直接 `shutil.copy`。于是 `file:///etc/passwd` 与相对 `../../etc/passwd`（`urljoin` 后同样落到 `file://`）都能把服务器文件复制进知识库媒体目录，再经对象存储回传。

**决策 6 — 目录围栏而非删分支。**
新增 `_is_local_media_allowed(candidate)`：`candidate.resolve()` 必须位于 `Path(source_html_filepath).resolve().parent` 之下，否则记 warning 并返回 `None`。保留分支是因为"HTML 旁边带一张图"在语义上是合法的（虽然当前上传路径不会产生），删分支收益不大而围栏已足够。`resolve()` 同时处理了符号链接。

**未做**：`http/https` 分支的 SSRF 限制（见 spec 排除项）。

---

## 4. V4 本地路径任意文件读取（AC-11～12）

**根因**：`core/cache/utils.py` 的 `file_download` / `async_file_download` 第一分支——"字符串去掉 `?` 后是个存在的本地文件就直接返回"。微调预置文件接口把请求体里的 `files` 原样传入，再上传到对象存储。

**决策 7 — 在共用工具里修，而不是在微调接口修。**
调用方有 6 处（微调、日常聊天附件、灵思提交文件、知识库预览、开放接口文件库、图片识图）；只堵微调等于留 5 个入口。新增 `_ensure_allowed_local_file(path)`：真实路径必须位于 `CACHE_DIR`（`save_download_file` 的落盘目录）或 `tempfile.gettempdir()` 之下，否则 `ValueError`。同步版有两处本地路径出口（首分支与末尾兜底），都加了。

**为什么这两个根目录**：追了全部调用方，本地路径只可能来自本进程先前的下载落盘；3.0 的上传接口返回的已是对象存储分享链接，前端从不发本地路径。注释里那句"挂载存储卷时可直接读"的场景没有任何代码路径产生，视为未支持。

---

## 5. V5 建应用权限绕过（AC-13～14）

**根因**：`web_menu` 的 `create_app` 只控制前端按钮；`POST /workflow/create` 与 `POST /assistant` 只挂 `@require_quota`。

**决策 8 — 新依赖 `LoginUser.get_app_creator_user`。**
超管直接放行；否则 `assert_effective_web_menu_contains(user_id, "create_app")`（既有方法，含部门管理员合并与孤儿菜单剥离，与登录接口返回给前端的 `web_menu` 同源）。两个创建端点把 `Depends(UserPayload.get_login_user)` 换成它。判定口径与 `platform/.../BuildPage/apps.tsx` 的 `canCreateApp` 完全一致（超管 或 菜单含 create_app；部门管理员不再单独放行——前端已如此）。

**未做**：复制应用、模板创建走的是同两个端点，天然覆盖；`run_once` 对非 code 节点的权限不动。

---

## 6. 测试

| 文件 | 覆盖 |
|------|------|
| `test/user/test_jwt_secret_resolution.py` | 解析顺序、黑名单、缓存策略、落库、首启竞争、代码无默认值 |
| `test/knowledge/test_space_file_order_whitelist.py` | DAO 白名单拒绝注入串；两个端点参数注解为 Literal 别名 |
| `test/knowledge/rag/test_html_media_local_file_guard.py` | 绝对 `file://`、相对穿越、符号链接均不复制；同目录文件仍复制 |
| `test/core/test_file_download_local_guard.py` | 同步 / 异步两版：缓存目录内放行，目录外 / 穿越 / 符号链接 / 带签名参数一律拒绝 |
| `test/api/test_create_app_permission_gate.py` | 依赖三态；两个创建端点确实挂了该依赖 |

复现类验证（用报告里的 PoC 打修复后的环境）放在 tasks.md 的 e2e 项。

---

## 7. 运维与文档

- `docker/bisheng/config/config.yaml` 增加注释掉的 `jwt_secret` 示例与说明。
- `docs/architecture/08-deployment.md` 配置系统一节补 `jwt_secret` 语义；升级 checklist 加 v3.0 条目。
- Release Notes 三条见 spec §4。
