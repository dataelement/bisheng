# i18n Conventions for Platform Frontend (src/frontend/platform/)

## Technology Stack

- **Library**: `i18next` (v23+) + `react-i18next` (v15+) + `i18next-http-backend` (v2+)
- **Supported Languages**: `en-US` (English), `zh-Hans` (Simplified Chinese), `ja` (Japanese)

## File Locations

| File | Purpose |
|------|---------|
| `src/i18n.js` | i18next initialization (HTTP backend loader) |
| `public/locales/en-US/{ns}.json` | English translations |
| `public/locales/zh-Hans/{ns}.json` | Simplified Chinese translations |
| `public/locales/ja/{ns}.json` | Japanese translations |

## Namespace Files

Platform uses **multiple namespace files** per language (loaded via HTTP backend at runtime):

| Namespace | File | Scope |
|-----------|------|-------|
| `bs` | `bs.json` | General UI, common labels, system messages |
| `flow` | `flow.json` | Flow/workflow builder, nodes, edges |
| `model` | `model.json` | LLM model management, fine-tuning |
| `tool` | `tool.json` | Tool/plugin management |
| `dashboard` | `dashboard.json` | Dashboard, charts, analytics |
| `knowledge` | `knowledge.json` | Knowledge base management |

> When adding keys, choose the namespace that best matches the module the string belongs to. Default to `bs` for cross-cutting or ambiguous strings.

## Key Naming Convention

### Key Naming Rules

1. Use **dot-separated paths** for hierarchy: `knowledge.spaceCreateSuccess`.
2. Use **camelCase** for leaf keys.
3. Keep keys **descriptive but concise** (2-5 words).
4. For similar operations, use consistent suffixes: `Success`, `Error`, `Failed`, `Confirm`, `Placeholder`, `Title`, `Desc`.

### Example Keys

```json
// public/locales/zh-Hans/bs.json
{
  "deleteConfirm": "确定要删除吗？",
  "saveSuccess": "保存成功",
  "cancel": "取消"
}

// public/locales/zh-Hans/knowledge.json
{
  "spaceCreateSuccess": "知识空间创建成功",
  "dropToUpload": "松手即可上传文件至此处",
  "folderMaxDepth": "文件夹层级已达上限（10层）"
}
```

## JSON File Format

- Each namespace is a **flat key-value** JSON object (no nesting).
- Keys are sorted alphabetically.
- Use `{{0}}`, `{{1}}` for positional interpolation, `{{name}}` for named interpolation.
- Do NOT duplicate existing keys — search before adding.

## Usage in Components

### Import Pattern

```tsx
import { useTranslation } from "react-i18next"
```

### Component Usage

```tsx
function MyComponent() {
    const { t } = useTranslation()

    return (
        <div>
            {/* Default namespace (bs) */}
            <button>{t('cancel')}</button>

            {/* Specific namespace */}
            <h1>{t('knowledge:spaceCreateSuccess')}</h1>

            {/* With interpolation */}
            <p>{t('knowledge:filesCount', { 0: fileCount })}</p>
        </div>
    )
}
```

### Toast Messages

```tsx
import { toast } from "@/components/bs-ui/toast/use-toast"

toast({
    title: t('prompt'),
    variant: 'success',
    description: t('knowledge:spaceCreateSuccess')
})
```

### Specifying Namespace via useTranslation

```tsx
// Load a specific namespace
const { t } = useTranslation('knowledge')
// Now t('spaceCreateSuccess') resolves from knowledge.json

// Load multiple namespaces
const { t } = useTranslation(['bs', 'knowledge'])
```

## Interpolation Examples

| Pattern | Locale Value | Code |
|---------|-------------|------|
| Positional | `"已选择 {{0}} 个文件（共 {{1}} 个文件）"` | `t('key', { 0: selected, 1: total })` |
| Named | `"文件: {{name}} 超过 {{size}}MB"` | `t('key', { name, size })` |
| Count | `"剩余任务次数：{{count}}次"` | `t('key', { count: remaining })` |
