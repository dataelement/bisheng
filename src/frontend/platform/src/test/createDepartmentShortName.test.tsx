import { CreateDepartmentDialog } from "@/pages/DepartmentPage/components/CreateDepartmentDialog"
import { createDepartmentApi } from "@/controllers/API/department"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { fireEvent, render, screen, waitFor } from "@/test/test-utils"
import type { DepartmentTreeNode } from "@/types/api/department"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock("@/controllers/API/department", () => ({
  createDepartmentApi: vi.fn(),
}))

vi.mock("@/controllers/request", () => ({
  captureAndAlertRequestErrorHoc: vi.fn((promise: Promise<unknown>) => promise),
}))

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  toast: vi.fn(),
}))

vi.mock("@/components/bs-comp/department", () => ({
  TreeDepartmentSelect: () => <div data-testid="tree-select" />,
}))

vi.mock("@/components/bs-comp/selectComponent/DepartmentUsersSelect", () => ({
  __esModule: true,
  default: () => <div data-testid="admin-select" />,
}))

const mockedCreateDepartmentApi = vi.mocked(createDepartmentApi)
const mockedCapture = vi.mocked(captureAndAlertRequestErrorHoc)

const root: DepartmentTreeNode = {
  id: 1,
  dept_id: "BS@root",
  name: "Root",
  parent_id: null,
  path: "/1/",
  sort_order: 0,
  source: "local",
  status: "active",
  is_tenant_root: false,
  mounted_tenant_id: null,
  children: [],
}

describe("CreateDepartmentDialog short name", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedCreateDepartmentApi.mockResolvedValue({} as never)
    mockedCapture.mockImplementation((promise: Promise<unknown>) => promise as never)
  })

  it("renders the short name below the name and submits its normalized value", async () => {
    render(
      <CreateDepartmentDialog
        tree={[root]}
        defaultParentId={root.id}
        onCreated={vi.fn()}
        onClose={vi.fn()}
      />
    )

    const nameInput = screen.getByPlaceholderText("bs:department.nameRequired")
    const shortNameInput = screen.getByPlaceholderText(
      "bs:department.shortNamePlaceholder"
    )
    expect(
      nameInput.compareDocumentPosition(shortNameInput) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy()
    expect(shortNameInput).toHaveAttribute("maxlength", "64")

    fireEvent.change(nameInput, { target: { value: "Engineering" } })
    fireEvent.change(shortNameInput, { target: { value: "  R&D  " } })
    fireEvent.click(screen.getByRole("button", { name: "confirmButton" }))

    await waitFor(() => expect(mockedCreateDepartmentApi).toHaveBeenCalledTimes(1))
    expect(mockedCreateDepartmentApi).toHaveBeenCalledWith({
      name: "Engineering",
      short_name: "R&D",
      parent_id: 1,
      admin_user_ids: undefined,
    })
  })

  it("omits an empty short name from the create payload", async () => {
    render(
      <CreateDepartmentDialog
        tree={[root]}
        defaultParentId={root.id}
        onCreated={vi.fn()}
        onClose={vi.fn()}
      />
    )

    fireEvent.change(screen.getByPlaceholderText("bs:department.nameRequired"), {
      target: { value: "Engineering" },
    })
    fireEvent.change(
      screen.getByPlaceholderText("bs:department.shortNamePlaceholder"),
      { target: { value: "   " } }
    )
    fireEvent.click(screen.getByRole("button", { name: "confirmButton" }))

    await waitFor(() => expect(mockedCreateDepartmentApi).toHaveBeenCalledTimes(1))
    expect(mockedCreateDepartmentApi).toHaveBeenCalledWith(
      expect.objectContaining({ short_name: undefined })
    )
  })
})
