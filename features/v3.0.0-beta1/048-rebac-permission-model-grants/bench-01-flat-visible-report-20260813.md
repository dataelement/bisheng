# BENCH-01 初版：知识空间 `visible` 展平关系性能验证

## 1. 结论

在 `192.168.106.116` 的现有 OpenFGA 服务中新建隔离 Store，使用相同数据分别测试：

- 当前深层关系：`visible = permission_enabled AND (Grant/Model/Catalog 等可见分支)`；
- 展平关系：基准中命名为 `flat_visible`，直接投影
  `[user, department#member, user_group#member] -> resource`。

测试结果支持展平方案：在 10,000 个资源、用户可见 1,000 个资源、
`HIGHER_CONSISTENCY` 条件下，`flat_visible` P95 为 **19.281 ms** 且返回完整；
当前深层 `visible` 在约 3 秒 deadline 后仅返回 **659/1,000**，HTTP 状态仍为 200。

`flat_visible` 只是 A/B 测试中的对照名称。若采用该方案，建议直接把业务 `visible`
改为展平后的有效可见关系，不长期维护两个相同业务语义的 relation。

## 2. 测试边界

| 项目 | 值 |
|---|---|
| 测试日期 | 2026-08-13 |
| OpenFGA 环境 | `192.168.106.116` 当前服务 |
| OpenFGA 版本 | v1.14.2 |
| 数据存储 | 当前 OpenFGA MySQL datastore |
| 隔离 Store | `01KZX2TTNEEMZWN3R8DE3C08JM` |
| Authorization Model | `01KZX2TTPP0VH72QPYCPF2P0YQ` |
| 业务 Store | 全程未写入 |
| 资源规模 | 1,000、10,000 |
| 可见范围 | 直接用户 10、部门 100、用户组 1,000 |
| Tuple 数 | 66,446 |
| ListObjects deadline | 约 3 秒（当前服务配置） |
| ListObjects max results | 1,000（当前服务默认值） |

每组关系使用相同资源和相同授权主体；返回结果校验数量和集合 checksum。
强一致每组运行 3 次，默认一致性每组运行 5 次，串行执行，未进行并发压测。

## 3. 模型对照

### 3.1 当前深层 `visible`

```text
resource#visible
  = permission_enabled
    AND (
      protected_visible FROM grant
      OR (ordinary_visible FROM grant AND custom_mode)
      OR system_visible
    )

grant#ordinary_visible
  = ordinary_assignee AND active FROM model

model#active
  = active FROM release

release#active
  = enabled_marker AND active FROM catalog
```

ListObjects 需要反向展开 resource、Grant、assignee、Model、Release、Catalog 及
intersection/union 分支。

### 3.2 展平关系

```text
resource#flat_visible:
  [user,
   department#member,
   department#subtree_member,
   user_group#member,
   user_group#admin]
```

基准数据同时保留深层 Grant 事实和等价的展平 tuple，确保两条查询路径期望集合相同。

## 4. 核心结果

### 4.1 10,000 资源

#### HIGHER_CONSISTENCY

| 可见来源 | 期望结果 | 深层 `visible` P95 | 深层结果 | 展平 P95 | 展平结果 |
|---|---:|---:|---:|---:|---:|
| 直接用户 | 10 | 3,007.933 ms | 10/10 | 2.900 ms | 10/10 |
| 部门 | 100 | 3,011.952 ms | 100/100 | 6.054 ms | 100/100 |
| 用户组 | 1,000 | 3,022.130 ms | 首个样本 659/1,000，集合不稳定 | 19.281 ms | 1,000/1,000 |

深层关系在 10 和 100 结果场景虽然最终返回完整，但耗时已经达到 deadline；
1,000 结果场景出现 HTTP 200 下的部分结果，不能作为安全的资源范围使用。

#### 默认一致性

| 可见来源 | 深层 `visible` P50/P95 | 展平 P50/P95 | 展平集合 |
|---|---:|---:|---:|
| 直接用户 10 | 3,007.003 / 3,008.364 ms | 2.441 / 11.487 ms | 完整、稳定 |
| 部门 100 | 3,005.682 / 3,006.727 ms | 5.078 / 5.551 ms | 完整、稳定 |
| 用户组 1,000 | 871.046 / 1,565.028 ms | 13.685 / 15.963 ms | 完整、稳定 |

默认一致性的深层关系受 iterator cache 状态影响明显；展平关系不依赖热缓存也保持毫秒级。

### 4.2 1,000 资源

#### HIGHER_CONSISTENCY

| 可见来源 | 深层 `visible` P95 | 展平 P95 | 展平结果 |
|---|---:|---:|---:|
| 直接用户 10 | 3,010.499 ms | 3.332 ms | 完整、稳定 |
| 部门 100 | 3,018.562 ms | 5.380 ms | 完整、稳定 |
| 用户组 1,000 | 3,010.112 ms，结果不完整 | 16.375 ms | 完整、稳定 |

#### 默认一致性

