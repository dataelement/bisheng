import type { DepartmentTreeNode } from "@/types/api/department";

/**
 * COFCO: same-named departments (and so same-named spaces) exist across the
 * group and its subsidiaries, so department spaces are labelled with the full
 * name chain from the visible org root, e.g. 中粮集团 / 示例子公司 / 数智化部.
 */
export const DEPARTMENT_PATH_SEPARATOR = " / ";

/** "/1/5/11/" -> [1, 5, 11] (a department's materialized path of ids). */
export function parseDepartmentPathIds(path?: string | null): number[] {
  return String(path ?? "")
    .split("/")
    .filter((seg) => /^\d+$/.test(seg))
    .map(Number);
}

/**
 * Name chain for a tree node. Ancestors whose names are not known (not
 * loaded, or outside the visible tree) are skipped, so the chain starts at the
 * visible root; the node itself always ends it.
 */
export function buildDepartmentPathLabel(
  node: Pick<DepartmentTreeNode, "id" | "name" | "path">,
  lookupName: (id: number) => string | undefined,
): string {
  const ancestors = parseDepartmentPathIds(node.path).filter((id) => id !== node.id);
  const names = ancestors.map(lookupName).filter((name): name is string => !!name);
  return [...names, node.name].join(DEPARTMENT_PATH_SEPARATOR);
}

/** id -> name for every node of a (search / locate) forest. */
export function collectDepartmentNames(roots: DepartmentTreeNode[], into = new Map<number, string>()) {
  for (const node of roots) {
    into.set(node.id, node.name);
    if (node.children?.length) collectDepartmentNames(node.children, into);
  }
  return into;
}

/** Card / preview fallback when the path is missing: name, then "--". */
export function departmentPathOrName(path?: string | null, name?: string | null): string {
  return path || name || "--";
}
