# React Component Refactoring Guidelines

This document defines the standard refactoring methodology for this project. Follow these rules when adding new features or refactoring existing modules to keep code maintainable and consistent.

---

## 1. Directory Structure Rules

### When to create a sub-directory
- When a feature area has **3+ closely related component files**, group them into a named sub-directory.
- The directory name should describe the **feature**, not the component (e.g., `CreateChannel/`, not `CreateChannelDrawerFiles/`).

### Standard layout

```
src/pages/ModuleName/
├── index.tsx                    # Page entry, layout & routing
├── moduleUtils.ts               # Pure utility functions (validation, data transform, payload builders)
├── hooks/                       # Custom hooks (one hook per file)
│   ├── useFeatureForm.ts        # Form state & handlers
│   └── useDataManager.ts        # Data fetching, filtering, CRUD
├── FeatureA/                    # Feature sub-directory
│   ├── MainComponent.tsx        # Top-level feature component
│   ├── SubComponentA.tsx        # Extracted sub-component
│   └── SubComponentB.tsx        # Another extracted sub-component
└── FeatureB/
    └── ...
```

### Import path conventions
- Components within the same feature directory use relative imports: `./SubComponent`
- Hooks are imported from `../hooks/useXxx`
- Utils are imported from `../moduleUtils`

---

## 2. Component Splitting Rules

### When to extract a sub-component
- An inline function component is **>120 lines**.
- A block of JSX is **self-contained** (has its own props/state concept).
- A component is **reused** or could be tested independently.

### How to extract
1. Create a new file in the same feature directory.
2. Define a clear `Props` interface and export it.
3. Move the component body; keep UI unchanged.
4. Import and use in the parent — the parent JSX should only change the component reference.

### Naming conventions
- Sub-component file name = component name (PascalCase): `SubChannelBlock.tsx`
- Always `export function ComponentName` (named exports, no default).
- Co-export related types/interfaces that are tightly coupled.

---

## 3. Hook Extraction Rules

### When to extract a hook
- A component has **≥8 `useState` calls**.
- There is a block of **`useEffect` + state** that handles data loading or side effects.
- Multiple event handlers share the same state and form a logical unit.

### Naming conventions
- File: `hooks/useFeatureName.ts` (camelCase with `use` prefix)
- Hook function: `useFeatureName`
- Return a flat object: `{ stateA, setStateA, handlerB, ... }`
- The consuming component accesses via `const form = useFeatureName(...)` and references `form.stateA`

### What belongs in a hook
| Belongs in Hook | Stays in Component |
|---|---|
| `useState` declarations | JSX rendering |
| Derived/computed values (`useMemo`) | Layout-specific handlers (e.g., scroll position) |
| Data loading `useEffect`s | Event handlers that only call `showToast` |
| CRUD handlers (add/remove/update) | Direct UI event wiring |
| Form reset logic | |

### What does NOT belong in a hook
- UI library calls (`showToast`, `localize`) — pass as params if needed
- API layer definitions — keep in `~/api/`
- Component-specific render helpers

---

## 4. Utility / Validation Extraction Rules

### When to extract to `moduleUtils.ts`
- **Validation functions** that check form data and return error messages.
- **Payload builders** that transform form data into API payloads.
- **Data transformers** that convert between API types and UI types.
- **Pure functions** that don't depend on React state or hooks.

### Function signature pattern
```typescript
// Validation: returns error message or null
export function validateFormData(
    data: FormDataType,
    localize: (key: string) => string
): string | null;

// Payload builder: transforms form → API payload
export function buildPayload(data: FormDataType): ApiPayloadType;
```

### Rules
- Keep functions pure — no side effects.
- Accept `localize` as a parameter for i18n error messages.
- The component is responsible for displaying errors (toast/UI).

---

## 5. Refactoring Checklist

When refactoring a module, follow this order:

1. **[ ] Analyze** — Count lines, identify state density, find inline sub-components.
2. **[ ] Restructure directories** — Group files by feature if threshold met.
3. **[ ] Extract sub-components** — Move inline components to separate files.
4. **[ ] Extract hooks** — Pull state management into `hooks/useXxx.ts`.
5. **[ ] Extract utilities** — Move validation and data transforms to `moduleUtils.ts`.
6. **[ ] Clean imports** — Remove unused imports, verify all paths resolve.
7. **[ ] Verify** — Run `yarn start` to ensure compilation succeeds.

### DO NOT change during refactoring
- **UI/JSX structure** — no visual changes.
- **CSS classes** — keep exact same styling.
- **API layer** — do not restructure API files unless explicitly requested.
- **i18n hardcoded strings** — handle separately with the `i18n-localizer` skill.

---

## 6. File Size Guidelines

| File Type | Target Lines | Action if exceeded |
|---|---|---|
| Page component (`index.tsx`) | < 600 | Extract sub-sections |
| Feature component | < 600 | Extract hooks & sub-components |
| Custom hook | < 200 | Split by concern |
| Utility file | < 300 | Split by domain |
| Sub-component | < 150 | Already well-scoped |

---

## 7. Data Flow Conventions

```
API Layer (~/api/)
    ↕  raw types
Hooks (hooks/useXxx.ts)
    ↕  processed state + handlers
Component (Feature/Main.tsx)
    ↕  props
Sub-components (Feature/Sub.tsx)
```

- **Unidirectional**: Parent → Child via props; Child → Parent via callback props.
- **No prop drilling beyond 3 levels** — if deeper, use a hook or context.
- **Hooks own the state**, components own the rendering.
