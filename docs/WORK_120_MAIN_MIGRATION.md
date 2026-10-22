# Kinyoo work-120 migration

Source: `feat/bisheng-work-120` at `de60988d7`.
Target baseline: `origin/feat/bisheng-work-120-main` at `7e573b3a6`.

## Scope

The user approved all 27 non-merge commits authored by Kinyoo that are not ancestors of the target baseline. 26 were cherry-picked with source hashes in their commit messages. Source `994fde7ff` was skipped: the target already has the identical API example builder content under `apiExampleSnippets.ts`, rather than `apiRequestExampleBuilders.ts`.

No backend changes or unrelated release-line commits were merged. Nothing was pushed.

## Conflict decisions

- Permission roster search: retain the Outlined search icon and semantic color.
- Message attachments: retain target React hooks and add the attachment icon import.
- Markdown: retain target source-preview callback alongside compact image rendering.
- Layout: retain target model-resolution/default-skill logic and organization-KB pagination while applying the new layout/tool-selection composition.
- Article dock: preserve target per-surface model isolation and automatic selection repair when extracting DockInput.
- Locales: three-way merge source deltas; all pre-existing target translation leaf keys are retained in en, ja and zh-Hans.
- ESLint suppressions: retain target suppressions during layout conflict; do not manually add exceptions.

## Approved desktop dependencies

The user explicitly approved the smallest required desktop bridge dependencies, not the other author's complete chat visual redesign. Source snapshots at `e85f8ef21` supply desktopEmbedding, useDesktopAppearance, useDesktopConversation, useDesktopNavigation and their tests, plus DesktopShellBridge and its test. Their original introduction is traceable to `562ee4e6a` and `93d4df622`.

The integration follow-up mounts DesktopShellBridge in MainLayout, suppresses duplicate web sidebar chrome in embedded desktop mode, and connects conversation landing-state reporting. Existing web chat model behavior is retained.

## Verification

- `git diff --check`: passed before integration commit.
- Target locale leaf-key preservation: passed for all three languages.
- Backend diff against target baseline: empty.
- Frontend lint, typecheck and focused desktop Jest checks: launched; final outcomes reported in the delivery summary.
