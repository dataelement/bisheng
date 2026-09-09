import { DepartmentTree } from "@/pages/DepartmentPage/components/DepartmentTree";
import { fireEvent, render, screen, within } from "@/test/test-utils";
import type { DepartmentTreeNode } from "@/types/api/department";
import type { ChangeEventHandler } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/bs-ui/input", () => ({
  SearchInput: ({
    placeholder,
    onChange,
  }: {
    placeholder?: string;
    onChange?: ChangeEventHandler<HTMLInputElement>;
  }) => (
    <input
      aria-label={placeholder}
      placeholder={placeholder}
      onChange={onChange}
    />
  ),
}));

function node(
  id: number,
  name: string,
  children: DepartmentTreeNode[] = [],
): DepartmentTreeNode {
  return {
    id,
    dept_id: `BS@${id}`,
    name,
    parent_id: id === 1 ? null : 1,
    path: `/${id}/`,
    sort_order: 0,
    source: "local",
    status: "active",
    is_tenant_root: false,
    mounted_tenant_id: null,
    children,
  };
}

const tree: DepartmentTreeNode[] = [
  node(1, "公司", [
    node(2, "第一层班组", [node(3, "班组下层")]),
  ]),
];

const orgLevelById: Record<number, string | null> = {
  1: "company",
  2: "squad",
  3: "squad",
};

function querySquadBadge(row: HTMLElement) {
  return within(row).queryByText((content) => (
    content === "班组"
    || content === "Squad"
    || content.includes("orgLevel.squad")
  ));
}

describe("DepartmentTree org_level badge", () => {
  it("renders first-level squad badge and hides descendant squad badge", () => {
    render(
      <DepartmentTree
        data={tree}
        selectedDeptId="BS@1"
        onSelect={vi.fn()}
        onCreateChild={vi.fn()}
        orgLevelById={orgLevelById}
      />,
    );

    const search = screen.getByRole("textbox");
    fireEvent.change(search, { target: { value: "班组下层" } });

    const firstSquadRow = screen.getByText("第一层班组").closest(".group") as HTMLElement;
    const nestedRow = screen.getByText("班组下层").closest(".group") as HTMLElement;
    expect(querySquadBadge(firstSquadRow)).toBeInTheDocument();
    expect(querySquadBadge(nestedRow)).not.toBeInTheDocument();
  });
});
