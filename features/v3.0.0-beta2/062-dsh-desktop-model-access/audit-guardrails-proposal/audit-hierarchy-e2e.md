# 父子审计会话嵌套：实施、审查与验证

日期：2026-10-19。开发基线f0b54cdcb，分支feat/3.0.0-dsh-audit。用户已确认规格0.23和设计0.13，并要求功能完成后提交推送。本轮只改bisheng服务端/Platform；没有修改桌面客户端、部署109或读写109历史。

## 已实现

- 请求/会话原归属不变，独立折叠已存的合法来源和父编号；缺失不猜、有效冲突不选第一条。
- 三个可重建SQL读侧表：代次状态、会话节点、祖先路径。每批100，独立事务/租约fencing，影子构建完成再发布；最多保留active/building/一个retired引用，旧游标不可用明确刷新。
- 新树根/直接子/祖先定位管理API，沿用管理员及历史租户/用户授权。模型名称等值、同请求筛选、有界续扫；不对请求表加GROUP BY/DISTINCT或读正文组树。
- Platform父会话中分别展示本会话请求与折叠的子Agent会话，根、子及请求独立分页；只中子保留父路径，摘要未知不冒充0或正常。旧服务端或未准备的目录仍可平铺/查看请求，切换分页方式必须刷新。
- 独立dsh.prepare_audit_tree/dsh.scan_audit_trees和Beat注册，包含终态历史和当前OFF租户。维护命令prepare_dsh_audit_tree.py默认dry-run，显式--apply后按持久标记继续。
- DDL-only迁移唯一head为f062_dsh_audit_tree，前序dsh_audit_groups；新增整表由模型发现创建，旧表仅加列/索引，迁移不回填数据。正文、模型调用、账本、客户端协议及权限规则未改。

## 实际执行结果

| 范围 | 结果与证据边界 |
|---|---|
| 后端审计/模型业务回归 | 246 passed、12 skipped；命令为pytest test/dsh/test_model_audit*.py test/dsh/test_audit_history.py test/dsh/test_projection_worker.py test/dsh/test_model_service.py test/dsh/test_model_runtime.py test/dsh/test_models_api.py test/dsh/test_model_access.py test/dsh/test_model_quota.py test/database/test_alembic_single_head.py -q。跳过项需要显式环境/运行条件，不计为通过 |
| 新增层级定向 | tree、tree_queries、tree_http、tree_worker与迁移head定向共22通过；包含真实后台Service跨事务、旧owner失败不清新租约 |
| 独立本机MySQL | DSH_AUDIT_GROUPS_MYSQL=1 pytest test/dsh/test_model_audit_groups_mysql.py -q通过；实际重复DDL升级、真实事务、根/子查询、EXPLAIN索引候选及既有正文批次回归。仅启动并清理套件独有测试容器/卷；不接业务库 |
| 前端最终相关回归 | ModelAuditTree/Group/Panel三个文件24通过；覆盖折叠无预取、只中子路径、未知汇总、空续扫、重试/过期、迟到响应丢弃、平铺转树时游标刷新 |
| 前端扩大范围 | dsh目录及dshModelAudit API测试较早一次202通过、1个既有License用例失败。失败期望DSH Enterprise License Request，HEAD原英文资源已经是Client Enterprise License Request；相关测试和组件未改，locale仅新增tree字段；不顺手改License |
| 类型/国际化 | 从src/frontend执行pnpm typecheck和pnpm check-i18n全部通过；Platform、Client与file-viewers类型检查均通过，新文案三语键一致 |
| Lint | 本次全部改动TS/TSX定向ESLint通过；全量pnpm lint仍在Platform遇93条既有错误。六个文件均与HEAD无差异：CitationReferencesDrawer(2)、controllers/API/index(63)、controllers/API/license(3)、WorkbenchSensitivePolicy(3)、MessageMarkDown(6)、f067LicenseBannerCopy.test(16)。未增加suppression或修改无关文件 |
| Python/架构/文本 | Ruff、唯一迁移head测试、git diff --check和逐改动文件arch-guard检查；最终结果以提交前实际命令为准 |

