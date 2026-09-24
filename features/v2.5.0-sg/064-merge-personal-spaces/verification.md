# 本地验证记录

日期: 2026-09-09。状态: LOCAL_PASS; 真实环境 E2E: MANUAL_REQUIRED。

## 实际执行

运行目录 src/backend, 复用已有 .venv Python 3.10.19。未安装依赖或修改运行时配置。

1. 首批回归先出现 3 个预期失败: 根目录 folder=None 引发属性错误, 新合并模块尚不存在; 实现后 3 项通过。
2. 新脚本扩展至 32 项, 全部通过。
3. 三脚本联合回归首次 218 passed / 1 failed: 测试环境预替换 User 模块导致 SQL 构造收到 MagicMock。仅测试中使用最小映射表替身解决, 未修改生产查询绕过问题。
4. `.venv/bin/python -m pytest test/scripts/test_merge_personal_knowledge_spaces.py test/scripts/test_move_department_files_to_personal.py test/scripts/test_move_knowledge_space_files.py -q --tb=short`: **219 passed**, 3.17 秒。包括当时新脚本 40 项及已有两脚本 179 项。
5. 增加中断用例, 生产代码未再变更。`.venv/bin/python -m pytest test/scripts/test_merge_personal_knowledge_spaces.py -q --tb=short`: **41 passed**, 2.68 秒。复用第 4 项原脚本证据, 去重后共 220 项相关用例。
6. `.venv/bin/ruff check scripts/merge_personal_knowledge_spaces.py scripts/move_department_files_to_personal.py scripts/move_knowledge_space_files.py test/scripts/test_merge_personal_knowledge_spaces.py`: 通过; 最后增加中断用例后再次检查新脚本及新测试通过。
7. `.venv/bin/python -m py_compile scripts/merge_personal_knowledge_spaces.py scripts/move_department_files_to_personal.py scripts/move_knowledge_space_files.py`: 退出 0。
8. `.venv/bin/python scripts/merge_personal_knowledge_spaces.py --help`: 在真实模块导入环境退出 0, 参数正确, 未运行 load/apply。
9. `git diff --check`: 通过。仅修改三脚本相关落点和 README, 保留当前工作区其他改动。

测试中的第三方依赖弃用警告未影响结果。未用只读检查替代行为验证。

## 验收映射

| 验收 | 主要证据 |
|---|---|
| AC-01 | 默认名称、收藏/部门/租户/失效用户排除; 最小 ID 归并; loader 补空库所有者 |
| AC-02 | 根文件真实空间父权限; 嵌套目录及空目录执行; 完整版本图保留; 按库主归属 |
| AC-03 | 三库顺序覆盖目标原有文件; 迁入版本链被后续同名文件整体覆盖; 原脚本冲突保护回归 |
| AC-04 | 非成功文件保留; 断链/目录混入版本/审批/外部引用拒绝; 复制、权限、验证、来源删除、覆盖失败注入 |
| AC-05 | 空库删除; 业务 delete_space(force=True) 调用及残留检查; 新增文件/孤儿文档/目录丢失或移动/迁入文件丢失/索引共用/归并目标变化门禁 |
| AC-06 | 预览不初始化写入; JSONL 落盘失败阻断来源删除; 中断不删除旧库并保留 pending; 成功重跑无重复组 |

## 未验证及上线边界

SQL/迁移编排使用 ORM 与内存替身, 真实迁移底座被调用, 外部复制、索引、标签、权限操作由替身隔离。MySQL/DM8、MinIO、Milvus/ES、OpenFGA 组合环境未执行预览或 apply, 不能认定生产已合并或跨存储 E2E 通过。macOS 未安装 DM8 驱动。

部署需携带新脚本及同目录的 move_department_files_to_personal.py、move_knowledge_space_files.py、shougang_clean_personal_spaces.py 匹配版本。先备份, 在停写维护窗口按单用户 preview/apply 验证根目录、目录树、下载、检索、权限及旧库残留, 然后处理其余用户。发现 partial failure 时先核查 JSONL, 不盲目重跑。

