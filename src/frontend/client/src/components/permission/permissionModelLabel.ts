const STANDARD_PERMISSION_LABELS = new Map([
  ["owner", "com_permission.level_owner"],
  ["manager", "com_permission.level_manager"],
  ["editor", "com_permission.level_editor"],
  ["viewer", "com_permission.level_viewer"],
]);

export function permissionModelLabel(
  key: string,
  name: string | undefined,
  localize: (key: string) => string,
): string {
  const translationKey = STANDARD_PERMISSION_LABELS.get(key);
  return translationKey ? localize(translationKey) : name || key;
}
