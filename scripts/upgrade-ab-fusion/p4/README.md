# P4 身份 B→A

依赖顺序: 租户 → 用户 → 部门/组 → 角色 → 模型/工具映射.

```bash
bash p4/00-install-control.sh
bash p4/01-export-identity.sh
bash p4/02-propose-maps.sh
# 签字 csv 到本目录
APPLY=0 bash p4/10-apply-identity.sh
```

`bind` 只写 `fusion_map`, 不 UPDATE A 的 `user`/`department`.
`create` 在 A INSERT, 密码为不可登录占位 `*`.
