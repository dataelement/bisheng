# Frontend foundation consolidation

Approved scope: consolidate platform/client foundation configuration on feat/3.0.0 and upgrade compatible stable npm dependencies. This is an internal refactor/dependency maintenance track (SDD Guide §1); application URLs, API contracts, state libraries and persistence remain unchanged.

## Decisions

- Shared PostCSS, ESLint policy and TypeScript base live in frontend/config. App-specific aliases, test globals, legacy strict exemptions and import restrictions remain local.
- Both apps use the Vite 6.4 security-maintained line and Babel React plugin. Keep the app-specific build chunks, PWA, SVGR, editor assets, paths and ports. Share proxy safety and workspace/app environment loading; preserve old env variable names as fallbacks.
- React 18, Tailwind 3, TypeScript 5 and Node 20 remain. Compatible stable versions are queried from the official npm registry; avoid a blind latest upgrade. React 19/Tailwind 4/TS 7/Vite 8, archived state libraries, Jest migration and PDF API migration require separate work.
- Use catalog for common dependencies; both apps and the source-shipped UI use tailwind-merge 2.6 with the semantic font-size extension. Remove outdated Vite/Rollup downgrade overrides after checking builds, retain unrelated targeted security overrides.
- Shared preset owns fonts/type/color/radius/interaction semantics. Preserve legacy color aliases needed by existing pages; remove duplicate Tailwind directives and global scrollbar overrides, adopt system fonts. Evaluate global important removal against generated CSS and runtime behavior; record concrete exceptions rather than silently claiming full visual convergence.
- No automatic commit/push for this new request. No test checklist document.

## Tasks

- [x] Capture typecheck baseline, audit actual resolved configuration and stable registry versions.
- [x] Extract shared lint/PostCSS/TS config; remove stale TS output and path options.
- [x] Share Vite proxy and environment helpers; unify Vite/compiler with app-specific plugins intact.
- [x] Consolidate foundation styles and class merging; verify typography/color coexistence, important and scroll behavior.
- [x] Upgrade/catalog compatible packages and regenerate lockfile; verify reproducible install.
- [x] Run configuration/proxy regression tests, relevant app tests, typecheck/lint/i18n, both production builds, and independent review. Record legacy failures and deferred major upgrades.

## Baseline

- Clean start at 8de501334 on feat/3.0.0.
- Installed: Vite platform 5.4.21/client 6.4.1; both TS 5.9.3, Tailwind 3.4.19, React 18.3.1, PostCSS 8.5.22.
- Platform typecheck passes; client baseline captured in /tmp/config-baseline-bishengchat-types.log.
- Registry audit: /tmp/bisheng-dependency-audit.json. Official guidance: https://vite.dev/releases ; https://www.npmjs.com/package/tailwind-merge .

## Implementation and review

- Common configuration lives in `src/frontend/config/`. Vite helpers mirror merged public-prefix env values to browser code as well as proxy configuration; unprefixed values are never injected. Old API/MinIO names remain supported.
- Single platform Tailwind entry now imports App.css plus legacy business styles. Removed global important and all global scrollbar overrides, the redundant font overrides and unused font-face. Shared preset owns the system font and explicit no-scrollbar utility. Legacy feature colors/HSL aliases remain per app to avoid changing existing business semantics.
- Class merging uses one shared v2.6 implementation through @bisheng/ui/cn. The headlessui anchor type now derives from its public ListboxOptions props, required by bundler resolution.
- Catalog aligns React 18.3.1, TS 5.9.3, Tailwind 3.4.19, Vite 6.4.5, plugin-react 4.7.0, tailwind-merge 2.6.1, PostCSS 8.5.31, Autoprefixer 10.6.1, Axios 1.20.0, DOMPurify 3.4.17 and compatible Radix versions. Rollup 4.64.12 replaces the old downgrade. Rspress stays on 1.47.2; platform has its required testing-library/dom 10.4.2.
- Independent reviewer caught the remaining App.css Tailwind/scrollbar rules. Both corrected; regression observed red (2 failed / 9 passed), then green (11 passed). Reviewer rechecked fixes and public env filtering; no actionable issue remains.
- Initial verification: platform 46 suites / 237 tests and both builds pass. Client Jest initially exposed the documented unbuilt optional canvas package after skip-scripts install: removed only the local broken jsdom peer link so the supported canvas-free fallback can run. No source workaround.
- Scoped source lint is clean; full lint remains the baseline platform 83 / client 89 errors, with no suppressions added. Platform/shared packages typecheck pass; client retains exactly the 4 pre-existing skill-center type errors. i18n parity passes.
- Frozen offline install proved the local cache was incomplete, not lockfile drift; following up with a clean online frozen install and final tests/builds.

## Final verification

- Clean online `pnpm install --frozen-lockfile --ignore-scripts --registry=https://registry.npmjs.org` passes; lockfile resolution is skipped and no peer mismatch is reported. This local verification intentionally skips third-party install scripts; the unchanged CI/Docker installation still uses normal lifecycle scripts.
- After the review fixes: configuration 11/11 pass, configuration strict types pass, both production builds pass (platform 35.02s / client 1m13s). Old bundle-size, editor eval and missing optional PWA icon glob warnings remain.
- No browser visual inspection was performed in this change. Review the platform's fonts, native scrollbars and CSS precedence on actual business pages before release; business-specific colors and themes are intentionally retained.

- Final client Jest verification: 3 suites / 14 tests pass after disabling the local unbuilt optional canvas peer links; total regression count 262 (237 platform + 14 client + 11 configuration). No suppression baselines were changed. User authorized commit and push to feat/3.0.0 after verification.
