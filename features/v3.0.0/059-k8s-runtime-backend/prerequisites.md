# F059 前置继承状态

## 公共多租户启动（已从发布线继承）

用户2026-10-22明确授权后，将`0e3c156e5042d7805c3b02f32c39c49e235bf521`与最新发布线普通合并，推送`feat/3.0.0@9d156f261cc7769fcf75f41caeb104a425308017`。`git ls-remote`核验远端一致。F059在`98fbba0325be7a897239e9fe853653297b4b1b87`普通合并该发布线，两个父提交均保留；三个生产修复文件与发布线逐文件diff为空。主工作区未切换或改动，未复制权限分叉。

冲突逐文件处理：同时保留app和linsight_skill资源注册、应用审计过滤/导出及沙箱审计；审批页拆分后保留必审判断、审批人来源和单租户标签；Vibe调用适配已发布共享组件。自动审批拒绝批量修改后，采用逐文件修改和验证；被拒绝脚本未执行。

验证：公共修复17项通过；继承权限/审计选择197 passed、3 xfailed；前端13个文件98 passed；runtime-manager 600 passed、10 skipped；资源账本/材料协议/模型82 passed。平台lint 85项、类型1项，client lint 89 errors/1 warning、类型4项，与发布线同一选择逐条比较无新增。全仓质量门仍未通过；lint:prune仅收缩抑制项。

继承后实测三条迁移head，新增空`f059_merge_release_heads`汇合；原父链不变，无表或数据修改。`alembic heads`确认唯一head，单head测试通过；尚未执行真实数据库升级。

## Vibe 专有字节计数器（已继承）

来源：原F086 `codex/086-vibe-runtime-delivery@667546bb77`。两字段扩为BIGINT。通用发布线没有runtime_delivery模型，属于分支特定修复，未向发布线复制不存在的应用模块。

保留F059字段并逐段解决BigInteger/String导入冲突。静态模型守卫明确授权历史NULL和待绑定UID NULL例外，其余约束不放宽。原迁移父链不改；`f059_merge_f086_heads`显式汇合源修复，后续发布线继承汇合在其之后。

## 验证边界

MySQL/DM8模型类型和约束为静态核查，未运行真实DM8或新迁移的真实数据库升级。189连接与节点Ready、无StorageClass/PV已刷新确认；尚未安装业务资源或运行应用E2E。