覆盖会永久删除旧目标完整版本链, 删除旧库不可仅靠 JSONL 一键回滚。completed_with_skips 的用户可能仍有重复库, 应根据 retained/skipped 原因单独处理。未改在线协议、未部署、未提交或推送。

## 2026-09-09 旧容器模块兼容修复

用户提供的 19:31:15 日志显示 run → Backend.load 在导入 shared_space_storage 时中止, ModuleNotFoundError 的缺失模块名为 bisheng.knowledge.rag.shared_space_storage。发生在计划生成及 apply 之前; 此次运行没有开始迁移。前面的 Pydantic warning 不是本次中止原因。

新脚本曾直接要求本地新版共享存储模块, 旧容器不存在该文件。新增 uses_shared_storage: 仅该模块本身不存在时返回 False, 使用现有保守的索引/集合共用检查, 不放宽删库条件。模块内部缺依赖、路由解析异常继续抛出。无需单独部署新版共享存储业务模块。

新增兼容行为测试先得到 5 个失败, 实现后 `.venv/bin/python -m pytest test/scripts/test_merge_personal_knowledge_spaces.py -q --tb=short` 得到 **47 passed**, 2.88 秒。包括真实 import_module 在 sys.modules 缺模块场景下运行完整 Backend.load、旧部署共用集合拒绝删除、新版路由开启/关闭、内部导入与运行异常不吞掉。Ruff、py_compile、git diff --check 通过。

本轮仅修复合并脚本、相应测试和使用记录; 尚未替换用户容器中的脚本或重新执行容器预览。此修复证明已知缺模块路径可兼容, 不代表其他版本差异或真实迁移 E2E 已验证。

## 2026-09-09 脚本混装检查与部署包

用户 19:43:24 日志: build_plan 构造 Candidate 时不接受 personal_space_candidate_ids。Candidate 来自 move_department_files_to_personal.py, 本地该字段存在; 说明容器依赖脚本与合并脚本契约不一致, 仍未进入 apply。不能仅删除该字段, 还依赖同名覆盖能力、plan_for_snapshot 复查和根目录底座支持。

两份迁移依赖新增 PERSONAL_SPACE_MERGE_API_VERSION=1, 合并脚本在 run 最开始检查标记, 旧版/混装明确中止并列出需成套更新的脚本。新增两项测试证明依赖不匹配时没有调用 backend.load, 未生成报告或操作文件。

三脚本联合回归 **228 passed**, 3.05 秒; Ruff 和四脚本 py_compile 通过。已打包四脚本、SHA256SUMS 和 DEPLOY.md, 逐个读回校验压缩内容与源字节一致。部署包只含指定维护脚本和说明, 不含业务配置。

脚本包: /var/folders/06/935ggv0j2259kmb0t_3nvhpc0000gn/T/bisheng-personal-space-merge-b68xae7q/personal-space-merge-scripts.tar.gz。

未向容器上传或执行。真实旧部署的其他版本差异仍需通过预览及维护窗口单用户验证确认。

## 2026-09-09 两个业务入口解除依赖

用户报告容器缺少 move_department_files_to_personal 并明确要求两个业务脚本不要互相引用。合并脚本现已内置原本依赖的 Snapshot/Candidate、目标冲突检测、目录迁移、复制复查、覆盖与失败补偿、数据库读取和审计逻辑; 去掉对部门迁移和个人库清理脚本的导入, 只依赖原通用底座 move_knowledge_space_files.py。合并不创建新目标库, 缺少目标直接拒绝。

AST 比对确认 12 个数据结构/函数及除规划入口、目标库检查外的原 Backend 方法与此前验证的实现一致。新脚本测试夹具也解除对部门脚本测试模块的依赖, 直接测试本地实现。拆分测试导入时发生过缩进错误, 已修复, 未改业务流程。

`.venv/bin/python -m pytest test/scripts/test_merge_personal_knowledge_spaces.py -q --tb=short`: **49 passed**, 2.75 秒。包括禁用两个业务脚本导入后以 runpy 加载合并脚本并构造完整计划; 同名覆盖、版本链、空目录、失败保护、删库复查等通过。真实 Python 模块环境中禁止这两个脚本导入后执行 --help 退出 0。Ruff、py_compile、git diff --check 通过。

