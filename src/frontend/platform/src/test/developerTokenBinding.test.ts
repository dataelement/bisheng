import { describe, expect, it } from "vitest"
import { resolveDepartmentUserTenantId, ROOT_TENANT_ID } from "@/pages/SystemPage/components/developerTokenBinding"

describe("resolveDepartmentUserTenantId", () => {
  it("prefers the mounted tenant on the selected department member", () => {
    expect(resolveDepartmentUserTenantId({
      tenant_id: 7,
      department_id: 10,
      dept_id: "D-10",
    })).toBe(7)
  })

  it("falls back to the operator tenant when the option has no mount", () => {
    expect(resolveDepartmentUserTenantId({
      department_id: 10,
      dept_id: "D-10",
    }, 5)).toBe(5)
  })

  it("uses ROOT_TENANT_ID when a department binding exists but no tenant is known", () => {
    expect(resolveDepartmentUserTenantId({
      department_id: 10,
      dept_id: "D-10",
    })).toBe(ROOT_TENANT_ID)
  })

  it("returns null when no binding context exists", () => {
    expect(resolveDepartmentUserTenantId(undefined)).toBeNull()
    expect(resolveDepartmentUserTenantId({
      label: "user",
      value: 1,
    })).toBeNull()
  })
})
