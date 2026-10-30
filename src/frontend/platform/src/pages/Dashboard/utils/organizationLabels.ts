export function organizationDisplayName(
  labels: Record<string, Record<string, string>> | undefined,
  fieldId: string | undefined,
  value: unknown,
): string {
  const text = value == null ? "" : String(value)
  if (!fieldId || !labels) return text
  return labels[fieldId]?.[text] ?? text
}

export function displayJoinedDimension(
  rawJoined: string,
  fieldIds: string[],
  labels: Record<string, Record<string, string>> | undefined,
): string {
  if (!fieldIds.length) return rawJoined
  return rawJoined
    .split("\n")
    .map((part, index) => organizationDisplayName(labels, fieldIds[index], part))
    .join("\n")
}
