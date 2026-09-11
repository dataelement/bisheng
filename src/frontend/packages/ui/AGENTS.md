# Component Library Rules — @bisheng/ui

Auto-loaded when editing files in `src/frontend/packages/ui/`.
Full design specs live in `docs/` (site: `pnpm dev:ui`); this file is the enforcement layer — hard rules only.

## Library Contract (permanent — violating components do not belong here)

- **Presentation-only.** Never import: state managers (Recoil/Zustand/jotai), HTTP/SSE/WS clients, react-router, or i18n (`useTranslation`/`useLocalize`). Data in via props, events out via callbacks, ALL text via props.
- **Source-shipped**: `exports` points at TS source; consumers compile it. No build step, no npm publish; apps consume via `workspace:*`.
- **Strict TS** (`strict: true` here, unlike the apps). No `any`; run `pnpm typecheck` before handing off.
- Icons from the `bisheng-icons` package only — never add icon components here.

## Design Tokens (SSOT discipline)

- `design-token.cjs` is the single source of truth for token NAMES + documented values (client re-exports it). `src/styles/tokens.css` + `tailwind-preset.cjs` are its runtime carriers.
- **`tailwind-preset.cjs` is the shared Tailwind theme** — client consumes it via `presets: [require('@bisheng/ui/tailwind-preset')]` and no longer declares the type scale / semantic colors / radius / shadow / z tiers / motion keyframes itself. A cross-app theme key belongs HERE, not in an app config; adding it to one app re-forks what this preset exists to unify. (platform has not adopted it yet.)
- **`src/styles/tokens.css` is the single definition of the runtime CSS custom properties.** client loads it from `main.jsx` (its `style.css` keeps only client-only vars) and the docs site from `rspress.config.ts` `preEntry`; there is no second copy to keep in sync. Override order is fixed INSIDE the file — `:root` first, then `.dark` / the ≤768px remap / `.theme-green` / `.illus-grey`, which tie with `:root` on specificity and win only by coming later. Do not reorder those blocks.
- Components consume the **semantic layer only** (`text-text-1…4`, `bg-fill-1…4`, `border-border-base`, `blue-*` = brand, `btn-*`, `success/warning/danger`). Primitives (`--arco-gray-N`) are intentionally not wired — never hardcode hex or reach around the semantic names.

## Interaction Rules (from 多端适配原则 / 组件-Button按钮 §5.5)

- Write plain `hover:` classes ONLY — `future.hoverOnlyWhenSupported` disables them on touch globally. **Never invent custom hover variant prefixes** (tailwind-merge can't dedupe them; business-page `hover:` overrides silently lose).
- Touch press feedback via `coarse-pointer:active:`; hover/active shade stays **within the current base color's ramp** (brand bg → brand ramp, red → red ramp; never gray out cross-palette).
- Small touch targets get the invisible ≥44px hot zone via `btn-touch-hit` (component-internal; never hand-rolled per page).

## Definition of Done for a new/migrated component

1. Component under `src/components/<Name>/` + export in `src/index.ts`.
2. Docs page `docs/components/<name>.mdx` — demos import from `'@bisheng/ui'` (never `~/…` app paths); scenario-per-demo, simplest first. Two lines make it show up correctly, and both are checked by the site itself:
   - front matter `status: done | draft | todo` (+ optional `statusNote:`) — the only hand-written cell in the 组件总览 table (everything else is derived from the page; never edit that table by hand);
   - a sidebar entry in `client/rspress.config.ts` → `themeConfig.sidebar['/components/']`. Miss it and 组件总览 renders a red 「没挂进侧边栏」 row for the page.
3. Consuming app keeps a re-export shim at its old path (e.g. client `~/components/ui/Button.tsx`) so call sites stay unchanged.
4. `docs/组件-*.md` spec updated if behavior/API changed (spec and code must not drift).
