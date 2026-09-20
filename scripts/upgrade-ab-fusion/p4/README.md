# P4 身份 B→A

依赖顺序: 租户 → 用户 → 部门/组 → 角色 → 模型/工具映射.

```bash
bash p4/00-install-control.sh
bash p4/01-export-identity.sh
bash p4/02-propose-maps.sh
# 无冲突已写入 p4/*.csv; 有冲突看 logs/p4/*.conflicts.csv
APPLY=0 bash p4/10-apply-identity.sh
```

`bind` 只写 `fusion_map`, 不 UPDATE A 的 `user`/`department`.
`create` 在 A INSERT, 拷贝 B 的 `password` 哈希; 空哈希仍写不可登录占位 `*`. 无工号用户也走 `create`, 不编造工号. 模型/工具对照表无冲突时一并安装, 真正建行和拷密钥在 `p5/30-apply.sh`.
