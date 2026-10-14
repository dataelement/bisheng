# 发布路径记忆设计

## 已确认方案

复用 `UserLink`，不按租户分组。现有字段 user_id、type、type_detail、update_time 足够；type_detail 上限 255，使用紧凑 JSON 只保存目标库/目录和格式版本。

| 发布分组 | 专用 type |
|---|---|
| 个人→团队/科室 | publish_target_personal |
| 团队/科室→部门 | publish_target_team |
| 部门→公共 | publish_target_department |

原唯一键包含 type_detail，不能保证每个用户/类型只有一条。仓储沿用现有 KnowledgeSpacePinRepositoryImpl 的用户行锁，在同一事务中选择最近记录、清理同类型重复项后更新或插入；只匹配当前用户及精确专用类型。JSON 严格校验版本、正整数 ID、根目录 null；不保存标题、版本关联、理由或凭证。

## 链路

1. 发布申请验证完成后，pending/pass 将源层级、已验证目标传给偏好服务。源层级在提交前捕获，避免后台移动文件后分组变化。偏好失败记录日志及非阻塞响应告警。
2. 新增 GET `/api/v1/approval/shougang/file-publish/last-target`，只接收源库/源文件。服务端从登录用户读记录，复用源发布资格与目标查看校验。失效库不回传不可访问的 ID/名称/路径，返回失效原因。
3. 有效目录按当前 file_level_path 生成祖先 ID 列表，前端用发布专用目录接口逐级核对并加载真实节点；目录已在同库内移动时跟随当前位置。删除、移出目标库、异常路径或加载失败时提示并回根目录。
4. 前端打开时加载可选库和最近目标；恢复完成前禁用提交。关闭、源文件或账号变化撤销旧异步写入，清空版本和理由。目录树接收可选恢复数据，分享调用保持兼容。无需浏览器持久化，也无需客户端指定账号。
5. 偏好读取和自动恢复目录的单次请求最多等待 5 秒，超时降级并提示；手动目录展开的原请求行为保持。

## 文件计划与追踪

| 文件 | 职责 | Requirements |
|---|---|---|
| knowledge/domain/repositories/{interfaces,implementations}/knowledge_publish_target_preference_repository*.py | UserLink 专用类型和事务读写 | REQ-1, REQ-4 |
| knowledge/domain/services/knowledge_publish_target_preference_service.py | 分组、紧凑 JSON 校验、会话边界 | REQ-1, REQ-2, REQ-4 |
| approval/api/endpoints/shougang_approval.py、domain/services/shougang_approval_service.py、domain/schemas/shougang_approval_schema.py | 私人记录读取、实时权限、成功提交保存 | REQ-1, REQ-2, REQ-4 |
| client/src/api/approval.ts、SpaceDetail/filePublishTargetPreference.ts | 契约、路径恢复辅助逻辑 | REQ-3, REQ-4 |
| client/src/pages/knowledge/SpaceDetail/FilePublishDialog.tsx、FilePublishTargetTree.tsx | 打开恢复、告警、目录展开及异步隔离 | REQ-3–REQ-5 |
| backend/test/knowledge、test/approval；客户端 API、弹窗、目录树测试 | 最小充分回归与失败路径 | REQ-1–REQ-5 |
| features/v2.5.0-sg/release-contract.md | 记录对既有 UserLink 的专用类型复用 | REQ-1 |

## 验证及边界

使用现有 Python 3.10 .venv、SQLite 异步仓储测试、mock 发布校验、Jest 弹窗集成与分享回归；检查 FOR UPDATE 语句，但 SQLite 不能证明真实行锁并发效果。补充构建及真实浏览器观察；真实 MySQL/DM8 并发和线上验证未运行时明确标记。

不新增 DAO、表、依赖、运行时配置或权限策略。user_link 本来没有租户列，直接按登录账号读取符合用户要求。默认目录接口最多 200 子目录的契约保持；未能找到路径时保守降级。偏好更新和受理申请非原子事务，偏好失败不能撤销或误报已受理申请。
