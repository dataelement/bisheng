export interface DepartmentDisplayNameInput {
  displayName?: string | null;
  shortName?: string | null;
  name?: string | null;
}

function normalizeName(value?: string | null): string {
  return value?.trim() ?? "";
}

/** 门户统一展示：服务端展示名优先，其次简称，最后正式名称。 */
export function resolveDepartmentDisplayName(input: DepartmentDisplayNameInput): string {
  return normalizeName(input.displayName)
    || normalizeName(input.shortName)
    || normalizeName(input.name);
}

/** 部门搜索同时匹配正式名称、简称和展示名称。 */
export function departmentMatchesKeyword(
  input: DepartmentDisplayNameInput,
  keyword: string,
): boolean {
  const normalizedKeyword = keyword.trim().toLocaleLowerCase();
  if (!normalizedKeyword) return true;
  return [input.name, input.shortName, input.displayName]
    .map(normalizeName)
    .some((value) => value.toLocaleLowerCase().includes(normalizedKeyword));
}
