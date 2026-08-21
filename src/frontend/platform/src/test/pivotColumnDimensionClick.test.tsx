import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ComponentConfigDrawer } from "@/pages/Dashboard/components/config/ComponentConfigDrawer"
import { ChartType } from "@/pages/Dashboard/types/dataConfig"

const { editorStoreState, toastMock } = vi.hoisted(() => ({
  editorStoreState: {
    editingComponent: null as any,
    updateEditingComponent: vi.fn(),
    applyEditingComponent: vi.fn(),
    cancelEditingComponent: vi.fn(),
    draftVersion: 0,
  },
  toastMock: vi.fn(),
}))

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  useToast: () => ({ toast: toastMock }),
}))

vi.mock("@/store/dashboardStore", () => ({
  useComponentEditorStore: () => editorStoreState,
  useEditorDashboardStore: () => ({ refreshChart: vi.fn() }),
}))

vi.mock("@/pages/Dashboard/components/config/DatasetSelector", () => ({
  DatasetSelector: ({ onFieldClick }: { onFieldClick?: (field: any) => void }) => (
    <button
      type="button"
      onClick={() => onFieldClick?.({
        fieldId: "category_name",
        fieldCode: "category_name",
        fieldName: "知识分类",
        displayName: "知识分类",
        role: "dimension",
      })}
    >
      添加第二个列维度
    </button>
  ),
}))

vi.mock("@/pages/Dashboard/components/config/DimensionBlock", () => ({
  DimensionBlock: ({ dimensions, isStack }: { dimensions: any[]; isStack?: string }) => (
    isStack === "stack"
      ? <div data-testid="stack-dimensions">{dimensions.map(item => item.fieldId).join(",")}</div>
      : null
  ),
}))

vi.mock("@/pages/Dashboard/components/editor/ComponentPicker", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  ChartGroupItems: [],
}))

vi.mock("@/pages/Dashboard/components/config/FilterConditionDialog", () => ({
  FilterConditionDialog: () => null,
}))

const pivotWithOneColumnDimension = {
  id: "pivot-field-click",
  title: "交叉表",
  type: ChartType.PivotTable,
  dataset_code: "mid_knowledge_space_content_stat",
  data_config: {
    dimensions: [
      {
        fieldId: "uploader_name",
        fieldName: "上传人名称",
        fieldCode: "uploader_name",
        displayName: "上传人名称",
      },
      {
        fieldId: "department_name",
        fieldName: "上传人部门名称",
        fieldCode: "department_name",
        displayName: "上传人部门名称",
      },
    ],
    stackDimension: {
      fieldId: "timestamp",
      fieldName: "时间(日)",
      fieldCode: "timestamp",
      displayName: "时间(日)",
      timeGranularity: "day",
    },
    metrics: [
      {
        fieldId: "new_file_count",
        fieldName: "新增文件数",
        fieldCode: "new_file_count",
        displayName: "新增文件数",
        aggregation: "sum",
      },
    ],
    filters: [],
    fieldOrder: [],
    isConfigured: true,
  },
  style_config: {},
}

describe("pivot column dimension field click", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    editorStoreState.editingComponent = pivotWithOneColumnDimension
    editorStoreState.draftVersion = 0
  })

  it("adds a second pivot column dimension from the dataset field list", async () => {
    render(<ComponentConfigDrawer />)

    await waitFor(() => {
      expect(screen.getByTestId("stack-dimensions")).toHaveTextContent("timestamp")
    })

    fireEvent.click(screen.getByRole("button", { name: "添加第二个列维度" }))

    await waitFor(() => {
      expect(screen.getByTestId("stack-dimensions")).toHaveTextContent(
        "timestamp,category_name",
      )
    })
  })

  it("keeps non-pivot stacked charts limited to one column dimension", async () => {
    editorStoreState.editingComponent = {
      ...pivotWithOneColumnDimension,
      id: "stacked-bar-field-click",
      type: ChartType.StackedBar,
    }

    render(<ComponentConfigDrawer />)

    await waitFor(() => {
      expect(screen.getByTestId("stack-dimensions")).toHaveTextContent("timestamp")
    })

    fireEvent.click(screen.getByRole("button", { name: "添加第二个列维度" }))

    expect(screen.getByTestId("stack-dimensions")).toHaveTextContent("timestamp")
    expect(screen.getByTestId("stack-dimensions")).not.toHaveTextContent("category_name")
    expect(toastMock).toHaveBeenCalled()
  })
})
