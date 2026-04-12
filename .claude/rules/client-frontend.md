---
globs: ["src/frontend/client/**"]
trigger: always_on
---

# Client Frontend Development Rules (src/frontend/client/)

## Tech Stack
Vite + React 18 + TypeScript + TailwindCSS 3 + Radix UI (shadcn/ui) + Recoil + react-i18next + react-router-dom v6 + lucide-react + axios (wrapped in `~/api/request.ts`)

## Mandatory Rules
- **TypeScript only**: All new files must use `.ts` / `.tsx`.
- **Functional Components**: Use Hooks; class components are prohibited.
- **Path Aliases**: Use `~/` for absolute imports (equivalent to `@/`, both map to `src/`).
- **HTTP Requests**: Must use `~/api/request.ts`. Do not import `axios` directly.
- **State Management**: Use Recoil (`~/store/`). Context or other solutions are prohibited for new state.
- **UI Components**: Use `~/components/ui/` (Radix-based). Do not introduce new UI libraries.
- **Code Comments**: All comments must be in English.
- **Component Size**: Keep individual components under 600 lines. Extract sub-components or custom hooks when exceeded.
- **Toast Notifications**: Use `const { showToast } = useToastContext(); showToast?.({ message, severity: 'error' | 'success' })`.
- **i18n**: Use `useLocalize()` from `~/hooks`. Locale files at `src/locales/{en,zh-Hans,ja}/translation.json`. New keys use nested namespace format (see `/i18n-localizer` skill).

## Coding Style
- **Naming**: `interface` for Props; `type` for internal types. PascalCase for components, camelCase for utilities/hooks.
- **Event Handling**: `handleXxx` for internal logic, `onXxx` for props.
- **Any Type**: Minimize usage. If necessary, add `// eslint-disable-next-line` with a brief explanation.
- **Exports**: Named exports (`export function`), no default exports for components.

## Known Pitfalls
- **403 Errors**: Handled automatically in the response interceptor with redirection. No manual handling needed in business logic.
