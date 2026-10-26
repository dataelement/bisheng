# F086 模型规范与 DM8 静态审查（2026-10-21）

用户确认：本轮不连接DM8，不执行真实驱动/DDL/事务测试；核对模型定义、规范与约束即可。AC-61的双数据库兼容目标保留，按constitution C2将DM8实测交中央回归，不再作为本Feature当前阻塞项。

## 结论

15张运行时表（12张租户表、3张全局目录/节点表）静态检查通过。发现并修复一处存储范围缺陷：材料上限2GiB、snapshot默认上限10GiB，原32位INTEGER无法完整记录；`runtime_artifact.size_bytes`和`runtime_transfer.offset`改为跨数据库`BigInteger`，默认0、NOT NULL保持。

| 检查 | 结果 |
| --- | --- |
| 新表与自动发现 | 模型位于domain/models且table=True；model_discovery可发现；全量RUNTIME_TABLES含15张表 |
| 租户边界 | 12张表继承tenant_id/app_id及索引，tenant_filter提前导入模块；3张全局表不加tenant_id |
| JSON与大字段 | 统一JsonType；MySQL JSON，DM分支CLOB；JSON列不作为唯一键/索引键 |
| 时间默认值 | create_time使用CURRENT_TIMESTAMP；全部update_time使用共享UPDATE_TIME_SERVER_DEFAULT，DM分支不产生MySQL ON UPDATE |
| 键、长度与唯一性 | UUID字符串主键、字符串有界；15项具名业务唯一约束的字段非NULL；索引可静态编译 |
| 大文件范围 | 两个字节计数列使用BIGINT，可容纳2GiB材料与10GiB快照 |
| 旧库升级 | 新revision `f086_runtime_byte_counters`挂在已查询的唯一head `merge_vibe_f077_heads`之后；DDL-only扩容；新库已是BIGINT则跳过，缺表/列则跳过，未知类型明确报错 |
| 降级 | 不把BIGINT缩回INTEGER，避免截断已存大计数；保留列不影响旧ORM读取 |

组合回归28 passed，包含模型约束、共享DM分支、迁移守卫、Repository、artifact/storage和单head检查。[测试日志](./model-review-tests.txt)、[元数据与静态DDL](./model-review.json)。

macOS没有dmPython/dmSQLAlchemy：DM检查使用SQLAlchemy通用编译器、`name=dm`触发共享适配分支，不称为真实DM8方言或驱动验证。新增扩容revision本轮也未对真实MySQL/DM8执行；此前109验收记录对应修复前schema，不能用此前通过冒充该revision已经实测。Ruff和逐文件arch-guard另行检查；本次未提交代码。

## 正式CI/镜像发行的具体范围

独立工作流和构建脚本已写好；后续已按用户要求用v3.0.0-test-vibe实际完成GitHub双原生测试发行及109公开服务镜像启动核验，T053关闭。完整平台断网新装及目录导入仍未演练，见[evidence](./e2e-evidence/2026-10-21-ci-release/README.md)。

1. 选择不可变release标识；配置Docker Hub写入身份（DOCKERHUB_USERNAME/DOCKERHUB_TOKEN）以及可用的原生amd64/arm64 runner。
2. 通过workflow_dispatch(version)或v* tag触发runtime-images工作流，两架构分别构建七类镜像：runtime-manager、app-proxy、Python runtime/preparer、Node runtime/preparer、static runtime。egress及data-helper复用manager镜像，static复用Node preparer。
3. 执行基础烟测及原生禁网准备、复用、SQLite等集成检查。当前脚本在基础烟测后推送架构标签；后续完整原生检查仍可能失败，所以部分已推tag不等于整套发行通过。
4. 推送 dataelement/bisheng-*:<release>-<arch>，记录各镜像manifest digest和配置Image ID，检查已有tag并拒绝覆盖。两侧完整job成功后才合成manager/app-proxy服务多架构索引并生成runtime-profiles.json（运行时与preparer按平台引用固定child digest）。
5. 验证实际仓库镜像及目录可取得；安装侧将Compose的BISHENG_RUNTIME_MANAGER_IMAGE/BISHENG_APP_PROXY_IMAGE指向已发行版本，由超管导入目录并按需CAS切默认环境。离线客户再通过准备机docker save/load交付镜像及依赖材料；当前工作流不自动生成整套离线安装包。

工作流当前没有“只构建不推送”的dispatch开关，触发正式工作流会实际推Docker Hub；后续测试Tag已触发并通过。工作流未出现在默认分支时，网页手动Run workflow入口可能不可用；本次实际采用Tag触发。它发布的是平台服务/基础运行环境镜像，不是让客户每次发布应用时构建镜像，也不自动部署客户环境。

源码：[workflow](../../../.github/workflows/runtime-images.yml)、[构建脚本](../../../scripts/build_runtime_images.sh)、[安装和目录导入](../../../src/runtime-manager/OPERATIONS.md)。
