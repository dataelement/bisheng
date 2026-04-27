/** Reserved by init_data (`_init_default_root_department`): guest branch under root. */
export const GUEST_DEPARTMENT_DEPT_ID = "BS@guest"

export function isGuestDepartmentDeptId(deptId: string | undefined | null): boolean {
  return deptId === GUEST_DEPARTMENT_DEPT_ID
}
