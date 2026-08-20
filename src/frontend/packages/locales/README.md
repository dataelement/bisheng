# @bisheng/locales

Single source of truth for copy shared by both frontend apps. Domains live under
`src/<domain>/<lang>.json` (languages: `zh-Hans`, `en`, `ja` — all three are
mandatory for every key).

`scripts/build.mjs` compiles each domain into the artifacts the apps load at
runtime (the apps' i18n runtimes are untouched):

| Domain | platform artifact | client artifact |
|---|---|---|
| `api_errors` | `platform/public/locales/<lng>/api_errors.json` (lazy i18next namespace, addressed as `api_errors:<code>`) | `client/src/locales/<lng>/api_errors.gen.json` (merged into the bundled resources, addressed as `api_errors.<code>`) |

Rules:

- **Edit the source only.** Artifacts are generated, committed, and verified in
  CI (`pnpm --filter @bisheng/locales check`); hand edits fail the gate.
- **New error-code copy goes here**, never into an app-local locale file, and
  always in all three languages at once.
- Regeneration is automatic on `pnpm dev` / `pnpm build` (pre-scripts). While
  editing copy with a dev server running: `pnpm --filter @bisheng/locales watch`.
- Migrating another duplicated domain (e.g. knowledge) = add `src/<domain>/`,
  add its `TARGETS` entries in `scripts/build.mjs`, delete the app-local copies.
