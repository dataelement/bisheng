import { toast } from "@/components/bs-ui/toast/use-toast"
import request from "@/controllers/request"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/components/bs-ui/toast/use-toast", () => ({ toast: vi.fn() }))

const storage = new Map<string, string>()
Object.defineProperty(globalThis, "localStorage", {
  configurable: true,
  value: {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, String(value)),
    removeItem: (key: string) => storage.delete(key),
  },
})

function gatewayError(url: string, status: number, method = "get", data: unknown = "<html>bad gateway</html>") {
  return {
    message: `Request failed with status code ${status}`,
    config: { url, method, baseURL: "/platform/" },
    response: { status, data },
  }
}

describe("dashboard gateway failures", () => {
  beforeEach(() => {
    vi.mocked(toast).mockClear()
  })

  it("does not toast when the dashboard list is a gateway 502", async () => {
    const error = gatewayError("/api/v1/telemetry/dashboard", 502)
    await expect(request.get("/api/v1/telemetry/dashboard", {
      adapter: async () => Promise.reject(error),
    })).rejects.toBeNull()
    expect(toast).not.toHaveBeenCalled()
  })

  it("does not toast when a dashboard detail is a gateway 504", async () => {
    const error = gatewayError("/api/v1/telemetry/dashboard/12", 504)
    await expect(request.get("/api/v1/telemetry/dashboard/12", {
      adapter: async () => Promise.reject(error),
    })).rejects.toBeNull()
    expect(toast).not.toHaveBeenCalled()
  })

  it("does not toast when a chart query is a gateway 503", async () => {
    const error = gatewayError("/api/v1/telemetry/dashboard/component/query", 503, "post")
    await expect(request.post("/api/v1/telemetry/dashboard/component/query", {}, {
      adapter: async () => Promise.reject(error),
    })).rejects.toBeNull()
    expect(toast).not.toHaveBeenCalled()
  })

  it("still toasts a gateway 502 on other pages", async () => {
    const error = gatewayError("/api/v1/user/info", 502)
    await expect(request.get("/api/v1/user/info", {
      adapter: async () => Promise.reject(error),
    })).rejects.toBeNull()
    expect(toast).toHaveBeenCalledOnce()
    expect(vi.mocked(toast).mock.calls[0][0].description).toBe("Request failed with status code 502")
  })

  it("still toasts a dashboard export gateway failure", async () => {
    const error = gatewayError("/api/v1/telemetry/dashboard/component/c1/export", 502, "post")
    await expect(request.post("/api/v1/telemetry/dashboard/component/c1/export", {}, {
      adapter: async () => Promise.reject(error),
    })).rejects.toBeNull()
    expect(toast).toHaveBeenCalledOnce()
  })

  it("still toasts a dashboard business envelope", async () => {
    const error = gatewayError("/api/v1/telemetry/dashboard", 500, "get", {
      status_code: 500,
      status_message: "查询失败",
    })
    await expect(request.get("/api/v1/telemetry/dashboard", {
      adapter: async () => Promise.reject(error),
    })).rejects.toBeNull()
    expect(toast).toHaveBeenCalledOnce()
    expect(vi.mocked(toast).mock.calls[0][0].description).not.toBe("Request failed with status code 500")
  })
})
