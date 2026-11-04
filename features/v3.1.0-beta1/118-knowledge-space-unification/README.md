# 知识库与知识空间统一：功能工作区

**迁移日期**：2026-11-04  
**功能分支**：`codex/3.1.0-beta1/118-knowledge-space-unification`  
**工作区**：`/Users/zhangguoqing/works/bisheng/.worktrees/118-knowledge-space-unification`  
**代码基线**：`d99eb7e430929323a9bf19e2242df9f54d63d908`，在本功能分支合并主工作区本地 `61971a13d8129a12a4522e31ff23d6dbd595bac2` 和最新远端 `origin/feat/3.1.0-beta1` 的 `22d46549f9a1f09fb7b63f3f7235c882b1576646`，两边提交均保留。

## 文档入口

- [Spec：92 条验收标准](./spec.md)
- [技术设计：迁移、策略统一、业务绑定维护和强制删除](./design.md)
- [升级说明：停服、引用回填、恢复与核对](./upgrade-guide.md)
- [HTML 技术评审：12 张流程图](../../../docs/architecture/review/2026-11-03-bisheng-knowledge-unification-technical-review.html)
- [版本契约：保留其他特性登记并加入 F118 增量](../release-contract.md)

## 迁移边界

本次迁入已有规格、设计、升级说明和 HTML，保留已确认的 Q-01–Q-05、业务同事务维护绑定、旧数据回填及强删后保留失效关系的规则。原文中的 `feat/3.0.0` / `25e50eceeeb71989257e5ff38e35f5e011e59bae` 是历史源码调研证据，并非新功能工作区的当前代码基线。

尚未重新对最新基线完成全部源码接线审查，尚未实现功能代码或迁移脚本；完整 spec/design 仍待整体技术评审。F118 编号保持现有文档约定。主工作区其他配置、登录流程及验证文档不迁移。
