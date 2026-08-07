import type {
  AutomotiveSheetIntroSyncConfig,
  DeveloperTokenRecord,
} from "@/controllers/API/developerToken"
import { findInvalidFileSyncRule } from "./developerTokenFileSyncRuleValidation"

const PDF_FILE_NAME_PATTERN = /^[^/\\]+\.pdf$/i
const HTTP_URL_PATTERN = /^https?:\/\/.+/i

export type AutomotiveSheetIntroSyncErrorField =
  | "enabled"
  | "apiUrl"
  | "apiMethod"
  | "developerToken"
  | "fileName"
  | "tokenFileSyncRule"

export interface AutomotiveSheetIntroSyncError {
  field: AutomotiveSheetIntroSyncErrorField
  reason: "required" | "invalid"
}

export function defaultAutomotiveSheetIntroSyncConfig(): AutomotiveSheetIntroSyncConfig {
  return {
    enabled: false,
    api_url: null,
    api_method: "GET",
    api_timeout_seconds: 120,
    developer_token_id: null,
    file_name: "汽车板介绍.pdf",
    external_file_id: "automotive_sheet_intro",
  }
}

export function normalizeAutomotiveSheetIntroSyncConfig(
  config: AutomotiveSheetIntroSyncConfig,
): AutomotiveSheetIntroSyncConfig {
  return {
    ...config,
    api_url: config.api_url?.trim() || null,
    file_name: config.file_name.trim(),
  }
}

export function findInvalidAutomotiveSheetIntroSyncConfig(
  config: AutomotiveSheetIntroSyncConfig,
  selectedToken: DeveloperTokenRecord | null,
): AutomotiveSheetIntroSyncError | null {
  if (!config.enabled) return null

  if (!config.api_url?.trim()) {
    return { field: "apiUrl", reason: "required" }
  }
  if (!HTTP_URL_PATTERN.test(config.api_url.trim())) {
    return { field: "apiUrl", reason: "invalid" }
  }
  if (!config.developer_token_id) {
    return { field: "developerToken", reason: "required" }
  }
  if (!selectedToken) {
    return { field: "developerToken", reason: "invalid" }
  }
  if (!selectedToken.enabled) {
    return { field: "developerToken", reason: "invalid" }
  }
  if (!config.file_name.trim() || !PDF_FILE_NAME_PATTERN.test(config.file_name.trim())) {
    return { field: "fileName", reason: "invalid" }
  }
  if (!selectedToken.file_sync_rule) {
    return { field: "tokenFileSyncRule", reason: "required" }
  }

  const fileSyncError = findInvalidFileSyncRule(
    selectedToken.file_sync_rule,
    null,
    selectedToken.file_sync_target_display,
  )
  if (fileSyncError) {
    return { field: "tokenFileSyncRule", reason: "invalid" }
  }

  return null
}
