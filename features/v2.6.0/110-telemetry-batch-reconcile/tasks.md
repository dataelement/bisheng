# 实施任务

- [x] T1 通用批量差异写入与部分失败/并发验证。_Requirements: REQ-2, REQ-4_ _Acceptance: AC-2, AC-3_
- [x] T2 人员多日期共享查询、合并登录、差异写入与安全清理。_Requirements: REQ-1, REQ-2_ _Acceptance: AC-1, AC-2, AC-3_
- [x] T3 问答和内容文件增量采用批量差异写入。_Requirements: REQ-2_ _Acceptance: AC-2, AC-3_
- [x] T4 持久任务预算、队列条目预算、恢复与检查工具。_Requirements: REQ-3, REQ-4, REQ-5_ _Acceptance: AC-4, AC-5_
- [x] T5 相关回归、静态检查、运维与验证文档。_Requirements: REQ-1, REQ-2, REQ-3, REQ-4, REQ-5_ _Acceptance: AC-6_

## 实际偏差记录

沿用已有工作区和已授权优化范围，不新建分支，不触碰现有权限、依赖、Beat 配置等其他改动；本地实现不进行运行中数据变更。

补充纳入行为事件批量链路及用户 Repository 批量方法，以完成“能批量的就批量”。统计定义、事件字段和原接口保留。真实中间件及部署验证未执行，详见 verification.md。
