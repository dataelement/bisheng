import { getFieldEnums } from "@/controllers/API/dashboard"
import { DimensionFilter } from "@/pages/Dashboard/components/charts/DimensionFilter"
import {
  ChartType,
  DashboardComponent,
  DimensionFilterConfig,
} from "@/pages/Dashboard/types/dataConfig"
import { fireEvent, render, screen, waitFor } from "@/test/test-utils"
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/controllers/API/dashboard", () => ({
  getFieldEnums: vi.fn(),
}))

const mockedGetFieldEnums = vi.mocked(getFieldEnums)

const component: DashboardComponent = {
  id: "dimension-filter-1",
  dashboard_id: "dashboard-1",
  title: "维度筛选",
  type: ChartType.DimensionFilter,
  dataset_code: "mid_knowledge_space_content_stat",
  data_config: {
    linkedComponentIds: [],
    fields: [
      {
        id: "field-1",
        fieldId: "primary_department_id",
        labelFieldId: "primary_department_name",
        fieldName: "primary_department_id",
        displayName: "人员主部门",
      },
    ],
  } satisfies DimensionFilterConfig,
  style_config: {},
  create_time: "",
  update_time: "",
}

beforeAll(() => {
  if (!window.PointerEvent) {
    Object.defineProperty(window, "PointerEvent", {
      configurable: true,
      value: MouseEvent,
    })
  }

  if (!Element.prototype.hasPointerCapture) {
    Element.prototype.hasPointerCapture = vi.fn(() => false)
  }

  if (!Element.prototype.setPointerCapture) {
    Element.prototype.setPointerCapture = vi.fn()
  }

  if (!Element.prototype.releasePointerCapture) {
    Element.prototype.releasePointerCapture = vi.fn()
  }
})

beforeEach(() => {
  mockedGetFieldEnums.mockReset()
  mockedGetFieldEnums.mockImplementation(async ({ keyword }) => ({
    options: keyword
      ? [{ label: "测试部门02", value: "dept-02" }]
      : [
          { label: "测试部门01", value: "dept-01" },
          { label: "测试部门02", value: "dept-02" },
        ],
  }))
})

describe("DimensionFilter interactions", () => {
  it("keeps only the interactive selector in the grid drag cancel area", async () => {
    const { container } = render(<DimensionFilter component={component} />)

    await waitFor(() => expect(mockedGetFieldEnums).toHaveBeenCalled())

    const filterRoot = container.firstElementChild
    const trigger = screen.getByRole("combobox")

    expect(filterRoot).not.toHaveClass("no-drag")
    expect(trigger).toHaveClass("no-drag")
  })

  it("replaces the enum list with the server-side search result", async () => {
    render(<DimensionFilter component={component} />)

    const trigger = screen.getByRole("combobox")
    await waitFor(() => expect(mockedGetFieldEnums).toHaveBeenCalledTimes(1))
    fireEvent.click(trigger)

    expect(await screen.findByText("测试部门01")).toBeInTheDocument()
    expect(screen.getByText("测试部门02")).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText("搜索人员主部门"), {
      target: { value: "02" },
    })

    await waitFor(
      () => {
        expect(mockedGetFieldEnums).toHaveBeenLastCalledWith(
          expect.objectContaining({ keyword: "02" }),
        )
      },
      { timeout: 1_500 },
    )

    await waitFor(() => {
      expect(screen.queryByText("测试部门01")).not.toBeInTheDocument()
      expect(screen.getByText("测试部门02")).toBeInTheDocument()
    })
  })
})

