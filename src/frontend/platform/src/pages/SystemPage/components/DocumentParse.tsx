import { Button, Input, InputNumber, Radio, RadioGroup, toast } from "@bisheng/ui"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"

import { Label } from "@/components/bs-ui/label"
import {
  getDocumentParseConfigApi,
  saveDocumentParseConfigApi,
  testDocumentParseConfigApi,
} from "@/controllers/API/documentParse"
import { showApiError } from "@/controllers/request"
import {
  DocumentParseConfig,
  DocumentParseConfigResponse,
  DocumentParseProvider,
  DocumentParseTestResult,
  PaddleOcrServiceMode,
} from "@/types/api/documentParse"

import { Etl4lmSection, Field, MineruSection, MineruV4Section, TokenField } from "./documentParse/sections"

const PROVIDERS: DocumentParseProvider[] = ["etl4lm", "mineru", "mineru_v4", "paddle_ocr"]
const SERVICE_MODES: PaddleOcrServiceMode[] = ["auto", "jobs", "sync"]

/** Every field the form may write; keeps the payload and the type from drifting. */
const PAYLOAD_FIELDS = [
  "loader_provider",
  "etl4lm_url",
  "etl4lm_timeout",
  "etl4lm_ocr_sdk_url",
  "mineru_url",
  "mineru_timeout",
  "mineru_api_key_header",
  "mineru_backend",
  "mineru_v4_api_url",
  "mineru_v4_api_key_env",
  "mineru_v4_tier",
  "mineru_v4_model_version",
  "mineru_v4_ocr_mode",
  "mineru_v4_request_timeout_seconds",
  "mineru_v4_job_timeout_seconds",
  "mineru_v4_poll_interval_seconds",
  "paddle_ocr_url",
  "paddle_ocr_model",
  "paddle_ocr_api_key_env",
  "paddle_ocr_service_mode",
  "paddle_ocr_timeout",
  "paddle_ocr_max_retries",
  "paddle_ocr_retry_backoff",
  "paddle_ocr_poll_interval_seconds",
  "paddle_ocr_job_timeout_seconds",
  "paddle_ocr_token",
  "paddle_ocr_clear_token",
  "mineru_v4_token",
  "mineru_v4_clear_token",
  "mineru_token",
  "mineru_clear_token",
] as const satisfies readonly (keyof DocumentParseConfig)[]

