import { getDatasets } from "@/controllers/API/dashboard"
import { DatasetSelector } from "@/pages/Dashboard/components/config/DatasetSelector"
import { fireEvent, render, screen, waitFor } from "@/test/test-utils"
import { QueryClient, QueryClientProvider } from "react-query"
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"

// F058 AC-06/AC-07: 用户反馈统计 is excluded server-side (is_visible=false, not asserted
// here — that's a backend concern, see test_dashboard_user_dataset_merge.py); this only
// covers the frontend grouping of datasets that share a dataset_group.

vi.mock("@/controllers/API/dashboard", async () => {
  const actual = await vi.importActual<typeof import("@/controllers/API/dashboard")>(
    "@/controllers/API/dashboard",
  )
  return { ...actual, getDatasets: vi.fn() }
})

const mockedGetDatasets = vi.mocked(getDatasets)

beforeAll(() => {
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = vi.fn()
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

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  mockedGetDatasets.mockReset()
  mockedGetDatasets.mockResolvedValue([
    {
      id: 1,
      dataset_name: "用户行为指标表",
      dataset_code: "mid_user_increment",
      es_index_name: "mid_user_increment",
      description: "",
      is_commercial_only: false,
      dataset_group: "user_engagement",
      schema_config: { dimensions: [], metrics: [] },
    },
    {
      id: 2,
      dataset_name: "活跃用户表",
      dataset_code: "mid_active_user",
      es_index_name: "mid_active_user",
      description: "",
      is_commercial_only: true,
      dataset_group: "user_engagement",
      schema_config: { dimensions: [], metrics: [] },
    },
    {
      id: 3,
      dataset_name: "知识空间内容统计",
      dataset_code: "mid_knowledge_space_content_stat",
      es_index_name: "mid_knowledge_space_content_stat",
      description: "",
      is_commercial_only: false,
      dataset_group: null,
      schema_config: { dimensions: [], metrics: [] },
    },
  ] as any)
})

// The test suite globally mocks react-i18next's `t` as `(key) => key` (see
// src/test/setup.ts) — it does not honor `defaultValue`. So assertions below check for
// the translation KEY text (`datasetSelector.group.<group>`, or the dataset_code as the
// `t(dataset.dataset_code, {defaultValue: ...})` fallback) rather than the localized
// copy a real app run would show.
describe("DatasetSelector grouping (F058 AC-07)", () => {
  it("renders a group label and clusters the merged user-engagement datasets under it", async () => {
    renderWithQueryClient(<DatasetSelector />)

    fireEvent.click(screen.getByRole("combobox"))

    await waitFor(() => expect(mockedGetDatasets).toHaveBeenCalled())

    expect(await screen.findByText("datasetSelector.group.user_engagement")).toBeInTheDocument()
    expect(screen.getByText("mid_user_increment")).toBeInTheDocument()
    expect(screen.getByText("mid_active_user")).toBeInTheDocument()
  })

  it("renders an ungrouped dataset as a plain item, not inside a group", async () => {
    renderWithQueryClient(<DatasetSelector />)

    fireEvent.click(screen.getByRole("combobox"))

    await waitFor(() => expect(mockedGetDatasets).toHaveBeenCalled())

    expect(await screen.findByText("mid_knowledge_space_content_stat")).toBeInTheDocument()
  })
})

// F058 AC-08: the "原始上传库" (uploader_*) dimensions are picked up automatically by
// DatasetSelector's generic `schema_config.dimensions` rendering — no special-casing was
// added on the frontend (see tasks.md T025 / T009's backend-side dimension registration).
// This confirms that generic rendering actually surfaces them once the dataset carries them.
describe("DatasetSelector uploader-org dimensions (F058 AC-08)", () => {
  it("lists uploader_company/office/squad_name as selectable dimensions alongside belonging_*", async () => {
    mockedGetDatasets.mockResolvedValue([
      {
        id: 4,
        dataset_name: "知识空间内容统计",
        dataset_code: "mid_knowledge_space_content_stat",
        es_index_name: "mid_knowledge_space_content_stat",
        description: "",
        is_commercial_only: false,
        dataset_group: null,
        schema_config: {
          dimensions: [
            { field: "belonging_company_name", name: "所属公司", field_type: "string" },
            { field: "uploader_company_name", name: "上传人公司", field_type: "string" },
            { field: "uploader_office_name", name: "上传人科室", field_type: "string" },
            { field: "uploader_squad_name", name: "上传人班组", field_type: "string" },
          ],
          metrics: [],
        },
      },
    ] as any)

    renderWithQueryClient(
      <DatasetSelector selectedDatasetCode="mid_knowledge_space_content_stat" />,
    )

    expect(await screen.findByText("uploader_company_name")).toBeInTheDocument()
    expect(screen.getByText("uploader_office_name")).toBeInTheDocument()
    expect(screen.getByText("uploader_squad_name")).toBeInTheDocument()
    expect(screen.getByText("belonging_company_name")).toBeInTheDocument()
  })
})
