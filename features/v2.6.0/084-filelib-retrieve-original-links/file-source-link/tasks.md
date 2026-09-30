# 任务

- [x] T001 按 ID 签发入口与权限/引用回归
  - Done when: 接口、Service、DI 与参数/身份/拒绝/引用测试通过。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-005_
  - _Acceptance: AC-01, AC-02, AC-03, AC-05_
  - _Verification: V-001, V-002_
  - _Depends: none_
  - _Boundary: open_endpoints 与定向测试_
- [x] T002 共用后台访问地址与文档
  - Done when: 新接口和 retrieve 使用相同 Origin 策略，配置/回归测试和文档检查通过。
  - _Requirements: REQ-004, REQ-005_
  - _Acceptance: AC-04, AC-05_
  - _Verification: V-003、定向回归、Ruff、架构守卫_
  - _Depends: T001_
  - _Boundary: 设计列明文件；不修改线上配置_

## 实际偏差记录

按用户新增接口请求直接完成可审查实现；沿用当前工作分支，未创建/切换分支或提交。源链接服务自上次讨论后已增加引用解析与故障降级，以当前实现为基线。

相关回归发现旧 external_user_context 测试缺少当前 retrieve 所需运行时与文件仓库依赖，补齐测试夹具，不修改 retrieve 检索实现。客户端配置类型仅同步字段注释。实现和本地验证完成，真实 MinIO 下载与生产代理验证待部署后执行，详见 verification.md。
