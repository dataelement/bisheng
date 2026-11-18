# F025 任务与唯一进度入口

- [x] 从最新remote beta1 c36ba672be建独立工作区，保留主工作区。
- [x] 用户确认原方案；独立评审并补齐安全/状态生产者细节。
- [x] A：模型来源按槽位准入、继承不授权、真实消费者接线及回归。
- [x] B：持久共享意图、新租户/新模型生产者、接收初始化、覆盖恢复及回归。
- [x] C：图片权威与共享只读价格、批量管理读取、DSH/nonDSH调用一致及回归。
- [x] Root：五栏目诊断与恢复继承UI、错误/缓存/租户切换、三语言及集成。
- [x] 生成并核对八列QA参考用例；E2E接口链路与页面清单。
- [x] 受影响回归、lint/typecheck/i18n/build、架构守卫、独立审查。
- [x] 本地提交并交付，不部署、不修复116存量、不自行合并推送。

共享写入：A独占llm/domain/services/llm.py、来源core/runtime及相关调用消费者；B独占共享/挂载链和接收初始化；C独占DSH视觉/价格/模型目录和modelPricing.ts；Root独占llm/api/router.py、管理诊断新文件和平台UI/三语言/文档。跨边界先协调，不抢写。所有Owner禁止stash/reset/clean或repo-wide restore。
