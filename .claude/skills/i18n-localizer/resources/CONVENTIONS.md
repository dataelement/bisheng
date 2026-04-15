# i18n Conventions for This Project

## Technology Stack

- **Library**: `i18next` (v24+) + `react-i18next` (v15+) + `i18next-browser-languagedetector` (v8+)
- **Supported Languages**: `en` (English), `zh-Hans` (Simplified Chinese), `ja` (Japanese)

## File Locations

| File | Purpose |
|------|---------|
| `src/locales/i18n.ts` | i18next initialization and configuration |
| `src/locales/en/translation.json` | English translations |
| `src/locales/zh-Hans/translation.json` | Simplified Chinese translations |
| `src/locales/ja/translation.json` | Japanese translations |
| `src/hooks/useLocalize.ts` | Custom hook wrapping `useTranslation` with Recoil lang state |

## Key Naming Convention

### Domain Namespaces

Keys are organized by domain namespace. Each domain is a top-level object in the JSON:

| Namespace | Scope |
|-----------|-------|
| `com_ui` | General UI elements (buttons, labels, status text) |
| `com_nav` | Navigation, sidebar, top bar, menus |
| `com_auth` | Authentication (login, register, password) |
| `com_endpoint` | LLM endpoint configuration |
| `com_sop` | SOP / task execution features |
| `com_knowledge` | Knowledge base management |
| `com_tools` | Tool panel and tool-related features |
| `com_agent` | Agent-related features |
| `com_app` | App center / agent marketplace |
| `com_invite` | Invitation features |
| `com_linsight` | Linsight-specific features |
| `com_label` | Label / tagging features |
| `com_search` | Search-related features |
| `com_file` | File management |
| `com_message` | Chat message related |
| `com_segment` | Mode segment features |

### Key Naming Rules

1. Use **snake_case** (all lowercase, underscores between words).
2. Keep keys **descriptive but concise** (2-5 words).
3. For similar operations, use consistent suffixes: `_success`, `_error`, `_failed`, `_confirm`, `_placeholder`, `_title`, `_desc`.
4. Do NOT include the translated text in the key name.

## JSON File Format

> [!IMPORTANT]
> **Legacy keys** (flat format like `"com_ui_cancel": "Cancel"`) MUST be left as-is. Do NOT refactor them.
> **New keys** MUST use the nested namespace format described below.

### New Key Format (Nested)

New keys use nested objects grouped by domain namespace:

```json
{
  "com_ui_cancel": "Cancel",
  "com_ui_delete": "Delete",

  "com_knowledge": {
    "space_create_success": "Knowledge space created",
    "space_deleted": "Space has been dissolved",
    "folder_max_depth": "Folder depth limit reached (10 levels)",
    "drop_to_upload": "Drop files here to upload"
  }
}
```

- Old flat keys like `"com_ui_cancel"` stay untouched at root level.
- New keys go inside their namespace object (e.g. `com_knowledge.space_create_success`).
- Within each namespace object, keys are sorted alphabetically.
- Namespace objects are placed after all legacy flat keys, also sorted alphabetically.

### Interpolation

- Use `{{0}}`, `{{1}}` for positional args; `{{name}}` for named args.
- Use `$t(keyName)` to reference other keys inline.

## Usage in Components

### Import Pattern

```tsx
// Preferred: via the barrel export
import { useLocalize } from "~/hooks";

// Alternative: direct import
import useLocalize from "~/hooks/useLocalize";
```

### Component Usage

```tsx
function MyComponent() {
    const localize = useLocalize();

    return (
        <div>
            {/* New nested key — use dot notation */}
            <h1>{localize("com_knowledge.title")}</h1>

            {/* Legacy flat key — unchanged */}
            <button>{localize("com_ui_cancel")}</button>

            {/* With interpolation */}
            <p>{localize("com_knowledge.files_count", { 0: fileCount })}</p>
        </div>
    );
}
```

### Toast Messages

```tsx
showToast({
    message: localize("com_knowledge.space_create_success"),
    severity: NotificationSeverity.SUCCESS
});
```

## Interpolation Examples

| Pattern | Locale Value | Code |
|---------|-------------|------|
| Positional | `"已选择 {{0}} 个文件（共 {{1}} 个文件）"` | `localize("key", { 0: selected, 1: total })` |
| Named | `"File: {{name}} exceeds {{size}}MB"` | `localize("key", { name, size })` |
| Nested ref | `"$t(linsight)正在规划..."` | Automatically resolved by i18next |
| Plural (count) | `"剩余任务次数： {{count}}次"` | `localize("key", { count: remaining })` |
