import { describe, expect, it, vi } from "vitest"
import axios from "@/controllers/request"
import {
  issueServiceAccountKeyApi,
  mutateServiceAccountResourceGrantsApi,
} from "@/controllers/API/serviceAccount"
import {
  listPersonalTokensApi,
  updatePersonalTokenSettingApi,
} from "@/controllers/API/personalToken"

vi.mock("@/controllers/request", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))

describe("open API management wrappers", () => {
  it("keeps service-account subjects explicit in key and resource-grant calls", async () => {
    await issueServiceAccountKeyApi(12, {
      name: "integration",
      scopes: ["delegate"],
      delegate_scopes: [{ subject_type: "user", subject_id: 8 }],
    })
    const payload = {
      idempotency_key: "mutation-1",
      expected_resource_version: 2,
      expected_catalog_release_id: 3,
      changes: [{
        op: "ADD" as const,
        model_key: "reader",
        subject: { type: "service_account" as const, id: "12" },
      }],
    }
    await mutateServiceAccountResourceGrantsApi(12, "knowledge_space", "9", payload)

    expect(axios.post).toHaveBeenNthCalledWith(1, "/api/v1/service-accounts/12/keys", expect.any(Object))
    expect(axios.post).toHaveBeenNthCalledWith(
      2,
      "/api/v1/service-accounts/12/resource-grants:mutate",
      payload,
      { params: { resource_type: "knowledge_space", resource_id: "9" } },
    )
  })

  it("uses tenant-admin personal-token ledger and settings endpoints", async () => {
    await listPersonalTokensApi({ page: 1, page_size: 20 })
    await updatePersonalTokenSettingApi({ pat_enabled: true, pat_ttl_days: 30 })
    expect(axios.get).toHaveBeenCalledWith("/api/v1/personal-tokens", { params: { page: 1, page_size: 20 } })
    expect(axios.put).toHaveBeenCalledWith("/api/v1/personal-tokens/settings", { pat_enabled: true, pat_ttl_days: 30 })
  })
})
