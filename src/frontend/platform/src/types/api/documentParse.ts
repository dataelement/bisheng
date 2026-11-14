/**
 * Document-parse (OCR / ETL) settings.
 *
 * `tokenConfigured` is read-only: the backend reports whether the environment
 * variable named by `paddleOcrApiKeyEnv` is set, and never returns the token.
 */
export type DocumentParseProvider = 'etl4lm' | 'mineru' | 'mineru_v4' | 'paddle_ocr'

export type PaddleOcrServiceMode = 'auto' | 'jobs' | 'sync'

export interface DocumentParseConfig {
  loader_provider: DocumentParseProvider
  etl4lm_url: string
  etl4lm_timeout: number
  etl4lm_ocr_sdk_url: string
  mineru_url: string
  mineru_timeout: number
  mineru_api_key_header: string
  mineru_token?: string | null
  mineru_clear_token?: boolean
  mineru_backend: string
  mineru_v4_api_url: string
  mineru_v4_api_key_env: string
  mineru_v4_token?: string | null
  mineru_v4_clear_token?: boolean
  mineru_v4_tier: string
  mineru_v4_model_version: 'pipeline' | 'vlm'
  mineru_v4_ocr_mode: 'auto' | 'txt' | 'ocr'
  mineru_v4_request_timeout_seconds: number
  mineru_v4_job_timeout_seconds: number
  mineru_v4_poll_interval_seconds: number
  paddle_ocr_url: string
  paddle_ocr_model: string
  paddle_ocr_api_key_env: string
  paddle_ocr_service_mode: PaddleOcrServiceMode
  paddle_ocr_timeout: number
  paddle_ocr_max_retries: number
  paddle_ocr_retry_backoff: number
  paddle_ocr_poll_interval_seconds: number
  paddle_ocr_job_timeout_seconds: number
  /** Write-only: typed token. Empty/omitted keeps the stored token. */
  paddle_ocr_token?: string | null
  /** Write-only: drop the stored token. */
  paddle_ocr_clear_token?: boolean
}

export type DocumentParseConfigResponse = DocumentParseConfig & {
  token_configured: boolean
  mineru_v4_token_configured: boolean
  mineru_token_configured: boolean
}

export type DocumentParseTestStatus =
  | 'ok'
  | 'token_missing'
  | 'token_invalid'
  | 'model_invalid'
  | 'unreachable'
  | 'misconfigured'
  | 'error'

export interface DocumentParseTestResult {
  status: DocumentParseTestStatus
  message: string
  latency_ms: number
}
