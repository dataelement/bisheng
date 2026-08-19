interface PermissionTemplateItem {
  id: string
}

interface PermissionTemplateSectionLike {
  columns: Array<{ items: PermissionTemplateItem[] }>
}

export function filterAvailablePermissionIds(
  permissionIds: string[],
  sections: PermissionTemplateSectionLike[],
): string[] {
  const availablePermissionIds = new Set(
    sections.flatMap((section) =>
      section.columns.flatMap((column) => column.items.map((item) => item.id)),
    ),
  )
  return permissionIds.filter((id) => availablePermissionIds.has(id))
}
