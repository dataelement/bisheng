import {
  buildDepartmentPathLabel,
  collectDepartmentNames,
  departmentPathOrName,
  parseDepartmentPathIds,
} from "@/pages/BuildPage/bench/departmentPath";
import type { DepartmentTreeNode } from "@/types/api/department";
import { describe, expect, it } from "vitest";

const node = (id: number, name: string, path: string, children: DepartmentTreeNode[] = []) =>
  ({ id, name, path, children }) as DepartmentTreeNode;

describe("department path labels", () => {
  it("parses the materialized id path", () => {
    expect(parseDepartmentPathIds("/1/5/11/")).toEqual([1, 5, 11]);
    expect(parseDepartmentPathIds(null)).toEqual([]);
  });

  it("tells same-named departments apart by their chain", () => {
    const names = new Map([[1, "Group"], [5, "Subsidiary"]]);
    const lookup = (id: number) => names.get(id);
    expect(buildDepartmentPathLabel(node(10, "Digital", "/1/10/"), lookup)).toBe("Group / Digital");
    expect(buildDepartmentPathLabel(node(11, "Digital", "/1/5/11/"), lookup)).toBe(
      "Group / Subsidiary / Digital",
    );
  });

  it("starts at the visible root when an ancestor is unknown", () => {
    expect(buildDepartmentPathLabel(node(99, "HR", "/98/99/"), () => undefined)).toBe("HR");
  });

  it("collects names from a search forest", () => {
    const forest = [node(1, "Group", "/1/", [node(5, "Subsidiary", "/1/5/", [node(11, "Digital", "/1/5/11/")])])];
    expect(Array.from(collectDepartmentNames(forest).entries())).toEqual([
      [1, "Group"],
      [5, "Subsidiary"],
      [11, "Digital"],
    ]);
  });

  it("falls back to the name, then --", () => {
    expect(departmentPathOrName("A / B", "B")).toBe("A / B");
    expect(departmentPathOrName(null, "B")).toBe("B");
    expect(departmentPathOrName(undefined, "")).toBe("--");
  });
});
