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
