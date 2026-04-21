# Bisheng Development Guide

Monorepo layout:
- `src/backend/` — Python FastAPI backend (uv-managed, `.venv/` in dir)
- `src/frontend/client/` — end-user chat app (bishengchat)
- `src/frontend/platform/` — admin / builder console

Client and platform are two distinct React apps with different state libs / build tooling. Do **not** mix their conventions — scope rules by directory.

---

## Frontend — Client (`src/frontend/client/`)

### Tech stack
Vite 6 + React 18 + TypeScript + TailwindCSS 3 + Radix UI (shadcn/ui) + **Recoil** + **TanStack react-query v5** + react-router-dom v6 + lucide-react + axios (wrapped in `src/api/request.ts`)

### Mandatory rules
- **TypeScript only**: all new files use `.ts` / `.tsx`.
- **Functional components**: Hooks only; class components prohibited.
- **Path aliases**: use `@/` or `~/` (both resolve to `src/`) for absolute imports.
- **HTTP requests**: must use `src/api/request.ts`. Do not import `axios` directly.
- **State management**: Recoil atoms/selectors in `src/store/`. Context or other solutions are prohibited for new state.
- **UI components**: `src/components/ui/` (Radix-based). Do not introduce new UI libraries.
- **Code comments**: English only.
- **Component size**: keep components under 600 lines; split into sub-components or extract hooks when larger.
- **Toast notifications**: `const { showToast } = useToastContext(); showToast?.({ message, severity: 'error' | 'success' })`.

### Coding style
- **Naming**: `interface` for Props; `type` for internal types. PascalCase for components; camelCase for utilities/hooks.
- **Event handlers**: `handleXxx` for internal logic, `onXxx` for props.
- **Any type**: minimize. If necessary, add `// eslint-disable-next-line` with a brief reason.

### Known pitfalls
- **403 errors**: handled automatically in the response interceptor (redirects). No manual handling needed in business logic.

---

## Frontend — Platform (`src/frontend/platform/`)

### Tech stack
Vite 5 + React 18 + TypeScript + TailwindCSS 3 + Radix UI + **Zustand** + **react-query v3** + react-router-dom v6 + @xyflow/react (workflow editor) + lucide-react + axios (wrapped in `src/controllers/request.ts`)

### Mandatory rules
- **TypeScript only**; functional components only.
- **Path aliases**: `@/` → `src/`.
- **HTTP requests**: use `src/controllers/request.ts`. Do not import `axios` directly.
- **State management**: **Zustand stores in `src/store/`** (NOT Recoil — that's the client app). Do not mix with Context for new state.
- **Server state**: react-query v3 API (`useQuery({ queryFn })` style, not v5). Check existing hooks before copying v5 patterns.
- **UI components**: `src/components/bs-ui/` (Radix-based).
- **Workflow editor**: `@xyflow/react` (not the legacy `react-flow-renderer`); custom nodes live in `src/CustomNodes/`.
- **Code comments**: English only.
- **Toast notifications**: `const { toast } = useToast(); toast({ variant: 'error' | 'success', description: '...' })` — different API from client.

### Coding style
- Same as client (Props=interface, internal types=type, PascalCase components, camelCase utils, handleXxx/onXxx).

---

## Backend (`src/backend/`)

- Python ≥ 3.10, managed by `uv` (lockfile `uv.lock`).
---

## Skills
Project-level skills under `.claude/skills/`:
- **i18n-localizer** — extract hardcoded Chinese strings, generate keys, sync en / zh-Hans / ja locale files.
- **react-component-refactor** — refactor overgrown React components (extract hooks, split sub-components).

Invoke via the Skill tool (`skill: "i18n-localizer"`) or trigger phrases like "国际化这个模块" / "重构这个组件".
