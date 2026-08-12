import type { DeveloperTokenRecord } from "@/controllers/API/developerToken"
import {
  findInvalidAutomotiveSheetIntroSyncConfig,
  normalizeAutomotiveSheetIntroSyncConfig,
} from "@/pages/SystemPage/components/automotiveSheetIntroSyncValidation"
import { describe, expect, it } from "vitest"

const tokenWithRule: DeveloperTokenRecord = {
  id: 10,
  tenant_id: 5,
  user_id: 7,
  name: "token",
  token_prefix: "bs_abc",
  enabled: true,
  override_ip_whitelist: false,
  override_rate_limit: false,
  route_rule_count: 0,
  file_sync_rule: {
    category: { code: "DOC", subcategory_code: "INTRO" },
    business_domain: { mode: "fixed", code: "AUTO", dynamic_source: null },
    target_space: {
      mode: "fixed",
      knowledge_id: 100,
      folder_mode: "fixed",
      folder_path: "automotive/intro",
    },
  },
}

describe("automotive sheet intro sync validation", () => {
  it("allows disabled config without required fields", () => {
    const invalid = findInvalidAutomotiveSheetIntroSyncConfig(
      {
        enabled: false,
        api_url: null,
        api_method: "GET",
        api_timeout_seconds: 120,
        api_ssl_verify: true,
        developer_token_id: null,
        file_name: "汽车板介绍.pdf",
        external_file_id: "automotive_sheet_intro",
      },
      null,
    )
    expect(invalid).toBeNull()
  })

  it("requires api url and token when enabled", () => {
    const invalid = findInvalidAutomotiveSheetIntroSyncConfig(
      normalizeAutomotiveSheetIntroSyncConfig({
        enabled: true,
        api_url: null,
        api_method: "GET",
        api_timeout_seconds: 120,
        api_ssl_verify: true,
        developer_token_id: null,
        file_name: "汽车板介绍.pdf",
        external_file_id: "automotive_sheet_intro",
      }),
      null,
    )
    expect(invalid?.field).toBe("apiUrl")
  })

  it("requires token file sync rule when enabled", () => {
    const invalid = findInvalidAutomotiveSheetIntroSyncConfig(
      normalizeAutomotiveSheetIntroSyncConfig({
        enabled: true,
        api_url: "https://example.com/x.pdf",
        api_method: "GET",
        api_timeout_seconds: 120,
        developer_token_id: 10,
        file_name: "汽车板介绍.pdf",
        external_file_id: "automotive_sheet_intro",
      }),
      {
        ...tokenWithRule,
        file_sync_rule: null,
      },
    )
    expect(invalid?.field).toBe("tokenFileSyncRule")
  })

  it("accepts enabled config when selected token has file sync rule", () => {
    const invalid = findInvalidAutomotiveSheetIntroSyncConfig(
      normalizeAutomotiveSheetIntroSyncConfig({
        enabled: true,
        api_url: "https://example.com/x.pdf",
        api_method: "GET",
        api_timeout_seconds: 120,
        developer_token_id: 10,
        file_name: "汽车板介绍.pdf",
        external_file_id: "automotive_sheet_intro",
      }),
      tokenWithRule,
    )
    expect(invalid).toBeNull()
  })
})
