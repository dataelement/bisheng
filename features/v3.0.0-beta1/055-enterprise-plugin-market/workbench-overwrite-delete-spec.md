# 重复覆盖、100 MiB 与工作台删除

用户直接确认三项变更，沿现有 dsh_market 模块实现；保留原工作树改动。覆盖语义同时适用于插件和工作台，大小与删除扩展针对工作台。无 ZIP 批量支持。

## 验收

- AC-UPDATE-01：同租户、同身份和完全相同版本号允许不同包内容覆盖；预览 allowed=true、overwrite=true（内容不同）或 duplicate=true（内容相同）。替换 digest/size/manifest、包显示元数据、updated_at/revision，保留版本号与版本 ID。低版本及身份冲突、SemVer 等价但字符串不同的工作台版本冲突仍拒绝。
- AC-UPDATE-02：A→B→A 同版本反复导入以最后一次主动导入为准，不能因 digest 对应旧 completed 任务直接返回成功却未更新；相同内容重复安全，已删除工作台重导入可恢复。覆盖后详情摘要、下载内容/ETag 一致；下载期间替换或删除须检测陈旧结果。
- AC-UPDATE-03：工作台原始 TGZ 最大 100 MiB，前端、API 读取、domain、代理一致；100 MiB 内合规包正常，超限明确拒绝。解压总量 256 MiB、文件数、YAML 等安全限制不放宽。一次最多 50 包，移除 64 MiB 独立批次总量上限，串行读/上传。插件既有 512 MiB 上限不主动降低。
- AC-UPDATE-04：租户管理员可在工作台管理行内删除，二次确认后使用 DELETE /api/v1/dsh/market/admin/workbenches/{id}?revision=n；列表/详情增加 revision 整数。返回 {id,deleted:true}。使用 tenant+revision 并发保护，过期 revision 返回已有工作台冲突码。
- AC-UPDATE-05：删除把 current_version_id 置空并 revision++，无 schema 迁移；版本/任务/内容寻址对象保留。管理员与员工列表、详情、旧 URL 下载不可见；重新主动导入可恢复。不影响客户端已安装内容。
- AC-UPDATE-06：覆盖提示、删除确认/结果三语言齐全，异步错误使用已有 ApiError；删除锁定重复提交，失败保留行、取消不发请求，成功刷新及最后一页回退，不跨租户回调。
- AC-UPDATE-07：补齐真实路由回归：新字节/ETag、A→B→A、相同内容、降级/身份、权限租户、CAS 删除/旧下载/重导入、100 MiB 边界与代理配置；前端覆盖提示、100 MiB/100 MiB+1、超过旧总量仍处理、删除确认/取消/失败/成功。质量检查、独立审查及 109 部署记录。

## 实现边界

写入经过现有 market_admin 与 tenant 限制。不新增存储字段，不删除 MinIO 共享内容，不迁移历史数据。上传存储内容寻址，数据库事务更新元数据，失败保留原包。覆盖须推进插件发布审计与目录 revision；旧任务与下载消费者一并检查。

状态：本地实施完成；后端 Python 3.11 冻结环境 118 项、前端 100 项、质量门禁、生产构建与七维源码审查通过。109 登录恢复后发布完成：候选 Python 3.11 自检、服务健康、公开资源摘要和实际 100 MiB multipart 代理/未登录拒绝检查均通过；登录后的业务 UI 手工清单未执行。证据见 workbench-overwrite-delete-validation.md。
