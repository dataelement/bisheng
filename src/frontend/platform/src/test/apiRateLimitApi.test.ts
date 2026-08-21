import axios from "@/controllers/request"
import {
  getApiRateLimitConfigApi,
  getApiRateLimitRoutesApi,
  updateApiRateLimitConfigApi
} from "@/controllers/API/apiRateLimit"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/controllers/request", () => ({
  default: {
    get: vi.fn(),
    put: vi.fn()
  }
}))

describe("api rate limit controller", () => {
  beforeEach(() => vi.clearAllMocks())

  it("uses the admin config endpoint for reads", async () => {
    vi.mocked(axios.get).mockResolvedValue({ revision: 0 })

    await getApiRateLimitConfigApi()

    expect(axios.get).toHaveBeenCalledWith(
      "/api/v1/admin/api-rate-limit/config"
    )
  })

  it("sends the expected revision with a complete replacement", async () => {
    vi.mocked(axios.put).mockResolvedValue({ revision: 3 })
    const payload = {
      expected_revision: 2,
      global: {
        limits: { second: 1, minute: null, hour: null, day: null },
        message: "busy"
      },
      routes: []
    }

    await updateApiRateLimitConfigApi(payload)

    expect(axios.put).toHaveBeenCalledWith(
      "/api/v1/admin/api-rate-limit/config",
      payload
    )
  })

  it("queries the categorized route catalog with bounded pagination filters", async () => {
    vi.mocked(axios.get).mockResolvedValue({ items: [], total: 0 })

    await getApiRateLimitRoutesApi({
      keyword: "knowledge",
      method: "GET",
      tag: "Knowledge",
      page: 2,
      page_size: 50
    })

    expect(axios.get).toHaveBeenCalledWith(
      "/api/v1/admin/api-rate-limit/routes",
      {
        params: {
          keyword: "knowledge",
          method: "GET",
          tag: "Knowledge",
          page: 2,
          page_size: 50
        }
      }
    )
  })
})
