# 文件所属组织验证记录

- Feature ID: `082-file-belonging-organization`
- Date: `2026-10-23`
- Overall: `LOCAL_VERIFIED / MANUAL_REQUIRED`
- 范围：本地代码、隔离 SQLite、外部接口替身；没有提交、推送、部署、执行环境迁移或历史批量回填。

## 结果与验收映射

| Acceptance | 结果 | 证据 |
|---|---|---|
| AC-01 | 本地 PASS；真实数据库迁移 MANUAL_REQUIRED | E-001：重复升级、历史行保持空、回退不影响其他列，MySQL与DM兼容通用方言列编译 |
| AC-02 | PASS | E-001：同步/异步真实仓储唯一主组织解析；普通上传写回；Filelib使用责任人2而非调用人1 |
| AC-03 | PASS | E-001：科室、团队发布准备时不改组织，成功后更新；激活提交失败回滚 |
| AC-04 | PASS | E-001：已有版本、源库发布入口、分享入口同步；发布为已有文档新版本仍统一；重复回调幂等；版本关联及更正继承 |
| AC-05 | PASS | E-001：非个人源库和部门目标不重算；切换主版本及分享相关回归；历史科室层级标记兼容 |
| AC-06 | 本地 PASS；真实租户隔离集成 MANUAL_REQUIRED | E-001：跨租户组织留空、不任意选择附属组织；E-002：代码边界检查，无前端/权限/索引字段或历史扫描改动 |

## E-001 最终相关回归

本节为存量脚本扩展前的验证记录；当前代码的最新证据以 E-004 为准。

工作目录 `src/backend`，使用现有 `.venv/bin/python`，未安装依赖。最终代码状态包含本任务全部业务修改，另有工作区既有看板改动但未纳入测试范围。

```bash
.venv/bin/python -m pytest \
  test/knowledge/test_file_belonging_organization.py \
  test/knowledge/test_knowledge_file_original_origin_upload.py \
  test/knowledge/test_knowledge_version_service_link.py \
  test/knowledge/test_knowledge_version_service_set_primary.py \
  test/knowledge/test_knowledge_document_distribution_publish.py \
  test/knowledge/test_knowledge_document_distribution_share.py \
  test/knowledge/test_knowledge_document_distribution_attach_publish.py \
  test/open_endpoints/test_filelib_sync_from_staged_file.py \
  test/open_endpoints/test_filelib_sync.py \
  test/open_endpoints/test_filelib_sync_audit.py \
  test/open_endpoints/test_filelib_sync_version_link.py \
  test/open_endpoints/test_filelib_sync_token_rule.py \
  test/open_endpoints/test_filelib_sync_folder_target.py \
  test/open_endpoints/test_inspection_standard_sync_service.py \
  test/open_endpoints/test_inspection_standard_sync_bulk.py \
  -m 'not slow' \
  -k 'not (test_unbound_business_domain_is_rejected or test_business_domain_requires_portal_space_and_code_bindings or test_production_router_reaches_sync_handler_for_missing_params or test_write_upload_success_calls_ainsert_v2)' \
  -q --disable-warnings --tb=short
```

结果：**198 passed, 13 deselected**，exit 0。13项为9项慢测试和以下4项已确认的基线失败。最终输出 `/tmp/file-org-final.log`。

新增组织归属用例16项，使用真实SQLite仓储及原发布服务；外部权限写入使用既有替身。字段发布更新不在审批准备阶段执行，与成功激活处于同一数据库事务。Filelib编排单元测试显式使用组织查询替身，组织解析本身由同步/异步仓储集成用例证明，不能将接口替身视为真实组织服务验收。

## E-002 静态及迁移链

- 对本任务24个新增/修改Python文件执行 `py_compile` 和 `scripts/arch-guard.sh`：通过，无架构违规。
- Ruff新文件检查及既有文件相对HEAD按诊断码和信息比较：无新增诊断；既有诊断未整文件修复。
- `git diff --check`：通过。
- `.venv/bin/alembic heads`：唯一head为 `f118_file_belonging_organization`。该命令只检查迁移链，未连接环境数据库执行upgrade。
- 可空整数列通过MySQL方言及名称为dm的通用方言编译；通用方言不等于真实DM8驱动或数据库验收。
- 无前端行为变化，不运行无关前端构建或全项目测试。

## E-003 已知基线失败与环境限制

以下4项在扩展回归中失败；在独立进程加载 `git show HEAD:src/backend/bisheng/open_endpoints/domain/services/filelib_sync_service.py` 到同名模块后，仅执行这4项，仍全部失败（4 failed，exit 1，`/tmp/file-org-baseline.log`），没有覆盖工作区文件：