新部署包只有合并脚本、通用底座、SHA256SUMS 和 DEPLOY.md, 逐个读回验证归档内容。之前四文件包仅保留为历史记录, 当前部署应使用新版两文件包。仍未部署到用户容器或执行业务数据迁移。

## 2026-09-09 最终单文件交付

用户进一步明确“脚本要独立”。现已将通用底座所需的 65 个类型/函数/常量内置至 merge_personal_knowledge_spaces.py, 不包含原底座的 CLI 或无关批量规划入口。通过 AST 依赖闭包提取并逐个 AST 比对, 65 个内置定义与原已验证实现一致。删除外部脚本导入及依赖版本检查, 没有用读取文件、动态执行或隐藏脚本加载规避要求。

测试只调用单文件内置定义。`.venv/bin/python -m pytest test/scripts/test_merge_personal_knowledge_spaces.py -q --tb=short`: **48 passed**, 2.86 秒; 相比前一版移除了已不适用的底座版本检查测试。单文件计划生成测试禁止导入整个 scripts 包后通过。真实 Python 进程将脚本复制到空临时目录, 确认目录内只有此文件, 并禁止导入所有 scripts 模块, 执行 --help 退出 0。Ruff、py_compile、git diff --check 通过。

交付只需更新 /app/scripts/merge_personal_knowledge_spaces.py。原四文件/两文件包均被替代, 不再需要部署其他维护脚本。仍依赖容器已有 Bisheng 业务模块、第三方库和配置, 不是脱离应用环境运行的程序。未部署或真实 apply, 不声称用户环境迁移已完成。

## 2026-09-09 性能修复

此前全租户文件/文档加载、逐单元全局重规划、每候选重建引用/版本映射与每单元整份 JSON 写盘为代码确认的开销。按用户确认进行单文件内局部优化, 未修改数据库表、索引、业务服务或依赖环境。

现先读元数据找重复用户, --user-id 下推数据库; 再按用户读取重复默认库。迁移前/删除前复查只读取当前来源、目标目录和同名文件并展开完整版本链, 外部引用另外按关联 ID 查询。迁入结果按新文件 ID 获取, 删库后直接按 source ID 查残留, 不依赖重复组仍存在。PlanningIndex 每次规划只遍历原文件列表一次; 复查只处理指定 unit_id; 汇总报告在每 20 单元/10 秒或阶段终止保存, 删除步骤 JSONL 仍同步 fsync。

验证:

- `.venv/bin/python -m pytest test/scripts/test_merge_personal_knowledge_spaces.py test/scripts/test_merge_personal_spaces_performance.py -q --tb=short`: **57 passed**, 3.22 秒。
- 新增 9 项性能与安全回归, 包含 10/300 单元下全量列表遍历次数恒定、25 个文件仅 4 次汇总保存、metadata-only 不查文件或版本、SQLite 实际执行用户及单元范围查询、外部引用 ID 保护、跨用户共用存储保护、组消失后仍检出孤儿文件/文档、新增版本成员导致指纹变化。
- SQLite 测试克隆表定义, 仅在克隆表上替换不支持的 MySQL ON UPDATE 默认值, 不修改生产模型。原测试 model_copy 对象保留旧 ORM state, 通过重建测试对象解决插入失败。User 使用独立最小映射表, 审批返回空替身, 外部存储操作仍为替身; 不是生产数据库 E2E。
- 同一进程、相同模拟 Snapshot 含 8,300 文件(300 待迁、8,000 无关文件), 旧脚本 build_plan **3.0211 秒**, 新脚本 **0.0174 秒**, 两者均产出 300 单元。仅对比 Python 规划, 不代表数据库、MinIO/索引复制的生产整体提速。
- Ruff、py_compile、git diff --check 通过; 最后只追加了扫描进度输出和文档。独立脚本导入隔离仍在回归集内通过。

未执行用户容器的预览/apply, 未测量生产 CPU/内存峰值及 SQL 执行计划。数据库实际索引与数据分布影响查询速度; 所有拟迁候选和审计计划仍需保存在报告中, 不承诺任意数据规模恒定内存。文件复制/索引验证的实际 IO 开销保持原行为。

