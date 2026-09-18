# B 升级回滚

方案 §16.1: MySQL + MinIO + Milvus + ES(+etcd) 同一冻结点, 并在隔离机恢复演练.

## 完整冻结 (新演练 B, `01-freeze` 已成功)

```bash
APPLY=0 bash p2/90-rollback.sh
# 隔离机真恢复 (覆盖 MANIFEST 里的 live_host)
CONFIRM_VERSION_ROLLBACK=1 CONFIRM_RESTORE_STORAGE=1 APPLY=1 bash p2/90-rollback.sh
```

stamp: `BACKUP_STAMP` 或 `logs/p2/current-freeze.txt`. 不要在未确认的生产盘上 APPLY=1.

## 不完整冻结 (本轮 `20260911124114`, 没有对象存储副本)

```bash
APPLY=0 bash p2/90-rollback.sh
CONFIRM_VERSION_ROLLBACK=1 ACCEPT_INCOMPLETE_STORAGE=1 APPLY=1 bash p2/90-rollback.sh
```

只覆盖 `bisheng` 库和 compose/config. 检索对不上是对象存储未冻结的代价.

## 禁止

- `alembic stamp` 假装成功
- 半升级状态继续 hop
- 用 A 的库覆盖 B
- 不完整冻结不设 `ACCEPT_INCOMPLETE_STORAGE=1` 就 APPLY=1
- 完整冻结设 `ACCEPT_INCOMPLETE_STORAGE=1` (会拒绝)
- 在已经升完的这台 2.5 演练机上灌 2.2 (没有 2.2 dump)