1. `test_unbound_business_domain_is_rejected`：既有业务域拒绝断言。
2. `test_business_domain_requires_portal_space_and_code_bindings`：既有业务域绑定断言。
3. `test_production_router_reaches_sync_handler_for_missing_params`：独立真实路由导入进程中的本机SciPy动态库无法加载。
4. `test_write_upload_success_calls_ainsert_v2`：既有审计元数据的责任人名称断言得到None。

未把这些失败标成通过，也未扩大范围更改业务域、审计或安装依赖。慢测试曾在独立扩展批次执行，最终最小回归不要求重跑万级文件性能场景。

曾误选 `test_file_correction_update_lifecycle.py` 与 `test_file_correction_promote_manager.py` 中连接配置开发MySQL的旧用例：夹具创建临时测试数据后，模型读取因环境尚未增加新列而失败。原用例finally负责清理临时记录；未额外读回远端清理结果。该组未作为通过证据，之后停止此类测试，未对该环境执行迁移。纠错继承由本次隔离用例覆盖；真实纠错全流程仍待迁移后验收。

## 环境验收及上线顺序

以下为 `MANUAL_REQUIRED`，本次不执行：

1. 在隔离MySQL/DM8验证迁移：旧行值保持NULL，新列可写；确认对应部署迁移前驱。
2. 先执行经批准的迁移，再更新后端与worker，避免新模型读取尚不存在的列。
3. 普通上传、接口责任人上传各验证一次；无唯一主组织时为空。
4. 个人库分别发布到科室和团队：审批未完成不变，成功后各版本及原库/目标库/分享入口组织一致。
5. 验证发布为已有文档新版本、重复回调、权限失败或事务失败；核对其他发布方向、普通分享及人员调组织不触发重算。
6. 使用真实租户上下文和权限服务核验组织ID不会跨租户写入，组织字段不会授予资源权限。

回退优先只回退代码并保留列和值；删列会丢失新记录的组织事实，需另行确认。历史未发生新上传或指定发布的文件仍为空，没有后台自动回填。

## E-004 存量脚本及门户实际创建结构补充验证

用户明确存量只按当前主版本上传人的当前唯一主组织补齐整文档；不按发布路径、科室绑定或团队创建人回填。新增脚本 `scripts/backfill_knowledge_file_organization.py`，用法见 `src/backend/scripts/README.md`。

- 新增脚本回归11项：只读计划、各版本与分享入口统一补空、普通无版本文件、自身上传人与原始上传人区分、现有值冲突、组织缺失/多主组织、坏链、跨租户及非业务记录排除、计划漂移/改写/错库、不完整计划拒绝、失败事务回滚、日志尾部残片、未确认提交不盲目回退、回退预览与漂移保护、报告0600与独占创建。保持原更新时间及原始上传人字段。
- 上轮测试只覆盖部门/用户组所有者兼容结构，遗漏了门户实际的用户所有者结构。新增两项实际结构用例先复现失败（`/tmp/file-org-portal-red.log`），随后修正：科室取独立绑定表；团队取范围创建人，历史缺失时取知识库创建人。新旧结构均通过；没有改权限或审批规则。
- 最终命令复用 E-001 完整命令，在测试文件列表最前加入 `test/knowledge/test_backfill_file_organization.py`，其余参数和排除策略相同。结果 **211 passed, 13 deselected，exit 0，10.65秒**，输出 `/tmp/file-org-with-backfill-final.log`。13项仍为前述4项基线失败及9项慢测试，未标为通过。
- 对新脚本、新脚本测试、组织原回归、组织服务及仓储实现共5个本轮文件执行 `py_compile`、架构守卫、`ruff check` 和 `ruff format --check`：全部通过。CLI `--help` exit 0；直接 `--tenant-id 1 --apply` 被参数校验拒绝（exit 2），未创建报告或连接数据库。输出中使用的租户1仅为CLI拒绝测试参数。
- 本轮只有隔离SQLite测试和CLI帮助/参数校验，没有连接环境扫描数据、执行回填、迁移或回退。MySQL/DM8真实锁、事务、时间字段及运行环境端到端仍为 `MANUAL_REQUIRED`。

### 运行边界

必须先完成f118字段迁移，再于维护窗口审核计划和执行。计划筛选的是种子，实际展开整份文档；全部受影响ID在报告中。已有非空组织与推导值冲突整组跳过。写入日志需保存在持久化存储；回退只处理已确认提交且未漂移的本次补空值，未确认提交保留未知状态供人工核对。脚本不会停止服务或获得全局维护锁，不应并发运行相关上传、移动、编辑、发布/分享、版本切换或组织同步。