## 2026-09-10 覆盖索引复核与失败停止修复

用户提供 2026-09-09 21:04 apply 日志: 来源 document:18214 在覆盖旧目标 document:35695 时失败, target_file_id=126739, 删除后 Milvus=0、ES=367。代码确认业务 delete_vector_files 的 ES delete_by_query 未传 refresh, 原脚本立即计数存在可见性延迟误报的可能; 缺少该次 delete_by_query 响应及刷新后的实际计数, 尚不能确认生产 367 条全部为延迟。另确认旧版 attempt 收集异常后仍继续清理对象、标签、权限、版本图和文件记录, 日志中的后续 OpenFGA 调用与此路径一致。

单文件脚本在 ES 计数非零时刷新目标索引并仅复查 ES, 避免重复扫描 Milvus; 刷新分片失败或刷新后仍有残留均中止。计数索引名与业务删除保持 index_name/collection_name 回退一致。清理先检查整个旧版本链的索引, 每一步失败立即返回步骤报告, 交由原有保护逻辑保留来源及新副本并停止迁移。不会恢复此前已删除的旧目标数据。

新增 5 项回归调用真实 delete_overwrite_target 方法, 外部存储用替身模拟: 可见性延迟、真实残留、刷新分片失败、对象删除失败、多版本第二个索引失败。修复前 5 项失败, 修复后通过。联合命令 `.venv/bin/python -m pytest test/scripts/test_merge_personal_knowledge_spaces.py test/scripts/test_merge_personal_spaces_performance.py test/scripts/test_merge_personal_spaces_overwrite_cleanup.py -q --tb=short` 得到 **62 passed**, 18 warnings, 3.30 秒。警告来自已有第三方依赖及测试模型枚举序列化。

未部署、未执行生产迁移或清理, 未验证真实 ES 刷新。来源未进入删除与新副本保留是代码路径判断; 旧目标实际清理程度需核对本次 JSON/JSONL 与线上状态后决定恢复方式, 不建议直接重复 apply。

### 2026-09-10 10:27 刷新请求超时

新日志在 `_refresh_es_after_delete` 的 indices.refresh 请求处报 ConnectionTimeout, urllib3 read timeout 约 10 秒, ES 节点为 10.171.0.59:9200。涉及来源 document:18214、旧目标 document:35697/file:126741。日志已运行 fail-fast 版本, 本次旧目标索引步骤失败后不会继续清理其对象/权限/数据库记录; 索引删除可能已完成, 不能把超时解释成服务端未执行或完整回滚。此次慢请求本身无法证明使用了共享索引。

仅为维护刷新调用 `.options(request_timeout=60, max_retries=0, retry_on_timeout=False)`, 不改变全局客户端或业务删除接口。保留超时后停止规则并增加索引名及超时上限日志。新增超时失败路径和请求参数断言; 修改前 5 failed/1 passed, 修改后上述三文件联合回归 **63 passed**, 18 warnings, 3.31 秒。Ruff check/format 检查通过。未部署或访问线上 ES, 延长等待仅缓解 10 秒预算不足, 未确认生产慢刷新的负载/磁盘/网络原因。

### 2026-09-10 原记录迁移验收

相关回归 102 项联合通过，新增整批 SQLite 用例单独通过，合计 103 项：原文件 ID/对象/版本链保留、两索引回退、外部异常降级、覆盖与事务回滚、空库删除保护、最终待解析清单。Ruff/编译通过。容器独立脚本更新及 --help 验证通过，SHA256 54f9260249fd8e2a5f03e89d701d5a1f7c627e05f2ed999ed08be616eaeb5748，备份后缀 20260910-122255。容器只读核验 126186：Milvus 0，ES 58 条正文无向量，新版 ES 读取可用。未执行真实 apply；MySQL/DM8 事务、索引写入及业务重新解析端到端仍为 MANUAL_REQUIRED。完整证据见 docs/个人知识库合并脚本ES超时现场分析-20260910.md 最新节。
