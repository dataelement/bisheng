import { DepartmentTree } from "@/pages/DepartmentPage/components/DepartmentTree";
import { render, screen } from "@/test/test-utils";
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

const tree: DepartmentTreeNode[] = [
  {
    id: 1,
    dept_id: "BS@root",
    name: "Root Department",
    parent_id: null,
    path: "1/",
    sort_order: 0,
    source: "local",
    status: "active",
    member_count: 7,
    is_tenant_root: false,
    mounted_tenant_id: null,
    children: [
      {
        id: 2,
        dept_id: "BS@child",
        name: "Child Department",
        parent_id: 1,
        path: "1/2/",
        sort_order: 0,
        source: "local",
        status: "active",
        member_count: 3,
        is_tenant_root: false,
        mounted_tenant_id: null,
        children: [],
      },
    ],
  },
];

describe("DepartmentTree", () => {
  it("does not render member counts beside department names", () => {
    render(
      <DepartmentTree
        data={tree}
        selectedDeptId="BS@root"
        onSelect={vi.fn()}
        onCreateChild={vi.fn()}
      />
    );

    expect(screen.getByText("Root Department")).toBeInTheDocument();
    expect(screen.getByText("Child Department")).toBeInTheDocument();
    expect(screen.queryByText("7")).not.toBeInTheDocument();
    expect(screen.queryByText("3")).not.toBeInTheDocument();
  });
});
