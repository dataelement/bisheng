export const WORKBENCH_PARENT_ID = "workstation"
export const ADMIN_PARENT_ID = "admin"

export const WORKBENCH_CHILD_MENUS = ["home", "apps", "subscription", "knowledge_space"] as const
export const ADMIN_CHILD_MENUS = [
  "board",
  "model",
  "log",
  "knowledge",
  "create_knowledge",
  "build",
  "create_app",
  "evaluation",
  "dataset",
  "mark_task",
] as const

export const TASK_MODE_MENU_ID = "linsight_task_mode"

export const CHILD_DEPENDENTS: Record<string, readonly string[]> = {
  home: [TASK_MODE_MENU_ID],
  build: ["create_app"],
  knowledge: ["create_knowledge"],
}

const LEGACY_MENU_ALIASES: Record<string, string> = {
  frontend: WORKBENCH_PARENT_ID,
  backend: ADMIN_PARENT_ID,
}

const SELECTABLE_MENU_IDS = new Set<string>([
  WORKBENCH_PARENT_ID,
  ADMIN_PARENT_ID,
  ...WORKBENCH_CHILD_MENUS,
  TASK_MODE_MENU_ID,
  ...ADMIN_CHILD_MENUS,
])

/**
 * Converts API data into the menu model represented by the role editor.
 * Unsupported or hidden API values are deliberately discarded so a later save
 * cannot preserve permissions that the user did not select in the UI.
 */
export function normalizeRoleMenuSelection(menuIds: readonly string[]): string[] {
  const selected = new Set<string>()

  menuIds.forEach((menuId) => {
    const normalized = LEGACY_MENU_ALIASES[String(menuId)] ?? String(menuId)
    if (SELECTABLE_MENU_IDS.has(normalized)) selected.add(normalized)
  })

  if (!selected.has(WORKBENCH_PARENT_ID)) {
    WORKBENCH_CHILD_MENUS.forEach((id) => selected.delete(id))
    selected.delete(TASK_MODE_MENU_ID)
  }
  if (!selected.has(ADMIN_PARENT_ID)) {
    ADMIN_CHILD_MENUS.forEach((id) => selected.delete(id))
  }

  Object.entries(CHILD_DEPENDENTS).forEach(([parent, dependents]) => {
    if (!selected.has(parent)) dependents.forEach((id) => selected.delete(id))
  })

  return Array.from(selected)
}
