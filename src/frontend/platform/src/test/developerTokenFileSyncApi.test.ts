import axios from "@/controllers/request"
import {
  createDeveloperTokenApi,
  getDeveloperTokenFileSyncOptionsApi,
  getDeveloperTokenFileSyncTargetChildrenApi,
  updateDeveloperTokenApi,
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

describe("developer token file-sync API client", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("passes the tenant and bounded knowledge-space pagination query", async () => {
    mockedAxios.get.mockResolvedValue({
      tenant_id: 2,
      categories: [],
      business_domains: [],
      user_id: 7,
      target_space_groups: {
        data: [],
        has_more: false,
        next_cursor: null,
        page_size: 50,
      },
    })

    await getDeveloperTokenFileSyncOptionsApi({
      tenant_id: 2,
      user_id: 7,
      space_cursor: "next-space",
      space_page_size: 50,
      space_keyword: "safety",
    })

    expect(mockedAxios.get).toHaveBeenCalledWith(
      "/api/v1/admin/developer-tokens/config/file-sync-options",
      {
        params: {
          tenant_id: 2,
          user_id: 7,
          space_cursor: "next-space",
          space_page_size: 50,
          space_keyword: "safety",
        },
      }
    )
  })

  it("loads folder children with a scoped cursor", async () => {
    mockedAxios.get.mockResolvedValue({
      data: [],
      has_more: false,
      next_cursor: null,
      page_size: 50,
    })

    await getDeveloperTokenFileSyncTargetChildrenApi({
      tenant_id: 2,
      user_id: 7,
      knowledge_id: 118,
      parent_id: 4096,
      cursor: "next-folder",
      page_size: 25,
    })

    expect(mockedAxios.get).toHaveBeenCalledWith(
      "/api/v1/admin/developer-tokens/config/file-sync-target-children",
      {
        params: {
          tenant_id: 2,
          user_id: 7,
          knowledge_id: 118,
          parent_id: 4096,
          cursor: "next-folder",
          page_size: 25,
        },
      }
    )
  })

  it("preserves omitted and explicit-null file-sync payload semantics", async () => {
    mockedAxios.post.mockResolvedValue({})
    mockedAxios.put.mockResolvedValue({})
    const basePayload = {
      name: "token",
      user_id: 7,
      enabled: true,
      override_ip_whitelist: false,
      override_rate_limit: false,
    }

    await createDeveloperTokenApi({ ...basePayload, file_sync_rule: null })
    await updateDeveloperTokenApi(5, { name: "renamed" })
    await updateDeveloperTokenApi(5, { file_sync_rule: null })

    expect(mockedAxios.post).toHaveBeenCalledWith(
      "/api/v1/admin/developer-tokens",
      expect.objectContaining({ file_sync_rule: null })
    )
    expect(mockedAxios.put).toHaveBeenNthCalledWith(
      1,
      "/api/v1/admin/developer-tokens/5",
      { name: "renamed" }
    )
    expect(mockedAxios.put).toHaveBeenNthCalledWith(
      2,
      "/api/v1/admin/developer-tokens/5",
      { file_sync_rule: null }
    )
  })
})
