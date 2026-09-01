import type { TFunction } from "i18next"

/**
 * Display names for permission actions and resource types.
 *
 * The catalog stores a single `name` per action, and it is seeded to the code
 * itself — so the panel rendered `manage_permission` / `knowledge_file` at
 * users. One column cannot serve three languages anyway, so the label is
 * resolved here by code and the stored name is kept as the fallback for
 * anything the catalog gains later.
 */

export function actionLabel(
  t: TFunction,
  code: string,
  fallback?: string,
): string {
  return t(`actionName.${code}`, { defaultValue: fallback || code })
}

export function resourceTypeLabel(t: TFunction, resourceType: string): string {
  return t(`resourceTypeName.${resourceType}`, { defaultValue: resourceType })
}
