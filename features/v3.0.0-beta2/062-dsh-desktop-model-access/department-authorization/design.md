# 技术设计
状态：用户已确认简化版。基线 b034bea54166e759053abcdabc7bee0a41f48a0e。

Platform 复用 Dialog/Input/LoadButton，固定工具栏与滚动树表；部门与成员同列编辑额度，成员显示已保存最终额度和资格。根展开、直属成员分页；搜索用户保留部门路径。个人草稿复用 useUserPolicyDrafts 的幂等 ID、版本检查、部分成功恢复。部门独立正额度与个人同口径保存，空值为零。

额度编辑和展示使用“万 Token/月”。输入组件按十进制字符串移动四位完成换算，保留 1 Token 精度及安全整数上限；共享草稿与 API 继续使用整数 Token。输入中的小数点和末尾零保留到失焦，空值等价于 0。部门最终额度取已保存的自身和祖先额度最大值，正额度显示已授权；用户继续使用服务端返回的最终额度与席位状态。树正文使用 Platform 现有 text-sm 字阶，部门行 48px、成员行 56px，空成员占位省略。

Domain 保持最大值解析和 SQL/Redis 配额写入。额度保存独立于席位容量。模型成员分页增加可选 include_seats/unassigned_only，默认兼容已有调用方。资格查询按页、有界并发及超时，通过已授权租户调用 Gateway license 和指定用户 seats。状态顺序：零额度 UNAUTHORIZED；查询异常 UNAVAILABLE；许可无效 LICENSE_UNAVAILABLE；撤销 REVOKED；已分配 AUTHORIZED；有容量 PENDING_LOGIN；其余 SEAT_LIMIT_REACHED。真实调用仍校验模型和月剩余额度。

用户域增加当前租户有效部门的未分组过滤、用户名/精确 ID 搜索。旧角色额度用独立运维程序迁移：管理服务读取当前成员，个人额度提升至 max(有效个人,角色)，幂等写入并逐人核对，然后关闭角色策略；失败保留旧策略。保留审计与历史，兼容 API 保留用于回滚。

部署前从 live release 合并本次增量，基于组合源码构建；迁移 dry-run、备份、apply、逐人校验；复制 release 后原子切换，健康失败回滚。Gateway 镜像、席位表、月用量保持原样。
