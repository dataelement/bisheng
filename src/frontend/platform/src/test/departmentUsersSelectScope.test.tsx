import { fireEvent, render, screen, waitFor } from "@/test/test-utils"
import DepartmentUsersSelect, {
  type DepartmentUserOption,
} from "@/components/bs-comp/selectComponent/DepartmentUsersSelect"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string | { defaultValue?: string }) => {
      if (typeof fallback === "string") return fallback
      if (fallback && typeof fallback === "object" && "defaultValue" in fallback)
        return fallback.defaultValue || _key
      return _key
    },
  }),
}))

// SearchInput pulls in an SVG via ?react which vite-plugin-svgr does not
// handle in the vitest environment. Stub the whole module so the picker can
// mount under jsdom.
vi.mock("@/components/bs-ui/input", async () => {
  const React = await import("react")
  const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
    (props, ref) => <input ref={ref} {...props} />,
  )
  return {
    Input,
    PasswordInput: Input,
    PassInput: Input,
    InputList: Input,
    NonNegativeInput: Input,
    Textarea: Input,
    SearchInput: Input,
  }
})

vi.mock("@/controllers/request", () => ({
  captureAndAlertRequestErrorHoc: vi.fn((promise: Promise<unknown>) =>
    Promise.resolve(promise),
  ),
}))

vi.mock("@/controllers/API/department", () => ({
  getDepartmentChildrenApi: vi.fn(),
  getDepartmentPathTreeApi: vi.fn(),
  getDepartmentMembersApi: vi.fn(),
}))

vi.mock("@/controllers/API/user", () => ({
  getUsersApi: vi.fn(),
}))

import {
  getDepartmentChildrenApi,
  getDepartmentMembersApi,
  getDepartmentPathTreeApi,
} from "@/controllers/API/department"
import { getUsersApi } from "@/controllers/API/user"

const mockedChildren = vi.mocked(getDepartmentChildrenApi)
const mockedPathTree = vi.mocked(getDepartmentPathTreeApi)
const mockedMembers = vi.mocked(getDepartmentMembersApi)
const mockedUsers = vi.mocked(getUsersApi)

// F038: lazy synthetic org tree.
//   Root (id=1)
//   ├── A (id=10)  └── A1 (id=11)
//   └── B (id=20)  └── B1 (id=21)
const NODE = (id: number, name: string, parent_id: number | null, path: string, has_children: boolean) => ({
  id,
  dept_id: String(id),
  name,
  parent_id,
  path,
  sort_order: 0,
  source: "local",
  status: "active",
  is_tenant_root: false,
  mounted_tenant_id: null,
  has_children,
  matched: false,
  children: [],
})
const NODES: Record<number, ReturnType<typeof NODE>> = {
  1: NODE(1, "Root", null, "/1/", true),
  10: NODE(10, "A", 1, "/1/10/", true),
  11: NODE(11, "A1", 10, "/1/10/11/", false),
  20: NODE(20, "B", 1, "/1/20/", true),
  21: NODE(21, "B1", 20, "/1/20/21/", false),
}
// parent_id (null = root layer) -> child ids
const CHILDREN: Record<string, number[]> = { null: [1], "1": [10, 20], "10": [11], "20": [21] }

beforeEach(() => {
  vi.clearAllMocks()
  mockedChildren.mockImplementation((parentId: number | null) =>
    Promise.resolve((CHILDREN[parentId == null ? "null" : String(parentId)] ?? []).map((id) => NODES[id])),
  )
  // path-tree: root→target chain (only id 10 is a valid rootDeptId here).
  mockedPathTree.mockImplementation((id: number) => {
    if (id === 10) return Promise.resolve({ roots: [{ ...NODES[1], children: [NODES[10]] }], total_matches: 1, truncated: false })
    return Promise.resolve({ roots: [], total_matches: 0, truncated: false })
  })
  mockedMembers.mockResolvedValue({ data: [] } as any)
  mockedUsers.mockResolvedValue({ data: [] } as any)
})

function openPicker() {
  const triggers = screen.getAllByRole("button")
  // The popover trigger is the first button rendered by the component.
  fireEvent.click(triggers[0])
}

