# F077 主线设计

基线 origin/feat/3.0.0，独立工作区、分支 codex/subject-id-search-3.0.0。遵守 docs/constitution.md。用户已确认本方案与既有通用搜索口径，不重复规格/设计确认。

1. common 仅放规范化、LIKE 字面转义和数字前缀范围；core 双库表达式通过 as_comparison 标记比较，避免达梦错误的 =1。
2. Service 保留原主线鉴权与范围，SQL 归所属 user/department/tenant Repository。授权按既有 application 目录装配接入，不复制中粮隐藏/邀请策略。
3. 页面以主线组件增量适配，保留原平铺选人、原写入和主线其他更新，不整文件覆盖差异代码。
4. 用户/部门新增 external_id 前导非唯一索引，独立 f077 revision 接当前主线唯一 head merge_release_information_heads，不能使用中粮 migration。
5. 统一后端回归，失败集合比较主线基线；逐文件白名单及独立审查中粮渗入。原有优化保留不代表实际性能验收通过。
