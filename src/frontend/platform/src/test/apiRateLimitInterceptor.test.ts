import {
  API_RATE_LIMIT_CODE,
  resetApiRateLimitNoticeDedupe,
  shouldShowApiRateLimitNotice,
} from "@/controllers/apiRateLimitNotice"
import request from "@/controllers/request"
import { toast } from "@/components/bs-ui/toast/use-toast"
import { beforeEach, describe, expect, it } from "vitest"

vi.mock("@/components/bs-ui/toast/use-toast", () => ({ toast: vi.fn() }))

describe("API rate limit notice dedupe", () => {
  beforeEach(resetApiRateLimitNoticeDedupe)

  it("shows concurrent duplicate errors once and allows them after the window", () => {
    expect(shouldShowApiRateLimitNotice(API_RATE_LIMIT_CODE, "busy", 1000)).toBe(true)
    expect(shouldShowApiRateLimitNotice(API_RATE_LIMIT_CODE, "busy", 1001)).toBe(false)
    expect(shouldShowApiRateLimitNotice(API_RATE_LIMIT_CODE, "another", 1001)).toBe(true)
    expect(shouldShowApiRateLimitNotice(API_RATE_LIMIT_CODE, "busy", 2500)).toBe(true)
  })

  it("handles HTTP 429 globally even when the request is silent", async () => {
    const upstreamError = {
      code: "ERR_BAD_RESPONSE",
      config: { silent: true },
      response: {
        status: 429,
        data: {
          status_code: API_RATE_LIMIT_CODE,
          status_message: "configured limit message",
          data: { retry_after: 3 },
        },
      },
    }

    await expect(request.get("/rate-limited", {
      silent: true,
      adapter: async () => Promise.reject(upstreamError),
    })).rejects.toBe(upstreamError)

    expect(toast).toHaveBeenCalledOnce()
    expect(vi.mocked(toast).mock.calls[0][0].description).toBe("configured limit message")
  })
})
