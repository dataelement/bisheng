# F061：按文件分类自动移动到公共知识空间

## 状态

- Status: `implemented`
- Date: `2026-07-17`
- Detailed requirements: [requirements.md](./requirements.md)
- Detailed design: [design.md](./design.md)
- Implementation tasks: [tasks.md](./tasks.md)
- Verification: [verification.md](./verification.md)（真实环境验证待执行）

## 目标

重写 `move_knowledge_space_files.py` 的选择和编排逻辑。执行者重复传入多个来源知识空间 ID 后，脚本扫描全部 `SUCCESS` 普通文件，根据门户一级、二级分类的 label，分别唯一匹配公共知识空间名称和其根目录直属文件夹名称。

## 核心契约

1. 一级或二级分类缺失、分类配置不存在、空间/目录没有唯一命中时跳过。
2. 目标目录同名、目标空间相同 MD5、向量模型不一致时跳过。
3. 版本链只有全部成员位于本次来源范围、分类完整且路由一致时才整体迁移，并保留版本号和主版本。
4. 目标文件所有者改为目标空间所有者；来源权限不复制，只写目标 owner/parent 必要关系。
5. 默认 dry-run，`--apply` 才写入；写入采用“复制 → 校验 → 删除来源”，失败执行补偿并记录残留。
6. 当前部署未启用多租户，本功能不引入跨租户语义。
7. 来源工件快照和预览复制通过项目统一 `get_minio_storage_sync()` 获取 MinIO 客户端；REQ-007 已修复首次真实 apply 暴露的旧入口调用错误。
8. 版本链目标无法解析时保留分类上下文，并在 `error` 中输出底层 route reason；兼容保留 `version_chain_target_unresolved`。
9. 名称精确匹配前忽略 `U+200B` 和 `U+FEFF`，其他字符、唯一性和直属目录规则保持不变。
10. 目标标签以复制前保存的来源快照为唯一来源并精确替换；不一致错误输出来源和目标标签 ID。

## 交付边界

- 修改范围限定为 F061 规格、移动脚本、定向测试和脚本 README。
- 不修改 schema、不新增依赖、不创建目标空间/目录、不重新解析不同模型文件。
- 不迁移收藏、分享链接和其他旧文件 ID 引用。
- 不对真实业务环境自动执行 `--apply`。

## 验收摘要

- 多来源 CLI、分类路由、冲突跳过、版本链整体迁移、目标 owner/权限、dry-run、报告和补偿均有自动化测试。
- Ruff、Python 编译、脚本 `--help`、定向 pytest、既有 copy worker 回归与 `git diff --check` 通过。
- 真实业务 dry-run/apply 作为人工验证项，在用户提供 IDs 和运行授权前不执行。
