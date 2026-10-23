# Frontend foundation

The workspace owns shared dependency versions in `pnpm-workspace.yaml` (`catalog`). Both apps extend these configurations while retaining independent routes, state libraries, build chunks and tests.

- `tsconfig.base.json`: source-only, no declaration emit, bundler module resolution, shared JSX/target defaults. App configs retain their strict legacy gate and aliases.
- `eslint.mjs`: shared lint policy. Frozen imports, request-wrapper exemptions and legacy suppressions remain app-local.
- `postcss.cjs`: shared Tailwind 3 / Autoprefixer pipeline. Each app's content paths and feature plugins stay in its Tailwind config; design tokens/fonts/interactions come from `@bisheng/ui/tailwind-preset`.
- `vite.ts`: workspace env defaults plus app-local overrides, proxy configuration and MinIO diagnostics. Process environment takes precedence; the merged values are also injected into browser code using each app's existing public env prefixes. API configuration prefers `VITE_API_PROXY_TARGET`; legacy platform `VITE_PROXY_TARGET` and client `VITE_DEV_API_TARGET` still work. MinIO prefers `VITE_MINIO_PROXY_TARGET`; client also accepts `VITE_DEV_MINIO_TARGET`. Gateway license traffic keeps its dedicated `VITE_GATEWAY_PROXY_TARGET`.
- `vitest.config.mts`: node-only configuration tests, without the applications' DOM setup. Run `pnpm test:config` at `src/frontend/`.

Keep both dev servers on their documented ports (3001/4001). API and object storage targets are separate; the MinIO target host must match the host used to sign object URLs. Restart Vite after dependency upgrades to discard prebundled modules.

SheetJS is pinned to **0.20.3** in the workspace catalog for client, platform and
`@bisheng/file-viewers`. Use the official versioned tarball from
https://cdn.sheetjs.com/xlsx-0.20.3/xlsx-0.20.3.tgz, not the stale npm `xlsx`
release (0.18.5). The pnpm lockfile records SHA-512 integrity. This release includes
the fixes for CVE-2023-30533 (prototype pollution, fixed in 0.19.3) and
CVE-2024-22363 (ReDoS, fixed in 0.20.2). Upgrades must update the catalog and lockfile
together and rerun `pnpm test:config` plus both production builds. Package source:
https://docs.sheetjs.com/docs/getting-started/installation/nodejs/.

Keep `xlsx-populate` for the shared viewer's image extraction; this security update
does not consolidate Excel libraries or change preview behavior.
