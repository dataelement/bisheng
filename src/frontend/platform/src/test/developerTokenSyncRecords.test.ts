import { readFileSync } from "node:fs"
import path from "node:path"
import axios from "@/controllers/request"
import { listDeveloperTokenSyncRecordsApi } from "@/controllers/API/developerToken"
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
}

describe("developer token sync records", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedAxios.get.mockResolvedValue({ data: [], total: 0 })
  })

  it("calls sync-records list API for a token", async () => {
    await listDeveloperTokenSyncRecordsApi(12, { page: 2, limit: 10 })
    expect(mockedAxios.get).toHaveBeenCalledWith(
      "/api/v1/admin/developer-tokens/12/sync-records",
      { params: { page: 2, limit: 10 } },
    )
  })

  it("does not mount automotive sheet sync panel above the token list", () => {
    const source = readFileSync(
      path.resolve(__dirname, "../pages/SystemPage/components/DeveloperToken.tsx"),
      "utf8",
    )
    expect(source).not.toContain("DeveloperTokenAutomotiveSheetSync")
    expect(source).not.toContain("automotive-sheet-intro-sync")
  })
})
