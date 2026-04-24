import type { DepartmentTreeNode } from "@/types/api/department"

/** Build map: internal department id → human-readable path `父/子/孙`. */
export function buildDepartmentPathLabelMap(
  nodes: DepartmentTreeNode[],
  prefix: string[] = [],
): Map<number, string> {
  const map = new Map<number, string>()
  for (const n of nodes) {
    const segments = [...prefix, n.name]
    map.set(n.id, segments.join("/"))
    if (n.children?.length) {
      const childMap = buildDepartmentPathLabelMap(n.children, segments)
      childMap.forEach((v, k) => map.set(k, v))
    }
  }
  return map
}
