import type { DepartmentSearchResult, DepartmentTreeNode } from "@/types/api/department"
import {
  getDepartmentChildrenApi,
  getDepartmentPathTreeApi,
  searchDepartmentsApi,
} from "./department"
import { filterDelegateCandidatesApi } from "./serviceAccount"

/** Intersect visible candidates with the same eligibility rules used on save. */
export function createDelegateCandidateSource(serviceAccountId: number) {
  const filterUserIds = async (ids: number[], signal?: AbortSignal): Promise<number[]> => {
    if (!ids.length) return []
    const eligible = await filterDelegateCandidatesApi(
      serviceAccountId,
      ids.map((subject_id) => ({ subject_type: "user", subject_id })),
      signal,
    )
    return eligible.filter((entry) => entry.subject_type === "user").map((entry) => entry.subject_id)
  }

  const filterDepartments = async (nodes: DepartmentTreeNode[]): Promise<DepartmentTreeNode[]> => {
    const ids = new Set<number>()
    const collect = (items: DepartmentTreeNode[]) => {
      for (const node of items) {
        ids.add(node.id)
        collect(node.children ?? [])
      }
    }
    collect(nodes)
    if (!ids.size) return []
    const eligible = await filterDelegateCandidatesApi(
      serviceAccountId,
      [...ids].map((subject_id) => ({ subject_type: "department", subject_id })),
    )
    const allowed = new Set(
      eligible.filter((entry) => entry.subject_type === "department").map((entry) => entry.subject_id),
    )
    const prune = (items: DepartmentTreeNode[]): DepartmentTreeNode[] =>
      items.flatMap((node) => {
        const children = prune(node.children ?? [])
        // Preserve eligible search matches even when their path has an ineligible ancestor.
        return allowed.has(node.id) ? [{ ...node, children }] : children
      })
    return prune(nodes)
  }

  const filterSearchResult = async (result: DepartmentSearchResult): Promise<DepartmentSearchResult> => {
    const roots = await filterDepartments(result.roots)
    const countMatches = (nodes: DepartmentTreeNode[]): number =>
      nodes.reduce((count, node) => count + Number(!!node.matched) + countMatches(node.children), 0)
    return { ...result, roots, total_matches: countMatches(roots) }
  }

  return {
    filterUserIds,
    departmentSource: {
      cacheKey: `delegate-departments:${serviceAccountId}`,
      fetchChildren: async (parentId: number | null) =>
        filterDepartments(await getDepartmentChildrenApi(parentId, false)),
      fetchSearch: async (keyword: string) =>
        filterSearchResult(await searchDepartmentsApi(keyword, false)),
      fetchPathTree: async (id: number) =>
        filterSearchResult(await getDepartmentPathTreeApi(id, false)),
    },
  }
}
