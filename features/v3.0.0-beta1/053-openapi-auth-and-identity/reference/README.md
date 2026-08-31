# reference/ — 从 `3.0-vibe` 分支原样拷入的参考文档（只读、已知有过期内容）

| 文件 | 来源 | 状态 | 怎么用 |
|---|---|---|---|
| `vibe-049-spec.md` / `vibe-049-design.md` / `vibe-049-tasks.md` | `3.0-vibe:features/v3.0.0/049-openapi-auth-baseline/` | 2026-08-17 定稿，代码 Wave 1–2 已实现（33/76）。**排除项「个人访问令牌整条否决」已被 PRD v2.4 D13 推翻**；三扩展位 / 托管应用 / F051–F055 引用在 beta1 上不存在 | 底座（凭据 / 服务账号 / 管理界面 / 端点接入 / share-token）的决策与坑：**design D1–D13、坑 1–27 全部沿用**，差异见 `../design.md` §2.2 |
| `vibe-050-spec.md` | `3.0-vibe:features/v3.0.0/050-identity-modes/spec.md` | 已评审，无 design / 代码 | 身份传递的 AC 与 12 条决议，`../design.md` §5 沿用其决议 1–12 |
| `vibe-058-spec.md` | `3.0-vibe:features/v3.0.0/058-openapi-responses/spec.md` | 已评审，无 design / 代码；基于 PRD v2.1 写、后按 v2.3 D9 修订 | 日常模式会话的 AC 与 14 条决议；契约形态在 `../design.md` §7 定 |

**编号提醒**：vibe 上的 F049 / F050 与 beta1 的 `049-knowledge-space-children-read-optimization` / `050-unified-permission-settings` **不是同一个东西**。本目录内文件提到的 F049–F059 一律指 vibe 编号。
