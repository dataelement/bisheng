interface DepartmentNode {
  id: number;
  name?: string;
  children?: DepartmentNode[];
}

export function buildDepartmentPathLabelMap(nodes: DepartmentNode[]): Map<number, string> {
  const out = new Map<number, string>();

  const walk = (items: DepartmentNode[], ancestors: string[]) => {
    for (const item of items || []) {
      const name = item.name || String(item.id);
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
