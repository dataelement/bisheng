import type { DepartmentUserOption } from "@/components/bs-comp/selectComponent/DepartmentUsersSelect"

/** Mirrors backend `ROOT_TENANT_ID` used when no tenant mount is found. */
export const ROOT_TENANT_ID = 1

export function resolveDepartmentUserTenantId(
  selected: Pick<DepartmentUserOption, "tenant_id" | "department_id" | "dept_id"> | undefined,
  operatorTenantId?: number | null,
): number | null {
  if (!selected) return null

  const fromOption = Number(selected.tenant_id)
  if (Number.isFinite(fromOption) && fromOption > 0) return fromOption

  const fromOperator = Number(operatorTenantId)
  if (Number.isFinite(fromOperator) && fromOperator > 0) return fromOperator

  if (selected.department_id != null || selected.dept_id) return ROOT_TENANT_ID
  return null
}
