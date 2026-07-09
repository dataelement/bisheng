# 知识空间文件上传额度可视化 PRD

> **版本**：v2.6.0 · **类型**：工作台（client）体验优化 · **状态**：已实现；因客户暂不需要，冻结于本备份分支 `feature/knowledge-space-quota-display`（beta4 已移除） · **原 commit**：`5d23e36a8` + 开关提交

---

## 一句话结论（电梯陈述）

> **用一处纯前端改动、复用既有配额接口，把"知识空间文件上传额度"从"超限那一刻才被动报错"变成"在账户菜单里随时主动可查"，并用系统配置开关（默认关）控制是否展示。**

支撑这个结论的三点（下文逐层展开）：

| 支柱 | 论点 | 成本 |
|---|---|---|
| **数据** | 后端已有 `GET /api/v1/quota/effective` 直接返回"已用/上限"，单位就是 GB | 后端零改动 |
| **展示** | 账户菜单里加一个额度条组件，覆盖正常 / 预警 / 无限制三态 | 1 个新组件 + 挂载点 |
| **刷新** | 配额 hook 迁 react-query，多处共享一次缓存、上传后自动刷新 | 内部改造、对外签名不变 |
| **开关** | `knowledge_space.storage_quota_display` 系统配置，默认关，需要时打开 | 复用现成配置下发管线 |

---

## 一、为什么做（背景 → 冲突 → 问题）

- **背景（Situation）**：后台管理员可按**角色**设置「知识空间文件上传上限（GB）」（角色编辑页，与"创建频道数""加入知识空间数"同组）。
- **冲突（Complication）**：这个上限对前台用户**完全不可见**——用户既不知道自己有多少额度，也不知道已经用了多少；只有在上传把容量顶爆的那一刻，才被动收到一次 `SpaceFileSizeLimitError`（错误码 18024）的报错。
- **问题（Question）**：如何让用户**主动、随时**看到自己的上传额度与已用量，而不是撞墙后才知道？

**答案**：在用户账户菜单（点击左下角头像弹出的弹窗）里，展示一条「已使用 X GB / 上限 Y GB」的额度条，由系统配置开关控制是否启用。

---

## 二、做成什么样（目标与非目标）

**目标（In Scope）**
1. 用户可在工作台账户菜单里看到**知识空间文件上传**的"已用 / 上限（GB）"。
2. 额度紧张时进度条**变色预警**（橙 → 红）。
3. "无限制"角色有明确、不误导的呈现。
4. 是否展示由系统配置开关控制，**默认关闭**，需要时打开。

**非目标（Out of Scope，本期不做）**
1. 不改动任何配额**规则/校验逻辑**（后端仍是唯一权威拦截方）。
2. 不展示角色的另两项额度（创建频道数 / 加入知识空间数）——本期只聚焦存储容量。
3. 不做用量趋势、历史曲线、到量通知。
4. 不让展示条参与任何**鉴权/拦截**（它只是前置 UX 提示）。

---

## 三、核心方案（四根支柱，MECE）

### 支柱 1 · 数据：复用既有接口，后端零改动

- 后端已存在 `GET /api/v1/quota/effective`（`role/api/endpoints/quota.py`，鉴权 `Depends(LoginUser.get_login_user)`，**任意登录用户**可调）。
- 它对每种资源返回 `EffectiveQuotaItem`：`{resource_type, role_quota, tenant_quota, tenant_used, user_used, effective}`。取 `resource_type === "knowledge_space_file"` 一项即可：
  - `user_used` = 已用（**GB**）
  - `effective` = 有效上限（**GB**），`-1` = 无限制
- **单位关键点**：该资源在后端已做 `bytes / 1024³` 换算（`quota_service.py`），前端**无需任何字节换算**，直接展示 GB。
- **前端基础设施也已就绪**：`~/api/quota.ts` 已封装接口、`~/hooks/useEffectiveQuota.ts` 已在拉这份数据、资源类型枚举已含 `knowledge_space_file`。→ 本期本质只是"把已有数据渲染出来"。

### 支柱 2 · 展示：账户菜单里的额度条

- **位置**：全局用户账户菜单 `UserPopMenu`（rail 桌面弹窗 + drawer 移动抽屉两个变体），放在用户名下方、菜单项分隔线之上，作为"账户状态"。
- **组件**：新增 `~/components/StorageQuotaBar.tsx`，复用 `~/components/ui/Progress`。三态呈现规则（MECE）：

