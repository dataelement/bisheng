import type { DepartmentTreeNode } from "@/types/api/department";

/** Localize the seeded label without rewriting user-defined department names. */
export function departmentDisplayName(
  node: Pick<DepartmentTreeNode, "dept_id" | "name">,
  defaultName: string,
): string {
  // eslint-disable-next-line no-restricted-syntax -- Persisted system seed names are identifiers, not UI copy.
  return node.dept_id === "BS@root" && ["Default Org", "默认组织"].includes(node.name)
    ? defaultName
    : node.name;
}
