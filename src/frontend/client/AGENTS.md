# Frontend Rules — Client (End-user Chat UI)

Auto-loaded when editing files in `src/frontend/client/`. Base path: `/workspace`.
Cross-app boundary + hard rules common to both apps: root `AGENTS.md §4`. The store-must-not-call-HTTP law: `docs/constitution.md` C7 (arch-guard RULE-6).

## Commands (cwd: `src/frontend/client/`)

```bash
npm install
npm run dev    # dev server on :4001
```

## Tech Stack
Vite 6 + React 18 + TypeScript + TailwindCSS 3 + Radix UI (shadcn/ui) + **Recoil** + **react-query v5** + react-i18next + react-router-dom v6 + **lucide-react** + axios (wrapped in `~/api/request.ts`)

## Mandatory Rules
- **TypeScript only**: all new files `.ts` / `.tsx`.
- **Functional Components**: hooks only; class components prohibited.
- **Path Aliases**: `~/` (or `@/`) → `src/`.
- **HTTP Requests**: must use `~/api/request.ts`; never import `axios` directly.
- **State Management**: Recoil (`~/store/`). Context or other solutions prohibited for new state.
- **UI Components**: `~/components/ui/` (shadcn / Radix-based). Icons from `lucide-react`. No new UI libraries.
- **Code Comments**: English.
- **Component Size**: < 600 lines; extract sub-components or hooks when exceeded.
- **Toast**: `const { showToast } = useToastContext(); showToast?.({ message, severity: 'error' | 'success' })`.
- **i18n**: `useLocalize()` from `~/hooks` → `localize()`. Locale files at `src/locales/{en,zh-Hans,ja}/translation.json` (single file). New keys use nested namespace format (see `/i18n-localizer` skill).

## Coding Style
- **Naming**: `interface` for Props; `type` for internal types. PascalCase components, camelCase utilities/hooks.
- **Event Handling**: `handleXxx` for internal logic, `onXxx` for props.
- **Any Type**: minimize; if necessary add `// eslint-disable-next-line` with a brief reason.
- **Exports**: named exports (`export function`); no default exports for components.

## Known Pitfalls
- **403 Errors**: handled automatically in the response interceptor with redirection. No manual handling needed in business logic.
