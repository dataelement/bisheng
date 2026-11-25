# 166 删除空间引用提示排查与修复

日期：2026-11-25。基线：beta2 `3525d93349`；集成时保留远端新增的 `6a8b5f13a5`，未改其模型可见范围修复。

## 原因

空间 1 的引用明细已存在：工作流 `b3844644404442bfa993fbf389f3153c`，版本 1（页面 v0），三个节点槽位；另有独立助手一处引用。并非来源未保存或异步索引未同步。

`ReferenceHintRepository.aread` 先读取空间引用，再查询实际归属于该空间的文件引用。后一个 SQL 将整数文件 ID 转为 CHAR(64)，与引用表 target_id 比较。166 连接及转换结果为 `utf8mb4_0900_ai_ci`，target_id 列为 `utf8mb4_unicode_ci`，MySQL 报 1267 Illegal mix of collations。即使没有文件引用，该语句也会报错，导致整份辅助引用提示返回 `reference_check_complete=false`。

实际浏览器修复前响应：业务 `check_complete=true`、`can_execute=true`，引用 `reference_check_complete=false`、source_counts={}，文件和文件夹数 44。页面“无法确认”表示提示查询失败，并非不存在引用。按既有引用提示合同，引用是辅助影响提示，失败不阻止用户决定删除。

## 变更

- `a33b87567b`：比较两侧都转换为 String(64)，统一连接排序规则。继续使用当前文件归属及原权限披露；不改表排序规则、不迁移引用、不把字符串目标强转数值。
- 新回归验证超过 JavaScript 精确整数范围的文件 ID 仍精确匹配，并排除带前导零及后缀的非规范 ID。
- `eb9ef01ae2`：三语 workflow_unlink 文案描述引用影响及移除方法，去除遗留“因此无法删除”的阻断描述，与既有按钮行为一致。

## 验证

- 25 项后端回归通过：deletion_hints、kn_delete_plan、kn_refs。
- Ruff format/check、arch-guard、git diff --check 通过。
- check-i18n 通过；三语 JSON 解析通过，仅修改同一既有文案键。
- 166 真实 MySQL 只读核查确认两种排序规则，并验证修正后的文件归属查询正常执行。
- 166 部署修复后，实际删除预检返回 reference_check_complete=true；source_counts 为 workflow_version=1、assistant=1。来源明细展示“工作流”v0、3 个匹配位置，及“助手”1 个位置。
- 真实页面已看到工作流与助手来源表、可打开来源的链接，以及助手节点、知识库检索节点、知识库问答节点三个位置。
- 只执行预检和打开/取消弹窗，没有点击确认删除，空间及配置保留。
- DM8 未进行真实数据库运行验证；修复使用通用 SQLAlchemy String 转换，没有新增 MySQL 专用 SQL。

## 部署

166 使用本地派生镜像，原注册表 beta2 镜像未覆盖：

- 后端/API 与 Worker：`bisheng-backend:3.1.0-beta2-reference-hints-20261125`，镜像 `5a4e9d05289d1f7cbed066d3d83ce512f02f6dec8b6494c7b5c13afa34803a12`，只替换引用查询文件。
- 前端：`bisheng-frontend:3.1.0-beta2-reference-hints-20261125`，镜像 `00e8eac834417219c9bb4ec7e8b7adfd9b3d58727a3ac6f372ceb3a4dc91e4b8`，在之前上传按钮热修复镜像上只替换三语 knowledge.json。
- 私有备份：`/opt/bisheng/ops-backups/166-reference-hints-20261125/`，保留 env.before、原镜像 ID、原源文件和两份构建上下文；不在仓库记录凭证。
- 后端容器重建后曾因 Nginx 缓存旧 upstream 地址返回 502；重载 Nginx 后真实 API 已恢复。后续前端重建也会重新解析 upstream。
- 回退只恢复 `.env` 的对应镜像变量并重建对应服务，不整份覆盖并行修改的 env。后端原值为注册表 beta2，前端原值为上传按钮本地热修复镜像。

## sdd-code-review 自审

| 维度 | 结果 |
| --- | --- |
| 边界条件 | PASS：大整数和非规范字符串 ID 回归；既有空范围不变 |
| 权限与认证 | PASS：未改实际目标资格、租户范围和来源披露 |
| 并发安全 | PASS：只读查询；独立提示 Session、异步索引语义不变 |
| 信息泄漏 | PASS：未新增公开错误详情、凭证或查询字段 |
| 测试覆盖 | PASS：25 项及现场真实 MySQL/API/UI 核对；DM8 限制如上 |
| 代码风格 | PASS：Ruff、arch-guard、i18n 检查通过 |
| 文档同步 | PASS：006-reference-hints design 已补已知坑和修订记录 |

Overall：PASS。以上为本轮自审，非独立 agent 审查。