| 可见来源 | 深层 `visible` P50/P95 | 展平 P50/P95 |
|---|---:|---:|
| 直接用户 10 | 31.092 / 151.122 ms | 3.007 / 3.144 ms |
| 部门 100 | 31.175 / 265.583 ms | 4.676 / 4.748 ms |
| 用户组 1,000 | 33.855 / 612.956 ms | 12.345 / 15.495 ms |

## 5. OpenFGA 执行成本

以下为 10,000 资源强一致场景的代表请求：

| 可见范围 | 关系 | query time | dispatch | datastore query | datastore item |
|---:|---|---:|---:|---:|---:|
| 10 | 深层 `visible` | 3,003 ms | 4,573 | 14,203 | 8,086 |
| 10 | 展平 | 1 ms | 10 | 4 | 10 |
| 100 | 深层 `visible` | 3,008 ms | 4,249 | 12,860 | 7,624 |
| 100 | 展平 | 3 ms | 102 | 7 | 101 |
| 1,000 | 深层 `visible` | 3,003 ms | 4,375 | 12,110 | 8,821 |
| 1,000 | 展平 | 15 ms | 1,001 | 5 | 1,001 |

展平查询的成本基本跟用户实际可见结果数相关，而不是跟平台资源总数及
Grant/Model/Catalog 图的反向展开规模相关。

## 6. 方案评估

### 6.1 性能判断

展平关系在本轮 10,000 资源测试中满足“平台资源大、用户可见范围小”的目标：

- 可见 10：强一致 P95 2.900 ms；
- 可见 100：强一致 P95 6.054 ms；
- 可见 1,000：强一致 P95 19.281 ms；
- 三种主体来源均返回完整且 checksum 稳定；
- 没有依赖默认一致性的热缓存才能达标。

因此，从读取性能和 ListObjects 完整性看，展平 `visible` 方案合理。

### 6.2 上线前必须解决的投影语义

展平关系是执行索引，Grant/Model/Catalog 和 SQL Grant 仍是事实来源。实现必须覆盖：

1. Grant 新增、撤销和模型替换；
2. Catalog 发布导致模型动作/等级变化，以及模型 active 只改变可分配状态、既有投影不变；
3. `CUSTOM/INHERIT` 模式切换；
4. protected owner 与 ordinary assignee；
5. direct、department、department subtree、user group member/admin；
6. public、tenant shared、system visible；
7. 同一主体通过多个来源获得同一资源时，撤销一个来源不得误删最终 `visible`；
8. 资源删除、租户隔离和投影失败闭合。

部门和用户组应继续使用 userset tuple，不展开为每用户每资源 tuple，避免组织变更造成
用户级 fan-out。

### 6.3 写放大

本轮 11,000 个资源共写入 66,446 条 tuple。展平方案相对深层事实增加一条
“有效主体 -> 资源”的执行 tuple；真实增量与有效授权主体/资源组合数量相关。

上线前还应补充 mutation benchmark：

- 单Grant新增/撤销；
- 同主体多来源去重与最后来源撤销；
- 1,000/10,000 资源下模型停用不扫描 Grant/不改 visible 的验证，以及 Catalog 发布；
- 部门/用户组成员变更；
- projection ledger重试与失败恢复。

## 7. 建议

1. 直接展平现有业务 `visible`，不要长期保留 `visible` 和 `list_visible` 两套相同语义；
2. `visible` 只表达“用户是否能看到资源”，具体 edit/download/manage 等动作继续使用
   当前 Grant/Model/Catalog 关系；
3. 新增受限 `list_visible_objects(resource_type, actor, max_results)` 入口，只允许经过
   BENCH-01 的资源类型；
4. 当前 OpenFGA `listObjects-max-results=1000`，入口必须显式检测/约束用户可见结果上限，
   不能把 1,000 当作天然全集；
5. 完成投影一致性和写路径性能验证后，再把知识空间 `joined` 改为
   `ListObjects(visible) -> DB按ID查询 -> 排除本人创建`。

## 8. A/B 槽与组织 userset 补充对照测试（弃选证据）

### 8.1 目的与数据

为验证目标设计中的 A/B 槽是否削弱展平枚举性能，2026-08-13 在同一隔离 Store 追加：

- Authorization Model：`01KZX7WGH8773H1EV083Y5Q7T6`；
- OpenFGA：v1.14.2，build `c8a0e7b553ec322edfaa88948d57ba73bcad8883`，容器镜像 ID
  `sha256:65c4db264a403bfd62387fed4fe48f1b7cdda694bdac5f493a8f3c5a6460b4ba`；
- 资源类型：`bench_ab_space_10000_v1`，10,000 个资源；
- 新增 tuple：13,365；A/B 两槽数据相同，每个资源都有
  `visibility_switch -> permission_visibility_switch:bench-ab-current-v1`；
- 可见分布：直接用户 10、部门 userset 100、用户组 userset 1,000、三种来源重叠后的
  混合集合 1,000；
- A 槽、B 槽分别激活测试；每组普通 ListObjects 强一致 10 次、默认一致性 20 次；
- 切换 A→B 仅原子删除 `slot_a_active`、写入 `slot_b_active`；
- 另用 StreamedListObjects 强一致完整消费 10 次，记录首条与完整结果耗时。