后端命令从src/backend执行，解释器使用主检出已安装venv，config复用主检出测试配置。SQLite与合成身份的HTTP验证不代表生产JWT/OpenFGA；MySQL实测不代表DM8。

## 浏览器交互验证

使用当前真实ModelAuditTree/GroupRequests/Card、三语资源和bs-ui组件，独立临时Vite配置及Axios合成适配器；无业务登录、供应商或109请求。原Vite HTML插件会强制注入登录入口，故改用独立配置而不是修改产品配置。验证完已删除临时HTML/TSX/配置并停止本次启动的服务。

- [x] 初始父节点折叠时没有请求列表、子目录或正文读取。
- [x] 点击父节点，仅出现本节点requests和直接children两次元数据读取，子节点仍折叠。
- [x] 聚焦子节点按Enter，aria-expanded变为true，仅增加子节点requests读取；body-access始终0。
- [x] 桌面实际截图核对：父子在同一外卡片内，数量分别标本会话/含子会话，子异常可反映到父分支。
- [x] 375×812、touch/mobile、prefers-reduced-motion=reduce，父子均展开；实际innerWidth和scrollWidth均375，无横向溢出，正文读取仍0。
- [ ] 正式管理页登录、真实DSH账号及109历史数据上线验收，未执行。
- [ ] DM8编译/真库、正式Electron、超大目录压力与构建饥饿、模型P95/RSS，未执行；本机dmSQLAlchemy模块不存在，没有临时安装依赖或宣称DM8已验证。

## AC追溯与审查

| AC | 已验证核心 |
|---|---|
| AC-H01 | 根/子归属、UI折叠，不改请求事实 |
| AC-H02 | 根和子独立分页完整期望集合、多层、32跳边界及继续入口 |
| AC-H03 | 缺父、迟到父、自指、环、不同有效父/来源冲突、跨用户同编号 |
| AC-H04 | 仅子命中路径、所有条件由同一请求满足、精确子编号、预算内未完候选续扫 |
| AC-H05 | 本节点/分支计数、幂等、子异常和未知摘要不标正常 |
| AC-H06 | 管理员允许/普通用户与跨租户拒绝、展开零body-access |
| AC-H07 | 原元数据整理、终态/OFF、后台Service、旧代次与分页方式切换刷新 |
| AC-H08 | 有界批次、持久阶段、租约抢占fencing、构建中变更拒绝混代发布、失败重试 |
| AC-H09 | 过滤变化取消旧子请求、丢弃旧响应、按钮aria、键盘Enter及375px |

L1任务检查：基础设施、Domain/API、Worker、Platform各任务按分层、字段、租户、泄露、前端约定及设计同步检查。领域模型只存元数据；共享tenant_filter仅新增模型发现字符串；独立Worker header校验在获取数据库前，恢复profile_scope。国际化遵循Platform的useTranslation与既有bs-ui，不机械照搬Client的useLocalize或引入新UI库。

L2增量代码审查基线为f0b54cdcb加本轮工作树，不把整个远端main差异冒充本轮改动。七维结论：边界、授权、并发、信息泄漏、核心测试、改动文件风格和设计同步未发现遗留high/medium功能问题；全量存量lint/License失败及正式环境门禁单列，不声称仓库全绿。审查期间修正了重复查询参数检测、旧就绪响应覆盖新状态、平铺游标跨树发布、旧owner失败清新租约和未知摘要时间等问题，均有对应实现/测试或契约回写。

## 发布与回滚

先完成DDL/模型发现及所有写入、Worker进程升级；已有status/name/group准备须先完成。正常后台会独立整理关系；需人工验证进度时：

```bash
cd src/backend
python scripts/prepare_dsh_audit_tree.py --tenant-id 1
python scripts/prepare_dsh_audit_tree.py --tenant-id 1 --apply --max-steps 100
```

本轮没有在109执行这些命令。回滚保留新增列及原始审计，停独立树任务/使用旧平铺入口或旧镜像；不反向合并/删除请求、正文和账本。当前交付边界是功能代码及本机验证完成，可以按用户授权提交推送，不是正式部署验收完成。
