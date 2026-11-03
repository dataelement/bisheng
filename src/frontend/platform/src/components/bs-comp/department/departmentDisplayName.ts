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

/** Replace only a verified built-in root segment, preserving path separators and descendants. */
export function departmentDisplayPath(
  path: string,
  root: Pick<DepartmentTreeNode, "dept_id" | "name"> | undefined,
  defaultName: string,
): string {
  if (!root) return path;
  const translated = departmentDisplayName(root, defaultName);
  if (translated === root.name) return path;
  const [first, ...rest] = path.split("/");
  if (first.trim() !== root.name) return path;
  return [first.replace(root.name, translated), ...rest].join("/");
}
