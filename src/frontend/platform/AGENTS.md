# Frontend Rules — Platform (Admin / Builder UI)

Auto-loaded when editing files in `src/frontend/platform/`.
Cross-app boundary + hard rules common to both apps: root `AGENTS.md §4`. The store-must-not-call-HTTP law: `docs/constitution.md` C7 (arch-guard RULE-6).

## Commands (cwd: `src/frontend/platform/`)

```bash
npm install
npm start -- --host 0.0.0.0                                          # dev server on :3001
VITE_PROXY_TARGET=http://localhost:8180 npm start -- --host 0.0.0.0  # commercial gateway proxy mode
```

## Tech Stack
Vite 5 + React 18 + TypeScript + TailwindCSS 3 + Radix UI (bs-ui) + **Zustand** + React Context + **react-query v3** + react-i18next + react-router-dom v6 + **@xyflow/react** + axios (wrapped in `@/controllers/request.ts`)

## Mandatory Rules
- **TypeScript only**: all new files `.ts` / `.tsx`.
- **Functional Components**: hooks only; class components prohibited.
- **Path Aliases**: `@/` → `src/`.
- **HTTP Requests**: must use `@/controllers/request.ts`; never import `axios` directly. API modules in `@/controllers/API/`.
- **State Management**: Zustand stores in `@/store/` (cross-page); React Context (`@/contexts/`) for UI-scoped state (alerts, theme, tabs). No new state libraries.
- **UI Components**: `@/components/bs-ui/` (Radix-based). Icons from `@/components/bs-icons/`. No new UI libraries.
- **Workflow editor**: `@xyflow/react` (**not** `react-flow-renderer`); nodes in `src/CustomNodes/`.
- **Code Comments**: English.
- **Component Size**: < 600 lines; extract sub-components or hooks when exceeded.
- **Toast**: `import { toast } from "@/components/bs-ui/toast/use-toast"; toast({ title, variant: 'error' | 'success', description })`.
- **Confirm Dialogs**: `import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"`.
- **i18n**: `useTranslation()` from react-i18next → `t()`. Locale files at `public/locales/{en-US,zh-Hans,ja}/{ns}.json`. Namespaces: bs, flow, model, tool, dashboard, knowledge.

## Coding Style
- **Naming**: `interface` for Props; `type` for internal types. PascalCase components, camelCase utilities/hooks.
- **Event Handling**: `handleXxx` for internal logic, `onXxx` for props.
- **Any Type**: minimize; if necessary add `// eslint-disable-next-line` with a brief reason.
- **Exports**: named exports (`export function`); no default exports for components.

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
- **403 Errors**: handled automatically in the response interceptor. No manual handling needed.
- **MinIO Image Proxy**: Vite `fileServiceTarget` must match backend `config.yaml` `object_storage.minio.sharepoint`, otherwise image requests get 403.
