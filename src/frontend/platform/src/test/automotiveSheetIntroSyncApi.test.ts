import axios from "@/controllers/request"
import {
  getAutomotiveSheetIntroSyncConfigApi,
  listAutomotiveSheetIntroSyncRunsApi,
  testAutomotiveSheetIntroSyncApi,
  updateAutomotiveSheetIntroSyncConfigApi,
} from "@/controllers/API/developerToken"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/controllers/request", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

const mockedAxios = axios as unknown as {
  get: ReturnType<typeof vi.fn>
  post: ReturnType<typeof vi.fn>
  put: ReturnType<typeof vi.fn>
}

describe("automotive sheet intro sync API client", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("loads and saves tenant config", async () => {
    mockedAxios.get.mockResolvedValue({ enabled: false, file_name: "汽车板介绍.pdf" })
    mockedAxios.put.mockResolvedValue({ enabled: true, file_name: "汽车板介绍.pdf" })

    await getAutomotiveSheetIntroSyncConfigApi()
    await updateAutomotiveSheetIntroSyncConfigApi({
      enabled: true,
      api_url: "https://example.com/x.pdf",
      api_method: "GET",
      api_timeout_seconds: 120,
      developer_token_id: 10,
      file_name: "汽车板介绍.pdf",
      external_file_id: "automotive_sheet_intro",
    })

    expect(mockedAxios.get).toHaveBeenCalledWith(
      "/api/v1/admin/developer-tokens/automotive-sheet-intro-sync",
    )
    expect(mockedAxios.put).toHaveBeenCalledWith(
      "/api/v1/admin/developer-tokens/automotive-sheet-intro-sync",
      expect.objectContaining({ enabled: true }),
    )
  })

  it("dispatches test sync and loads run history", async () => {
    mockedAxios.post.mockResolvedValue({
      run_id: 11,
      status: "success",
      file_id: 900,
      scope: "tenant",
      tenant_id: 5,
      message: "ok",
    })
    mockedAxios.get.mockResolvedValue({ data: [], total: 0 })

    await testAutomotiveSheetIntroSyncApi()
    await listAutomotiveSheetIntroSyncRunsApi({ page: 1, limit: 10 })

    expect(mockedAxios.post).toHaveBeenCalledWith(
      "/api/v1/admin/developer-tokens/automotive-sheet-intro-sync/test",
    )
    expect(mockedAxios.get).toHaveBeenCalledWith(
      "/api/v1/admin/developer-tokens/automotive-sheet-intro-sync/runs",
      { params: { page: 1, limit: 10 } },
    )
  })
})
