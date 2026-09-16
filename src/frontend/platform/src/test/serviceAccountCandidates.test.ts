import { createDelegateCandidateSource } from "@/controllers/API/serviceAccountCandidates"
import { getDepartmentChildrenApi, getDepartmentPathTreeApi, searchDepartmentsApi } from "@/controllers/API/department"
import { filterDelegateCandidatesApi } from "@/controllers/API/serviceAccount"
import type { DepartmentTreeNode } from "@/types/api/department"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/controllers/API/serviceAccount", () => ({ filterDelegateCandidatesApi: vi.fn() }))
vi.mock("@/controllers/API/department", () => ({
  getDepartmentChildrenApi: vi.fn(),
  getDepartmentPathTreeApi: vi.fn(),
  searchDepartmentsApi: vi.fn(),
}))

function node(id: number, children: DepartmentTreeNode[] = []): DepartmentTreeNode {
  return {
    id, dept_id: `dept-${id}`, name: `Department ${id}`, parent_id: null,
    path: `/${id}/`, sort_order: 0, source: "local", status: "active",
    is_tenant_root: false, mounted_tenant_id: null, children, matched: true,
  }
}

beforeEach(() => vi.resetAllMocks())

describe("service-account delegation candidates", () => {
  it("uses the target service account and preserves cancellation for user filtering", async () => {
    const signal = new AbortController().signal
    vi.mocked(filterDelegateCandidatesApi).mockResolvedValue([{ subject_type: "user", subject_id: 2 }])
    const source = createDelegateCandidateSource(12)
    expect(await source.filterUserIds([1, 2], signal)).toEqual([2])
    expect(filterDelegateCandidatesApi).toHaveBeenCalledWith(12, [
      { subject_type: "user", subject_id: 1 }, { subject_type: "user", subject_id: 2 },
    ], signal)
  })

  it("filters every lazy department layer", async () => {
    vi.mocked(getDepartmentChildrenApi).mockResolvedValue([node(1), node(2), node(3)])
    vi.mocked(filterDelegateCandidatesApi).mockResolvedValue([{ subject_type: "department", subject_id: 2 }])
    const source = createDelegateCandidateSource(12).departmentSource
    expect((await source.fetchChildren(10)).map((entry) => entry.id)).toEqual([2])
    expect(getDepartmentChildrenApi).toHaveBeenCalledWith(10, false)
    expect(source.cacheKey).not.toEqual(createDelegateCandidateSource(13).departmentSource.cacheKey)
  })

  it("filters search and path trees while preserving eligible descendants", async () => {
    const result = { roots: [node(1, [node(2), node(3)])], total_matches: 3, truncated: false }
    vi.mocked(searchDepartmentsApi).mockResolvedValue(result)
    vi.mocked(getDepartmentPathTreeApi).mockResolvedValue(result)
    vi.mocked(filterDelegateCandidatesApi).mockResolvedValue([{ subject_type: "department", subject_id: 2 }])
    const source = createDelegateCandidateSource(12).departmentSource

    expect(await source.fetchSearch("Department")).toEqual({ ...result, roots: [node(2)], total_matches: 1 })
    expect((await source.fetchPathTree(2)).roots).toEqual([node(2)])
    expect(filterDelegateCandidatesApi).toHaveBeenCalledWith(12, [
      { subject_type: "department", subject_id: 1 },
      { subject_type: "department", subject_id: 2 },
      { subject_type: "department", subject_id: 3 },
    ])
  })

  it("does not fall back to unfiltered departments on failure", async () => {
    vi.mocked(getDepartmentChildrenApi).mockResolvedValue([node(1)])
    vi.mocked(filterDelegateCandidatesApi).mockRejectedValue(new Error("Filter unavailable"))
    await expect(createDelegateCandidateSource(12).departmentSource.fetchChildren(null)).rejects.toThrow("Filter unavailable")
  })
})
