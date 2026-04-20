---
trigger: always_on
---

# Bisheng Frontend Development Guide

## Tech Stack
Vite + React 18 + TypeScript + TailwindCSS 3 + Radix UI（shadcn/ui） + Recoil + react-query + react-router-dom v6 + lucide-react + axios (wrapped in `src/api/request.ts`)

## Mandatory Rules
- **TypeScript only**: All new files must use `.ts` / `.tsx`.
- **Functional Components**: Use Hooks; class components are prohibited.
- **Path Aliases**: Use `@/` (equivalent to `~/`) for absolute imports.
- **HTTP Requests**: Must use `src/api/request.ts`. Do not import `axios` directly.
- **State Management**: Use Recoil (`src/store/`). Context or other solutions are prohibited for new state.
- **UI Components**: Use `src/components/ui/` (Radix-based). Do not introduce new UI libraries.
- **Code Comments**: All comments must be in English.
- **Component Size**: We recommend keeping individual components under 600 lines. Components that exceed this guideline may be split into sub-components or refactored using custom hooks.
- **Toast Notifications**: Use `const { showToast } = useToastContext(); showToast?.({ message, severity: 'error' | 'success' })`.

## Coding Style
- **Naming**: `interface` for Props; `type` for internal types. PascalCase for components, camelCase for utilities/hooks.
- **Event Handling**: `handleXxx` for internal logic, `onXxx` for props.
- **Any Type**: Minimize usage. If necessary, add `// eslint-disable-next-line` with a brief explanation.

## Known Pitfalls
- **403 Errors**: Handled automatically in the response interceptor with redirection. No manual handling needed in business logic.

## Modules / Knowledge
<!-- Add module documentation links here for quick context alignment -->

## Skills
<!-- Custom agent skills and workflows -->