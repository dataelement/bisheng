---
name: i18n-localizer
description: Internationalize a module by extracting hardcoded Chinese strings, generating translation keys, and updating all three locale files (en, zh-Hans, ja).
---

# i18n Localizer

This skill extracts hardcoded Chinese strings from a React module and replaces them with i18n calls, keeping all three locale files in sync.

**Supports both frontends** — automatically detects Client (`src/frontend/client/`) vs Platform (`src/frontend/platform/`) and applies the correct conventions.

## Instructions
1. **Detect Frontend**: Determine which frontend the target module belongs to based on its file path:
   - Path contains `src/frontend/client/` → **Client frontend**
   - Path contains `src/frontend/platform/` → **Platform frontend**
   - If ambiguous, ask the user to clarify.
2. **Read the Workflow**: Read `resources/INSTRUCTIONS.md` for the complete step-by-step process.
3. **Read the Conventions**: Based on the detected frontend:
   - Client → Read `resources/CONVENTIONS.md`
   - Platform → Read `resources/CONVENTIONS_PLATFORM.md`
4. **Execute**: Follow the workflow to localize the target module, using the correct hook, locale paths, and key format for the detected frontend.
