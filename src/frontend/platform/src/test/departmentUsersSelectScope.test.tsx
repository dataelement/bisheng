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
  getDepartmentTreeApi: vi.fn(),
  getDepartmentMembersApi: vi.fn(),
}))

vi.mock("@/controllers/API/user", () => ({
  getUsersApi: vi.fn(),
}))

import {
  getDepartmentMembersApi,
  getDepartmentTreeApi,
} from "@/controllers/API/department"
import { getUsersApi } from "@/controllers/API/user"

const mockedTree = vi.mocked(getDepartmentTreeApi)
const mockedMembers = vi.mocked(getDepartmentMembersApi)
const mockedUsers = vi.mocked(getUsersApi)

// Synthetic org tree:
//   Root (id=1)
//   ├── A (id=10)         <- one tenant root
//   │   └── A1 (id=11)
//   └── B (id=20)         <- another tenant root
//       └── B1 (id=21)
const TREE = [
  {
    id: 1,
    dept_id: "root",
    name: "Root",
    parent_id: null,
    status: "active",
    children: [
      {
        id: 10,
        dept_id: "a",
        name: "A",
        parent_id: 1,
        status: "active",
        children: [
          {
            id: 11,
            dept_id: "a1",
            name: "A1",
            parent_id: 10,
            status: "active",
            children: [],
          },
        ],
      },
      {
        id: 20,
        dept_id: "b",
        name: "B",
        parent_id: 1,
        status: "active",
        children: [
          {
            id: 21,
            dept_id: "b1",
            name: "B1",
            parent_id: 20,
            status: "active",
            children: [],
          },
        ],
      },
    ],
  },
]

beforeEach(() => {
  vi.clearAllMocks()
  mockedTree.mockResolvedValue(TREE as any)
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

    await waitFor(() => expect(mockedTree).toHaveBeenCalled())
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

    await waitFor(() => expect(mockedTree).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText("A")).toBeInTheDocument())
    // A1 lives under A, so it is rendered.
    expect(screen.getByText("A1")).toBeInTheDocument()
    // The sibling subtree (B / B1) and the original Root must be invisible.
    expect(screen.queryByText("B")).not.toBeInTheDocument()
    expect(screen.queryByText("B1")).not.toBeInTheDocument()
    expect(screen.queryByText("Root")).not.toBeInTheDocument()
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

    await waitFor(() => expect(mockedTree).toHaveBeenCalled())
    await waitFor(() =>
      expect(screen.getByText("No selectable members")).toBeInTheDocument(),
    )
    expect(screen.queryByText("A")).not.toBeInTheDocument()
    expect(screen.queryByText("B")).not.toBeInTheDocument()
  })
})
