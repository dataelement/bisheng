# F116 主线部署验收

本次只交付本地代码。真实 API 测试：`src/backend/test/e2e/test_e2e_managed_spaces.py`，默认跳过，使用既有测试空间和短期 token，不造数或改授权。

明确设置 `MANAGED_SPACES_E2E=1`、`E2E_API_BASE`、`MANAGED_SPACES_E2E_CASES`（JSON）。cases 含 ordinary、super_admin、restricted_super_admin，每项包括 token_env、正整数 tenant_id、以 `e2e-managed-spaces-` 开头的 data_prefix、非空 fixtures。fixtures 含 case_name、space_id、included、user_role、is_pinned；禁止写入真实凭据。

在 backend 执行 `pytest test/e2e/test_e2e_managed_spaces.py -v`。收窄超管必须由操作者确认 token 为 personal_only；`/user/info` 的管理员标记本身不能证明 token 数据范围。

- [ ] AC-01/AC-04：普通成员、创建者、直接/部门/组编辑授权入选；viewer/manage-only、不可见、未发布、跨租户不入选；验证 my-permissions 的 edit。
- [ ] AC-02：枚举不完整、不可用和超过 5,000 明确失败，不出现部分成功。
- [ ] AC-03：固定可见量改变租户总量、固定租户量改变可见量；保存阶段指标及 SQL/FGA 次数，确认没有全租户逐页扫描。
- [ ] AC-04：租户管理员保持个人 visible 范围；全范围超管仅当前租户；收窄 token 不绕过范围；撤权、发布、Redis 异常不扩大结果。
- [ ] AC-05：浏览器排序/置顶/角色/计数/部门及详情/广场退出重入不回退；公开应用和文件权限保持主线现状。
- [ ] AC-06：成功、错误阶段及候选/批次/返回计数可观测。
- [ ] AC-07：记录实际镜像 digest 和提交，同账号同数据分别测冷/热 P50/P95；离线批次预算和 COFCO 冒烟耗时不是主线实测。