describe("DepartmentUsersSelect — rootDeptId scope", () => {
  it("renders the full tree when rootDeptId is omitted", async () => {
    const onChange = vi.fn<(v: DepartmentUserOption[]) => void>()
    render(<DepartmentUsersSelect value={[]} onChange={onChange} />)
    openPicker()

    await waitFor(() => expect(mockedChildren).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText("Root")).toBeInTheDocument())
    expect(screen.getByText("A")).toBeInTheDocument()
    expect(screen.getByText("B")).toBeInTheDocument()
  })

  it("narrows the tree to the subtree rooted at rootDeptId", async () => {
    const onChange = vi.fn<(v: DepartmentUserOption[]) => void>()
    render(
      <DepartmentUsersSelect value={[]} onChange={onChange} rootDeptId={10} />,
    )
    openPicker()

    await waitFor(() => expect(mockedPathTree).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText("A")).toBeInTheDocument())
    // A1 lives under A, so it is rendered.
    expect(screen.getByText("A1")).toBeInTheDocument()
    // The sibling subtree (B / B1) and the original Root must be invisible.
    expect(screen.queryByText("B")).not.toBeInTheDocument()
    expect(screen.queryByText("B1")).not.toBeInTheDocument()
    expect(screen.queryByText("Root")).not.toBeInTheDocument()
  })

  // F038 regression: switching rootDeptId on a STILL-MOUNTED picker must reload
  // the new scope, not keep the previous scope's stale subtree (cacheKey reset).
  it("reloads the tree to the new scope when rootDeptId changes without remount", async () => {
    const onChange = vi.fn<(v: DepartmentUserOption[]) => void>()
    const { rerender } = render(
      <DepartmentUsersSelect value={[]} onChange={onChange} rootDeptId={10} />,
    )
    openPicker()

    // rootDeptId=10 → only the A subtree is visible.
    await waitFor(() => expect(screen.getByText("A")).toBeInTheDocument())
    expect(screen.queryByText("Root")).not.toBeInTheDocument()
    expect(screen.queryByText("B")).not.toBeInTheDocument()

    // Same instance, drop the scope → the full org tree must load.
    rerender(<DepartmentUsersSelect value={[]} onChange={onChange} rootDeptId={undefined} />)
    await waitFor(() => expect(screen.getByText("Root")).toBeInTheDocument())
    expect(screen.getByText("B")).toBeInTheDocument()
  })

  it("shows the empty message when rootDeptId does not match any node", async () => {
    const onChange = vi.fn<(v: DepartmentUserOption[]) => void>()
    render(
      <DepartmentUsersSelect
        value={[]}
        onChange={onChange}
        rootDeptId={9999}
        emptyMessage="No selectable members"
      />,
    )
    openPicker()

    await waitFor(() => expect(mockedPathTree).toHaveBeenCalled())
    await waitFor(() =>
      expect(screen.getByText("No selectable members")).toBeInTheDocument(),
    )
    expect(screen.queryByText("A")).not.toBeInTheDocument()
    expect(screen.queryByText("B")).not.toBeInTheDocument()
  })

  // F038: the flat user search shows each user's org path from the backend
  // (with_department_path) instead of firing one path-tree call per distinct
  // department in the result page.
  it("renders the backend-resolved department_path for user search, with no per-dept path-tree", async () => {
    mockedUsers.mockResolvedValue({
      data: [
        {
          user_id: 5,
          user_name: "Zhang",
          external_id: null,
          department_id: 106,
          department_path: "总公司/研发部/平台组",
        },
      ],
      total: 1,
    } as any)

    render(<DepartmentUsersSelect value={[]} onChange={vi.fn()} />)
    openPicker()

    fireEvent.change(screen.getByPlaceholderText("system.searchUser"), {
      target: { value: "Zhang" },
    })

    await screen.findByText("Zhang")
    expect(screen.getByText("总公司/研发部/平台组")).toBeInTheDocument()
    expect(mockedUsers).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Zhang", withDepartmentPath: true }),
      expect.anything(),
    )
    // The label comes from the user-list payload — no per-department path-tree call.
    expect(mockedPathTree).not.toHaveBeenCalled()
  })
})
