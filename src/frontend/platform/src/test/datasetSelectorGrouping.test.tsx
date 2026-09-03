import { getDatasets } from "@/controllers/API/dashboard"
import { DatasetSelector } from "@/pages/Dashboard/components/config/DatasetSelector"
import { fireEvent, render, screen, waitFor } from "@/test/test-utils"
import { QueryClient, QueryClientProvider } from "react-query"
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"

// F058 AC-06/AC-07: 用户规模统计/活跃用户规模统计/全员每日参与度/用户反馈统计 are now merged
// server-side into one shared ES index (see init_dataset.py / test_dashboard_user_dataset_merge.py)
// and the non-surviving three entries are excluded from the picker via is_visible=false —
// the picker itself has no client-side grouping/merging logic to test anymore; it just
// renders whatever the (already-filtered) dataset list returns, same as any other dataset.

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
  // Simulates what the API already returns after server-side is_visible filtering:
  // exactly one entry for the merged user-engagement dataset, not three.
  mockedGetDatasets.mockResolvedValue([
    {
      id: 1,
      dataset_name: "用户数据统计",
      dataset_code: "mid_user_increment",
      es_index_name: "mid_user_engagement_stat",
      description: "",
      is_commercial_only: false,
      schema_config: { dimensions: [], metrics: [] },
    },
    {
      id: 3,
      dataset_name: "知识空间内容统计",
      dataset_code: "mid_knowledge_space_content_stat",
      es_index_name: "mid_knowledge_space_content_stat",
      description: "",
      is_commercial_only: false,
      schema_config: { dimensions: [], metrics: [] },
    },
  ] as any)
})

// The test suite globally mocks react-i18next's `t` as `(key) => key` (see
// src/test/setup.ts) — it does not honor `defaultValue`, so assertions below check for
// the dataset_code text (the `t(dataset.dataset_code, {defaultValue: ...})` fallback key)
// rather than the localized copy a real app run would show.
describe("DatasetSelector picker (F058 AC-06/AC-07)", () => {
  it("renders exactly one entry per dataset returned by the API — no client-side grouping/duplication", async () => {
    renderWithQueryClient(<DatasetSelector />)

    fireEvent.click(screen.getByRole("combobox"))

    await waitFor(() => expect(mockedGetDatasets).toHaveBeenCalled())

    expect(await screen.findByText("mid_user_increment")).toBeInTheDocument()
    expect(screen.getByText("mid_knowledge_space_content_stat")).toBeInTheDocument()
    expect(screen.getAllByText("mid_user_increment")).toHaveLength(1)
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
