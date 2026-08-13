# 复盘记录 Retrospective: 专家问答上传资源持久化

## 阅读摘要
- 原范围从回答图片扩大到问题/回答全部结构化上传资源，实施中又补充了“点击资源直接下载”的同根因缺陷。
- 本地实现与相关回归已经完成；真实 MinIO、数据库和浏览器联合验证仍属于 staging 门禁 `T012`。
- 全局临时桶生命周期、富文本内嵌 URL 与正式对象垃圾回收仍明确留在后续范围。

## 元信息 Metadata
- Feature ID: `054-qa-uploaded-asset-persistence`
- Status: `implementation-verified, staging-pending`
- Related requirements: `specs/054-qa-uploaded-asset-persistence/requirements.md`
- Related design: `specs/054-qa-uploaded-asset-persistence/design.md`
- Related tasks: `specs/054-qa-uploaded-asset-persistence/tasks.md`
- Related verification: `specs/054-qa-uploaded-asset-persistence/verification.md`
- Created: `2026-08-12`
- Updated: `2026-08-12`

## 已完成范围 Completed Scope
- QA 五个结构化资源字段的临时对象转正、永久 key 持久化、读取动态签名、失败补偿和历史修复脚本。
- `f083` 扩容三个多值字段，并保持 revision 直接衔接 `f082_department_short_name`。
- QA 上传 MIME 透传、历史 `application/octet-stream` 图片格式校验与 MIME 修正、`inline` 签名。
- 门户问题/回答图片和 QA 自上传文件的站内预览弹窗；知识库关联文档保持既有详情预览链路。
- QA 预览弹窗复用现有 `PreviewWatermarkProvider` 和 reader overlay，水印内容继续由当前用户、部门、日期及后台配置统一生成。

## 范围变化 Scope Changes
| Change | Spec Updated? | Reason | Impact |
|---|---|---|---|
| 回答图片扩大到问题/回答全部结构化图片与附件 | yes | 共享上传接口和原样持久化缺陷影响五个字段 | 引入统一 `QaAssetService`、双表历史脚本和三个多值字段扩容 |
| 增加资源点击预览修复 | yes | 用户发现全部图片/附件点击触发下载；调查确认上传 MIME 丢失且门户直接打开对象 URL | 新增 REQ-007、T013/T014、门户预览弹窗和 MIME/签名 contract |
| QA 预览增加现有系统水印 | yes | 用户要求图片和文件预览保持门户既有水印安全策略 | 新增 AC-REQ-007-05/T015，仅补 Provider 接线并复用已有 overlay |

## 实现经验 Implementation Learnings
- 对象长期可访问不只取决于 key 和签名 TTL；`Content-Type`、`Content-Disposition` 同样是面向浏览器的持久契约。
- 复制对象时若只保留旧 metadata，历史错误 MIME 会跟随进入正式桶；转正流程应基于已验证内容修正 metadata。
- “inline” 不能无条件配合用户扩展名；HTML/SVG 等主动内容需要降级响应 MIME，并只在净化后的站内阅读器中展示。
- attachments 的业务 ID、知识文档 ID 和对象引用混合存在，读取与预览必须保持字段感知，不能统一当成对象 URL。
- 复用带 overlay 的阅读器并不等于自动拥有水印；必须同时检查其 Context Provider 是否位于新入口的组件树上。

## 设计偏移 Design Drift
| Drift | Source | Impact | Follow-Up |
|---|---|---|---|
| 初始设计仅覆盖资源生命周期，没有定义浏览器 MIME/预览行为 | REQ-007 / T013 / T014 | 增加最小 storage 可选参数与门户预览组件 | 已同步更新 requirements/design/tasks；staging 在 T012 验证 |

## 验证缺口 Verification Gaps
- 当前环境未连接 staging MinIO/数据库，未执行真实 DDL、对象复制、历史 apply 或删除 tmp 后复读。
- 门户生产构建已通过，但当前 Node `20.13.1` 低于 Vite 建议的 `20.19+`；应在正式 CI 运行时使用项目要求版本。
- 门户聚合测试入口被本范围外既存 TypeScript 测试错误阻断；本次预览测试已隔离执行通过。

## 后续工作 Follow-Up Work
| Item | Type | In Current Scope | Owner / Next Step |
|---|---|---|---|
| 完成真实 MinIO/DB/浏览器 smoke | verification | yes | 部署到 staging 后执行 T012 手工门禁 |
| 盘点并修复全局 `tmp-dir` lifecycle filter | feature | no | 另立共享对象生命周期 spec |
| 扫描问题富文本内嵌临时 URL | feature | no | 确认结构化证据后另立 spec |
| 正式对象引用计数与垃圾回收 | feature | no | 设计资源关系/保留期后实施 |
| 修复门户聚合测试基线 | bug | no | 由对应配置/测试模块处理现有类型错误 |

## 复盘质量门 Retrospective Quality Gate
- [x] Scope changes were reflected in requirements/design/tasks before implementation continued.
- [x] Follow-up work is not marked as completed scope.
- [x] Verification gaps are explicit.
- [x] Lessons that affect future implementation are recorded.
