import { resolveDepartmentDisplayName } from "~/utils/departmentDisplayName";

interface DepartmentNode {
  id: number;
  name?: string;
  short_name?: string | null;
  display_name?: string;
  children?: DepartmentNode[];
}

export function buildDepartmentPathLabelMap(nodes: DepartmentNode[]): Map<number, string> {
  const out = new Map<number, string>();

  const walk = (items: DepartmentNode[], ancestors: string[]) => {
    for (const item of items || []) {
      const name = resolveDepartmentDisplayName({
        displayName: item.display_name,
        shortName: item.short_name,
        name: item.name,
      }) || String(item.id);
      const path = [...ancestors, name];
      out.set(item.id, path.join("/"));
      if (item.children?.length) {
        walk(item.children, path);
      }
    }
  };

  walk(nodes, []);
  return out;
}
