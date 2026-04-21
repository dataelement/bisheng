---
globs: ["src/frontend/platform/**"]
trigger: always_on
---

# Platform Frontend Development Rules (src/frontend/platform/)

## Tech Stack
Vite + React 18 + TypeScript + TailwindCSS 3 + Radix UI (bs-ui) + Zustand + React Context + react-i18next + react-router-dom v6 + @xyflow/react + axios (wrapped in `@/controllers/request.ts`)

## Mandatory Rules
- **TypeScript only**: All new files must use `.ts` / `.tsx`.
- **Functional Components**: Use Hooks; class components are prohibited.
- **Path Aliases**: Use `@/` for absolute imports (maps to `src/`).
- **HTTP Requests**: Must use `@/controllers/request.ts`. Do not import `axios` directly. API modules in `@/controllers/API/`.
- **State Management**: Zustand stores in `@/store/` for cross-page state. React Context (`@/contexts/`) for UI-scoped state (alerts, theme, tabs). Do not introduce new state libraries.
- **UI Components**: Use `@/components/bs-ui/` (Radix-based). Icons from `@/components/bs-icons/`. Do not introduce new UI libraries.
- **Code Comments**: All comments must be in English.
- **Component Size**: Keep individual components under 600 lines. Extract sub-components or custom hooks when exceeded.
- **Toast Notifications**: `import { toast } from "@/components/bs-ui/toast/use-toast"; toast({ title, variant: 'error' | 'success', description })`.
- **Confirm Dialogs**: `import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"`.
- **i18n**: Use `useTranslation()` from `react-i18next`. Locale files at `public/locales/{en-US,zh-Hans,ja}/{ns}.json`. Namespaces: bs, flow, model, tool, dashboard, knowledge.

## Coding Style
- **Naming**: `interface` for Props; `type` for internal types. PascalCase for components, camelCase for utilities/hooks.
- **Event Handling**: `handleXxx` for internal logic, `onXxx` for props.
- **Any Type**: Minimize usage. If necessary, add `// eslint-disable-next-line` with a brief explanation.
- **Exports**: Named exports (`export function`), no default exports for components.

## API Layer Pattern
```typescript
// @/controllers/API/xxx.ts
import axios from "@/controllers/request"
export async function getSomething(): Promise<SomeType> {
  return await axios.get(`/api/v1/something`)
}

// Component usage
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { getSomething } from "@/controllers/API"
captureAndAlertRequestErrorHoc(getSomething()).then(res => { ... })
```

## Known Pitfalls
- **403 Errors**: Handled automatically in the response interceptor. No manual handling needed.
- **MinIO Image Proxy**: Vite `fileServiceTarget` must match backend `config.yaml` `object_storage.minio.sharepoint`, otherwise image requests get 403.
