# F111 集成候选代码审查

历史候选快照（后续增量以文末为准）：2026-10-24。B基线 `858f76605ca81f0cef36f42841414b797a432fac`，合并源 `3420114d0`；G基线main `2995df6f`、特性源 `108eb5c8` 加T185/T186最终修复；Desktop源 `6c84d46`，T192兼容修复尚待收口。最终交付SHA与CI/digest见 deployment-execution.md。

本报告按仓库 `/sdd-code-review` 七维审查实际diff、源码及spec/design/tasks。B使用尚未提交的真实组合工作树差异而非三点HEAD，以免漏掉合并中的文件；G主/独立agent逐行交叉复核最终两源。候选源码审查与完整环境验收分别记录。

| 维度 | 当前HIGH | 当前MEDIUM | 结论与依据 |
|---|---:|---:|---|
| 边界条件 | 0 | 0 | 严格JSON/ID/分页/协议预算；Responses跨part缺陷已配对修复 |
| 权限与认证 | 0 | 0 | 共享HMAC精确路径原始bytes、租户隔离/历史事件、原web-session及模型鉴权保留 |
| 并发与幂等 | 0 | 0 | 不可变事实、唯一约束、短事务、owner租约与版本；MySQL真实并发和升级结果独立记录 |
| 信息泄漏 | 0 | 0 | 不存正文/命中词/凭据；局部QueryClient原始错误日志已关闭并保留页面反馈 |
| 测试覆盖 | 0 | 0 | 本地配对和相邻组合已通过；DM8/真实E2E/容量不是已通过项目 |
| 代码与架构 | 0 | 0 | 无模型鉴权/计量网关耦合，Ruff/架构守卫/目标lint/类型/生产构建通过；旧全量lint保留基线 |
| 文档一致性 | 0 | 0 | 同步迁移、七页签、模型开始时间及有界跨part混合观察算法，未改已确认spec取舍 |

## 已修复发现

1. HIGH（T185/T186）：同message相邻output_text及同reasoning summary/content跨part漏检，原测试还将错误PASSED固化。先保留19RED，后扩空part、Unicode、delta/done混合和final替换回归；最终60配对全绿、Gateway主独立882全绿。各part尾部屏障在item结束前不解除，原始观察不能被safe final抹除，混合观察后缀候选最多64且计入既有buffer，超限ERROR。独立第二agent2100语义样本及128候选拒绝通过。原108eb5c8本身仍是修复前版本，不得部署该旧commit。
2. MEDIUM（T188）：开发react-query保存失败会输出包含自定义词/请求headers的AxiosError。两回归先RED，局部安全logger后24PASS；保留错误提示/草稿/不自动重试。
3. MEDIUM（T189–T191）：Card未消费已保存model_started_at，违反AC-46分别显示。新增独立三语详情行、未知/不适用，稳定请求header/排序不变；5RED转10PASS。
4. 组合兼容（T176–T178、T181–T184、T187）：未发布F111接续已发布积分head，保留已发布revision哈希；保留全部目标路由和七页签；补缺翻译；修正旧bootstrap常量及不可变配置测试撤销污染。未通过修改生产租户逻辑来制造测试通过。

## 实际验证

- Backend最终相关组合910PASS/15环境SKIP，0FAIL/ERROR；HMAC/登录组合82PASS，独立审查205PASS。
- MySQL T179主独立24PASS/24DM8SKIP；fresh149表、work110143→149、真实target积分148→149反射一致。raw80/rate125/billed100、UNKNOWN NULL、迟到与重复结算不变。SQL边界结果不冒称真实Gateway/模型/Redis E2E。
- Gateway最终主独立34类882PASS/0SKIP，Responses60；另两组独立语义样本1800及2100PASS。真实MySQL Outbox10PASS证据沿T120，不算DM8通过。
- Platform最终DSH28文件280PASS、Platform609strict及全workspace类型检查PASS、目标lint/i18n/locales PASS；最终UI后两个SPA正式build PASS。
- Desktop正式build/typecheck通过；完整测试2810PASS/5FAIL/3SKIP，3unhandled，既有Undici兼容缺陷由T192修复中，Python环境已定位。临时Profile启动有Harness is ready，但完整界面/登录/真实工具验收尚未通过。

## 结论与剩余验收

**B/G候选源码：PASS，可以进入用户明确授权的CI构建及109 DSH专用测试部署。完整特性T132：INCOMPLETE，不予勾选。**

LinuxDM8按用户确认待验；T121–T125真实角色/模型/页面/工具与恢复验收、T126–T129容量、T131回退演练仍须实际证据。旧全量frontend lint Platform95/Client23有逐文件字节等target基线，不修改抑制项，不声称全量lint通过。Desktop联调须先收口T192。

本报告不批准更改其他部署、放宽认证、生成License、清理真实审计、覆盖已有标签或force-push。用户已单独授权本次merge/push/CI/109部署和启动客户端，最终操作记录按实际追加。


## T197/T198 部署前最小兼容补审（2026-10-24）

PASS，未发现HIGH/MEDIUM：离线模型治理元数据与实际调用快照分开；仅两管理员visibility路由使用前者。调用online、tenant/Root FGA、provider归属、DTO、policy CAS与计量未改变。主读全部三源，独立相关71PASS/5真实环境skip；B五文件71PASS及Ruff/archguard/diff通过。测试的管理身份依赖替换只证明端口短路，实际普通身份拒绝尚待109新镜像读回。新修复待新CI镜像，不改写前一ecf43f79镜像身份；完整特性T132及License阻塞下现场验收保持未完成。


## 最终发布与验收补审

当前B3cc9de9298/G64f602be/Desktop3e8486c均已推送并核远端SHA，B5624/G404 SUCCESS，固定digest仅更新109DSH。T192最终2820PASS/3SKIP/0FAIL/0unhandled及正式build已收口，实际隔离Desktop已连接并完成两协议正常回复、真实read正例与敏感参数零调度。用户已追加授权官方生成测试License，实际有效至2026-11-23，不再存在此前License阻塞。

T199/T200精确19801→admin_forbidden403修复经891完整Gateway及独立44/Netty3通过，未知错误保持503；真实普通权限七例通过。新增冻结HTTP设施/协议/身份/只读审计测试经主逐源和A/B/C交叉复核，T202/T203新48+旧33/13通过；Provider只认证关联结果，真实工具体成功另由持久成功结果+文件nonce证实。真实协议35与审计12条子集通过，旧失败均保留；不冒完整T121/T122/T123、DM8、多副本/容量与T132验收。当前无新增已确证HIGH/MEDIUM源码阻断，完整特性交付状态仍PARTIAL。

T204/T205主独立全文复审抓住capabilities旧字段误判，实际wire反例修复后最终49local+7live全PASS；严格body byteCount、公开身份/Backend header、物理零调用、精确完整空分页与账本不变保持。未新增业务源。最终测试资料补充不改变已部署生产协议；后续CI镜像与实际容器按新远端SHA另行读回。
