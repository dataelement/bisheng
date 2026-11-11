# F118 历史失效状态兼容增量审查

基线24b5f2153a；2026-11-11。沿用用户已确认的保留原失效配置、不可用状态和权限边界原则。范围为现有全FAILED无主版本链、退役改绑历史和原跨租户空间引用，不新增业务权限。

| 维度 | 结论 | 证据 |
| --- | --- | --- |
| Boundary Conditions | PASS | 无主链限已有type3、非空、唯一编号、NULL指针/零主标志、全FAILED；普通转换/成功文件坏链仍拒绝。历史行要求原模型Grant及已移至不同Grant的同一assignee、严格历史版本上界、全canonical指纹闭合。 |
| Permission & Auth | PASS | RETIRED历史不加入ACTIVE编译；跨租户空间实际owner保留、invalid_scope/is_valid=false。新建、复制、预览、运行拒绝，Owner查询不放宽。跨租户文件仍拒绝。 |
| Concurrency Safety | PASS | 绑定读取仅原来源/版本，明确ID+owner加锁，所有空间数值顺序后文件；源/目标事务与原版本围栏不变，续跑仍用冻结原基线。 |
| Information Leakage | PASS | 读Owner只查id/tenant/type等标量事实，无凭据或外国业务配置输出，无新HTTP端点。 |
| Test Coverage | PASS_WITH_WARNINGS | 新增M2/M3/M4及续跑覆盖、原生读写Owner和反例。77项定向及2项跨租户正式全链已通过；扩展结果追加现场报告。SQLite不代表DM8/MySQL物理锁调度。 |
| Code Style | PASS | Ruff、diff-check和全部12个变更Python的arch-guard通过。 |
| Docs Sync | PASS | spec/design/release-contract/tasks及八列QA158–160同步，保留未执行现场验收边界。 |

无主链不生成修复命令，不选择主版本或创建重复V1；文档/版本/物理文件保持原样，仍属业务异常待人工修复。RETIRED审计行只在命名空间确需变化时转换类型及tuple指纹，原行ID、来源版本、状态和操作记录保持。M4知识目标合法0→3变化按实际目标owner查已冻结转换命令，其余事实漂移继续阻断。

Overall: PASS_WITH_WARNINGS。本增量不代表全F118端到端验收完成；真实116升级、访问恢复与物理绑定核验结果另记。

退役历史补充：旧Grant可能仍被其他主体使用，当前assignee也可能在新Grant继续ACTIVE；这不使原RETIRED贡献复活。只核对同一来源确已改绑到不同Grant、历史版本严格更小、旧模型及全canonical身份指纹，原ACTIVE编译仍必须完全闭合。
