# i18n Localization Workflow

## Step 1 — Scan the Module

1. Read all `.tsx` and `.ts` files in the target module directory.
2. Identify every hardcoded user-facing string (Chinese text, toast messages, placeholders, button labels, titles, tooltips, error messages, etc.).
3. Ignore: code comments, CSS class names, variable names, enum values, strings already wrapped in `t()` / `localize()` / `i18n.t()`, and dev-only content (`console.log`).

## Step 2 — Generate Translation Keys

For each extracted string, determine which domain namespace it belongs to (e.g. `com_knowledge`, `com_ui`, `com_sop`), then generate a concise snake_case key name.

Example: `"知识空间创建成功"` → namespace `com_knowledge`, key `space_create_success` → used as `com_knowledge.space_create_success`

Refer to `CONVENTIONS.md` and `SAMPLE_KEYS.json` for naming details.

## Step 3 — Update Locale Files

> **CRITICAL**: Legacy flat keys (like `"com_ui_cancel"`) MUST be left untouched. Only ADD new keys using the nested namespace format.

Add new keys to **all three** translation files using nested structure:

```json
{
  "com_ui_cancel": "Cancel",

  "com_knowledge": {
    "space_create_success": "Knowledge space created",
    "drop_to_upload": "Drop files here to upload"
  }
}
```

| File | Value |
|------|-------|
| `src/locales/zh-Hans/translation.json` | Original Chinese string |
| `src/locales/en/translation.json` | Professional English translation |
| `src/locales/ja/translation.json` | Professional Japanese translation |

Rules:
- Do NOT modify or restructure existing flat keys.
- New keys go inside their namespace object, sorted alphabetically.
- If the namespace object already exists, append to it. If not, create it.
- Namespace objects are placed after all legacy flat keys, sorted alphabetically.
- Use `{{0}}` for positional interpolation, `{{name}}` for named interpolation.
- Do NOT duplicate existing keys — search before adding.

## Step 4 — Update Component Code

1. Import (if not present): `import { useLocalize } from "~/hooks";`
2. Initialize (if not present): `const localize = useLocalize();`
3. Replace hardcoded strings using **dot notation** for new nested keys:
   ```tsx
   // Before
   showToast({ message: "知识空间创建成功" });
   // After
   showToast({ message: localize("com_knowledge.space_create_success") });

   // Before (with dynamic values)
   message: `已开始处理 ${files.length} 个文件`
   // After
   message: localize("com_knowledge.files_processing_started", { 0: files.length })

   // Before (JSX)
   <p>松手即可上传文件至此处</p>
   // After
   <p>{localize("com_knowledge.drop_to_upload")}</p>
   ```

## Step 5 — Verify

1. No hardcoded Chinese remains in modified files (excluding code comments).
2. Every new key exists in all three locale JSON files.
3. No existing flat keys were modified or restructured.

## Output

After completing, provide a summary: number of strings extracted, list of new keys, and files modified.
