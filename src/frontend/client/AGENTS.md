# Frontend Rules — Client (End-user Chat UI)

Auto-loaded when editing files in `src/frontend/client/`. Base path: `/workspace`.
Cross-app boundary + hard rules common to both apps: root `AGENTS.md §4` (single source — not repeated here). The store-must-not-call-HTTP law: `docs/constitution.md` C7 (arch-guard RULE-6).

## Commands (cwd: `src/frontend/client/`)

```bash
npm install
npm run dev    # dev server on :4001
```

## Tech Stack
Vite 6 + React 18 + TypeScript + TailwindCSS 3 + Radix UI (shadcn/ui) + **Recoil** + **react-query v4 (@tanstack)** + react-i18next + react-router-dom v6 + **lucide-react** + axios (wrapped in `~/api/request.ts`)

## Mandatory Rules (client-specific — common hard rules in root §4)
- **Path Aliases**: `~/` (or `@/`) → `src/`.
- **HTTP Requests**: wrapper is `~/api/request.ts`.
- **State Management**: Recoil (`~/store/`). Context or other solutions prohibited for new state.
- **UI Components**: `~/components/ui/` (shadcn / Radix-based).
- **Icons**: prefer `bisheng-icons` — `import { Outlined } from 'bisheng-icons'` → `<Outlined.Delete />` (variants `Outlined` / `Filled` / `Colored`). Use `lucide-react` ONLY as a fallback when `bisheng-icons` has no matching-semantic icon.
  - **⚠️ After upgrading `bisheng-icons`**, clear the Vite pre-bundle cache or new icons crash the page (`Element type is invalid`): `npm run dev -- --force` (or `rm -rf node_modules/.vite && npm run dev`). Its git-source `exports` field defeats Vite's dep-change detection, so the stale pre-bundled snapshot is served unless forced.
- **Toast**: `const { showToast } = useToastContext(); showToast?.({ message, severity: 'error' | 'success' })`.
- **i18n**: `useLocalize()` from `~/hooks` → `localize()`. Locale files at `src/locales/{en,zh-Hans,ja}/translation.json` (single file). New keys use nested namespace format (see `/i18n-localizer` skill).
- **Brand theme (blue⇄green)**: brand-colored UI MUST follow the theme — **never hardcode brand hex** (`#165DFF`/`#024DE3`/`#19B476`/`#187C54`…).
  - Use `blue-*` classes (they're re-pointed to `--brand-*` vars → auto-follow; `blue-*` means "brand", not literal blue) or `rgb(var(--brand-NNN))` in inline style/CSS.
  - **Primary filled button**: `<Button>` (default variant, already themed). Hand-rolled `bg-blue-500 text-white` MUST also add the `btn-brand-primary` class. Brand-tinted secondary: `<Button variant="secondaryBrand">`.
  - **Tints**: selection/active `bg-blue-500/[0.07]`, header `…/[0.05]`. Tailwind arbitrary values can't contain spaces: `rgb(var(--brand-500)/0.04)` ✅.
  - **Illustrations**: inline SVG, `fill`/`stroke` = `rgb(var(--illus-NNN))` (separate brighter palette, in `src/components/illustrations/`). SVG presentation attrs ignore `var()` → use inline `style`/className/CSS-mask, and `useId()` to dedupe gradient/clip ids.
  - **Do NOT theme**: semantic colors (success `#00b42a` / danger `#f53f3f` / warning `#ff7d00`), type colors (skill-purple, assistant-orange), third-party logos. Need a muted-but-themed brand color → `rgb(var(--brand-muted))`.
  - Full guide: `BRAND-THEME-HANDOFF.md`.