| 状态 | 判定 | 呈现 |
|---|---|---|
| 正常 | `effective > 0` 且已用 < 80% | 品牌蓝进度条 + `已使用 X GB / Y GB` |
| 预警 | 已用 ∈ [80%, 100%) | 进度条转**橙** `#ff7d00` |
| 超限 | 已用 ≥ 100% | 进度条转**红** `#f53f3f`（满格） |
| 无限制 | `effective === -1` | `已使用 X GB / 无限制`，**不渲染进度条** |
| 未就绪/未启用 | loading / 无该项数据 / 开关关 | **渲染 null**，不闪烁、不占位 |

- **格式**：GB 数值 2 位小数后去尾零（`0.09` / `82.4` / `100` / `2.5`）。
- **多语言**：`com_knowledge.storage_quota_title / _used / _unlimited` 三键，覆盖 zh-Hans / en / ja。

### 支柱 3 · 刷新：迁 react-query，共享缓存 + 焦点刷新

- 将 `useEffectiveQuota` 内部由 `useState + useEffect` 改为 `useQuery`（`queryKey ['quota','effective']`，`staleTime 30s`），**对外返回结构 `{ quotas, loading, refresh, getEffective, isOverQuota }` 完全不变**。
- 收益：额度条与既有 3 个消费方（`knowledge/index`、`KnowledgeSpacePreviewDrawer`、`Subscription`）**共享一次缓存拉取**；借 react-query 默认 `refetchOnWindowFocus`，用户上传后切回来额度条**自动更新**。
- 因 3 个消费方只用了 `isOverQuota`，此改造**零破坏**。

### 支柱 4 · 开关：系统配置控制，默认关

- 复用现成 `knowledge_space` 配置段（同段已有 `tree_structured_directory_display`），新增 `storage_quota_display`，默认 `false`。
- 下发管线原样复用：`initdb_config.yaml` → `workstation/api/endpoints/config.py` 拼进 `ret["knowledge_space"]` → client `bsConfig.knowledge_space.storage_quota_display`。
- 组件读该标志，非 `true` 直接 `return null`。管理员在「系统 → 系统配置」`knowledge_space:` 段下加 `storage_quota_display: true` 保存即开启（100s Redis TTL + 前端硬刷新生效）。

---

## 四、关键决策与取舍

1. **上限口径取 `effective`（≈角色配额）**：该接口计算 `effective` 时租户侧读 `tenant_config["knowledge_space_file"]` 而未做 `storage_gb` 别名换算，故展示值实际≈**角色配额上限**，不扣减企业租户已用存储。对"我的额度"展示**稳定、直观**；如需反映租户剩余，属可选后端跟进。
2. **展示位置放在全局账户菜单**：`UserPopMenu` 是全局组件，故额度条在所有页面账户菜单可见。判断依据：这是**账户级**存储信息，随处可查更有价值。
3. **开关默认关**：作为按需能力，避免默认对所有部署暴露；`storage_quota_display` 归入 `knowledge_space` 配置段，语义与下发管线均自然复用。

---

## 五、交付与验证（历史记录）

**改动清单（9 个代码文件）**

| 层 | 文件 | 改动 |
|---|---|---|
| 前端 | `components/StorageQuotaBar.tsx` | 新增额度条组件（含开关门控） |
| 前端 | `layouts/UserPopMenu.tsx` | rail + drawer 两变体挂载 |
| 前端 | `hooks/useEffectiveQuota.ts` | 内部迁 react-query（签名不变） |
| 前端 | `locales/{en,zh-Hans,ja}/translation.json` | 三语文案 |
| 前端 | `types/chat/config.ts` | 配置类型加 `storage_quota_display` |
| 后端 | `workstation/api/endpoints/config.py` | 读并下发开关 |
| 后端 | `initdb_config.yaml` | 默认 `storage_quota_display: false` |

**验证结论**：tsc 改动文件零报错、`npm run build` 通过、114 实测符合预期（含预警变色、无限制态、开关生效）。

---

## 六、当前状态与恢复

- 客户暂不需要 → beta4 已 rebase 移除本功能；完整实现冻结在备份分支 **`feature/knowledge-space-quota-display`**（origin + 展示提交 `5d23e36a8` + 开关提交）。
- 恢复方式：从该分支 `cherry-pick` 两个提交，或整分支 merge/diff 回目标分支。