export function DocumentParse() {
  const { t } = useTranslation()
  const [form, setForm] = useState<DocumentParseConfigResponse | null>(null)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<DocumentParseTestResult | null>(null)

  const load = useCallback(() => {
    getDocumentParseConfigApi()
      .then((data) => setForm(data))
      .catch(showApiError)
  }, [])

  useEffect(load, [load])

  const patch = (next: Partial<DocumentParseConfig>) =>
    setForm((prev) => (prev ? { ...prev, ...next } : prev))

  /** The writable payload. The `*_configured` flags are read-only status. */
  /** The writable payload. The `*_configured` flags are read-only status. */
  const toPayload = (source: DocumentParseConfigResponse): DocumentParseConfig => {
    const payload = {} as Record<string, unknown>
    for (const field of PAYLOAD_FIELDS) payload[field] = source[field] ?? null
    return payload as unknown as DocumentParseConfig
  }

  const handleTest = () => {
    if (!form) return
    setTesting(true)
    setTestResult(null)
    // Tests the current form values, including a credential that is not saved yet.
    testDocumentParseConfigApi(toPayload(form))
      .then((result) => setTestResult(result))
      .catch(showApiError)
      .finally(() => setTesting(false))
  }

  const handleSave = () => {
    if (!form) return
    setSaving(true)
    saveDocumentParseConfigApi(toPayload(form))
      .then(() => {
        toast.show({ type: "success", message: t("system.docParseSaved") })
        setTestResult(null)
        load()
      })
      .catch(showApiError)
      .finally(() => setSaving(false))
  }

  if (!form) return null

  const isJobs =
    form.paddle_ocr_service_mode === "jobs" ||
    (form.paddle_ocr_service_mode === "auto" && form.paddle_ocr_url.replace(/\/$/, "").endsWith("/jobs"))

  return (
    <div className="flex h-full flex-col overflow-auto pt-6 pb-4">
      <div className="mx-auto w-full max-w-[720px] space-y-5">
        <div>
          <Label>{t("system.docParseProvider")}</Label>
          <p className="mt-1 text-xs text-muted-foreground">{t("system.docParseProviderHint")}</p>
          <RadioGroup
            className="mt-2"
            value={form.loader_provider}
            onValueChange={(v) => patch({ loader_provider: v as DocumentParseProvider })}
          >
            {PROVIDERS.map((provider) => (
              <Radio key={provider} value={provider}>
                {t(`system.docParseProvider_${provider}`)}
              </Radio>
            ))}
          </RadioGroup>
          <p className="mt-2 text-xs text-muted-foreground">
            {t(`system.docParseProviderHint_${form.loader_provider}`)}
          </p>
        </div>

        {form.loader_provider === "etl4lm" && <Etl4lmSection form={form} patch={patch} />}
        {form.loader_provider === "mineru" && <MineruSection form={form} patch={patch} />}
        {form.loader_provider === "mineru_v4" && <MineruV4Section form={form} patch={patch} />}

        {form.loader_provider === "paddle_ocr" && (
          <div className="space-y-4 rounded-md border p-4">
            <Field label={t("system.docParseUrl")} hint={t("system.docParseUrlHint")}>
              <Input
                value={form.paddle_ocr_url}
                placeholder="https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
                onChange={(e) => patch({ paddle_ocr_url: e.currentTarget.value })}
              />
            </Field>

            <div>
              <Label>{t("system.docParseServiceMode")}</Label>
              <RadioGroup
                className="mt-2"
                value={form.paddle_ocr_service_mode}
                onValueChange={(v) => patch({ paddle_ocr_service_mode: v as PaddleOcrServiceMode })}
              >
                {SERVICE_MODES.map((mode) => (
                  <Radio key={mode} value={mode}>
                    {t(`system.docParseMode_${mode}`)}
                  </Radio>
                ))}
              </RadioGroup>
            </div>

            {isJobs && (
              <Field label={t("system.docParseModel")} hint={t("system.docParseModelHint")}>
                <Input
                  value={form.paddle_ocr_model}
                  placeholder="PaddleOCR-VL-1.6"
                  onChange={(e) => patch({ paddle_ocr_model: e.currentTarget.value })}
                />
              </Field>
            )}

            <TokenField
              value={form.paddle_ocr_token}
              configured={form.token_configured}
              clear={Boolean(form.paddle_ocr_clear_token)}
              onChange={(token) => patch({ paddle_ocr_token: token })}
              onClearChange={(clear) => patch({ paddle_ocr_clear_token: clear })}
            />
            {form.paddle_ocr_api_key_env && (
              <p className="text-xs text-muted-foreground">
                {t("system.docParseTokenSource", { name: form.paddle_ocr_api_key_env })}
              </p>
            )}

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label={t("system.docParseTimeout")}>
                <InputNumber
                  className="w-full"
                  min={1}
                  value={form.paddle_ocr_timeout}
                  onChange={(v) => patch({ paddle_ocr_timeout: v ?? 1 })}
                />
              </Field>
              <Field label={t("system.docParseMaxRetries")}>
                <InputNumber
                  className="w-full"
                  min={0}
                  value={form.paddle_ocr_max_retries}
                  onChange={(v) => patch({ paddle_ocr_max_retries: v ?? 0 })}
                />
              </Field>
              {isJobs && (
                <>
                  <Field label={t("system.docParsePollInterval")}>
                    <InputNumber
                      className="w-full"
                      min={0.1}
                      step={0.1}
                      value={form.paddle_ocr_poll_interval_seconds}
                      onChange={(v) => patch({ paddle_ocr_poll_interval_seconds: v ?? 0.1 })}
                    />
                  </Field>
                  <Field label={t("system.docParseJobTimeout")}>
                    <InputNumber
                      className="w-full"
                      min={1}
                      value={form.paddle_ocr_job_timeout_seconds}
                      onChange={(v) => patch({ paddle_ocr_job_timeout_seconds: v ?? 1 })}
                    />
                  </Field>
                </>
              )}
            </div>
          </div>
        )}

        {testResult && (
          <p
            className={`text-sm ${testResult.status === "ok" ? "text-green-600" : "text-red-500"}`}
            role="status"
          >
            {t(`system.docParseTest_${testResult.status}`, { ms: testResult.latency_ms })}
            {testResult.message ? ` — ${testResult.message}` : ""}
          </p>
        )}

        <div className="flex justify-end gap-3">
          <Button variant="outlined" disabled={testing || saving} onClick={handleTest}>
            {testing ? t("system.docParseTestRunning") : t("system.docParseTest")}
          </Button>
          <Button disabled={saving || testing} onClick={handleSave}>
            {t("save")}
          </Button>
        </div>
      </div>
    </div>
  )
}