测试模型中：

```text
visible =
  (ordinary_visible_a AND slot_a_active FROM visibility_switch)
  OR
  (ordinary_visible_b AND slot_b_active FROM visibility_switch)
```

部门和用户组仍为 `department#member`、`user_group#member` userset，没有展开成员。

### 8.2 普通 ListObjects 结果

以下为 10,000 资源、HIGHER_CONSISTENCY P95；所有 240 个采样均成功，结果数量精确、
checksum 稳定：

| 当前槽 | 可见来源 | 结果数 | 裸展平 `flat_visible` | 当前底层槽 relation | 业务 `visible` |
|---|---|---:|---:|---:|---:|
| A | 直接用户 | 10 | 5.830 ms | 2.938 ms | 51.133 ms |
| A | 部门 userset | 100 | 9.672 ms | 6.759 ms | 50.686 ms |
| A | 用户组 userset | 1,000 | 16.289 ms | 17.040 ms | 63.233 ms |
| A | 直接+部门+用户组重叠 | 1,000 | 16.242 ms | 35.443 ms | 48.964 ms |
| B | 直接用户 | 10 | 3.634 ms | 2.894 ms | 52.810 ms |
| B | 部门 userset | 100 | 5.292 ms | 6.642 ms | 53.643 ms |
| B | 用户组 userset | 1,000 | 14.632 ms | 20.458 ms | 87.976 ms |
| B | 直接+部门+用户组重叠 | 1,000 | 12.758 ms | 13.177 ms | 80.975 ms |

A/B 两个槽返回集合完全相同，切换不改变授权语义。部门和用户组 userset 的底层槽查询仍
与直接展平关系同一数量级；主要新增耗时来自 `visible` 的 switch/intersection，而不是
userset 本身。

1,000 资源对照模型 `01KZX8617BJHZCM7PKHGH7EHGB` 中，B 槽业务 `visible` 强一致 P95：

| 可见来源 | 结果数 | 1,000 资源 | 10,000 资源 |
|---|---:|---:|---:|
| 直接用户 | 10 | 20.794 ms | 52.810 ms |
| 部门 userset | 100 | 25.211 ms | 53.643 ms |
| 用户组 userset | 1,000 | 37.753 ms | 87.976 ms |
| 混合重叠 | 1,000 | 25.371 ms | 80.975 ms |

这说明当前“每个资源一个 switch link + intersection”的表达仍受资源总量影响；虽然远低于
深层 Grant/Model/Catalog 约 3 秒的结果，但没有完全达到裸展平查询只随实际可见结果增长的
理想特征。

### 8.3 StreamedListObjects 结果

10,000 资源、B 槽激活、HIGHER_CONSISTENCY，所有 120 个采样均完整且 checksum 稳定：

| 可见来源 | 结果数 | 裸槽完整消费 P95 | `visible` 首条 P95 | `visible` 完整消费 P95 |
|---|---:|---:|---:|---:|
| 直接用户 | 10 | 22.924 ms | 70.421 ms | 71.376 ms |
| 部门 userset | 100 | 15.537 ms | 65.760 ms | 69.083 ms |
| 用户组 userset | 1,000 | 76.960 ms | 68.421 ms | 96.934 ms |
| 混合重叠 | 1,000 | 56.592 ms | 91.241 ms | 124.356 ms |

StreamedListObjects 解决普通 ListObjects 结果上限与静默截断风险，但不会消除模型图本身的
解析成本。当前合成数据下仍低于 125ms P95，不能据此直接外推并发或生产长尾。

### 8.4 结论与设计影响

1. 部门、用户组授权可以保留 userset，不必展开为用户级 tuple；本轮未发现 userset 破坏
   底层槽 relation 的列表性能，其成本仍主要随用户实际可见资源数增长。
2. A/B 双写明确增加存储与写放大；语义上只有当前激活槽贡献结果，A→B 切换前后集合一致，
   但不能据此假定 OpenFGA 物理执行时完全不遍历未激活分支。
3. 但是当前基于资源 `visibility_switch` + intersection 的运行时选槽给 10,000 资源带来
   约 40～75ms P95 附加开销，并表现出资源总量相关性。
4. 最新产品语义已经明确：模型停用只禁止新增或变更授权，已有 Grant 不受影响；模型删除前
   必须先撤销或替换全部绑定。因此不再存在“停用时瞬时撤销上万绑定”的全局原子切换需求。
5. 结合 2 倍写放大和约 40～75ms P95 的 switch/intersection 附加开销，目标方案选择单槽
   浅层 `visible`，A/B 仅保留为弃选方案的实测证据，不进入生产 DSL、迁移和运行时。
6. 上线门禁仍需在 pinned v1.15.1、目标完整单槽 DSL、生产脱敏分布和并发条件下复测普通
   Check、BatchCheck、StreamedListObjects、Grant 来源撤销/替换、模型停用投影不变和删除引用门禁。