// F058 AC-02/AC-03: org-hierarchy fields (belonging_*/uploader_*) get a "全选" affordance
// and a fixed relative display order; non-org fields are untouched.
describe("DimensionFilter org-hierarchy filters (F058)", () => {
  const orgComponent: DashboardComponent = {
    ...component,
    id: "dimension-filter-org",
    data_config: {
      linkedComponentIds: [],
      fields: [
        // configured out of level order (squad before company) — display order must
        // still resolve to company -> squad.
        {
          id: "field-squad",
          fieldId: "belonging_squad_name",
          fieldName: "belonging_squad_name",
          displayName: "所属班组",
        },
        {
          id: "field-company",
          fieldId: "belonging_company_name",
          fieldName: "belonging_company_name",
          displayName: "所属公司",
        },
        {
          id: "field-primary",
          fieldId: "primary_department_id",
          labelFieldId: "primary_department_name",
          fieldName: "primary_department_id",
          displayName: "人员主部门",
        },
      ],
    } satisfies DimensionFilterConfig,
  }

  it("shows 全选 only for org-hierarchy fields, and orders company before squad", async () => {
    render(<DimensionFilter component={orgComponent} />)

    await waitFor(() => expect(mockedGetFieldEnums).toHaveBeenCalledTimes(3))

    const selectAllButtons = screen.getAllByRole("button", { name: "全选" })
    expect(selectAllButtons).toHaveLength(2)

    const labels = screen.getAllByText(/^(所属公司|所属班组|人员主部门)$/).map(el => el.textContent)
    expect(labels.indexOf("所属公司")).toBeLessThan(labels.indexOf("所属班组"))
  })

  it("clicking 全选 selects every currently loaded option for that field", async () => {
    render(<DimensionFilter component={orgComponent} />)

    await waitFor(() => expect(mockedGetFieldEnums).toHaveBeenCalledTimes(3))

    const [selectAllButton] = screen.getAllByRole("button", { name: "全选" })
    fireEvent.click(selectAllButton)

    expect(await screen.findByText("测试部门01")).toBeInTheDocument()
    expect(screen.getByText("测试部门02")).toBeInTheDocument()
  })
})

// Customer feedback (2026-09-01): only the "上传人名称" filter dropdown shows
// "部门-姓名" — every other dropdown (including this same component's other fields)
// keeps showing the plain enum label.
describe("DimensionFilter uploader name shows department (customer feedback)", () => {
  const uploaderComponent: DashboardComponent = {
    ...component,
    id: "dimension-filter-uploader",
    data_config: {
      linkedComponentIds: [],
      fields: [
        {
          id: "field-uploader",
          fieldId: "uploader_user_name",
          fieldName: "uploader_user_name",
          displayName: "上传人名称",
        },
      ],
    } satisfies DimensionFilterConfig,
  }

  beforeEach(() => {
    mockedGetFieldEnums.mockReset()
    mockedGetFieldEnums.mockImplementation(async () => ({
      // Backend's label_field sub-aggregation already resolves `label` to the
      // department name when `labelField` is passed — see dashboard.py::get_dataset_field_enums.
      options: [
        { label: "测试积分部门", value: "gzx003" },
        { label: "测试部门10", value: "gzx0001" },
      ],
    }))
  })

  it("requests the paired department field and combines it into the option label", async () => {
    render(<DimensionFilter component={uploaderComponent} />)

    await waitFor(() => expect(mockedGetFieldEnums).toHaveBeenCalledTimes(1))
    expect(mockedGetFieldEnums).toHaveBeenCalledWith(
      expect.objectContaining({ field: "uploader_user_name", labelField: "uploader_department_name" }),
    )

    fireEvent.click(screen.getByRole("combobox"))

    expect(await screen.findByText("测试积分部门-gzx003")).toBeInTheDocument()
    expect(screen.getByText("测试部门10-gzx0001")).toBeInTheDocument()
    expect(screen.queryByText("gzx003")).not.toBeInTheDocument()
  })

  it("falls back to the bare value when the option has no distinct department label", async () => {
    mockedGetFieldEnums.mockReset()
    mockedGetFieldEnums.mockImplementation(async () => ({
      options: [{ label: "admin", value: "admin" }],
    }))

    render(<DimensionFilter component={uploaderComponent} />)
    await waitFor(() => expect(mockedGetFieldEnums).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByRole("combobox"))

    expect(await screen.findByText("admin")).toBeInTheDocument()
  })
})
