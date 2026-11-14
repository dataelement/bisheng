import { Checkbox, Input, InputNumber, PasswordInput, Radio, RadioGroup } from "@bisheng/ui"
import { ReactNode } from "react"
import { useTranslation } from "react-i18next"

import { Label } from "@/components/bs-ui/label"
import { DocumentParseConfig, DocumentParseConfigResponse } from "@/types/api/documentParse"

const OCR_MODES = ["auto", "txt", "ocr"] as const
const MODEL_VERSIONS = ["pipeline", "vlm"] as const

interface FieldProps {
  label: string
  hint?: string
  children: ReactNode
}

export function Field({ label, hint, children }: FieldProps) {
  return (
    <div>
      <Label>{label}</Label>
      <div className="mt-1">{children}</div>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

interface TokenFieldProps {
  value?: string | null
  configured: boolean
  clear: boolean
  onChange: (token: string) => void
  onClearChange: (clear: boolean) => void
}

/** Write-only credential input: never prefilled, never echoed back by the API. */
export function TokenField({ value, configured, clear, onChange, onClearChange }: TokenFieldProps) {
  const { t } = useTranslation()
  return (
    <div>
      <Label>{t("system.docParseToken")}</Label>
      <PasswordInput
        className="mt-1"
        value={value ?? ""}
        placeholder={configured ? t("system.docParseTokenKeep") : t("system.docParseTokenPlaceholder")}
        revealLabel={t("system.docParseTokenReveal")}
        hideLabel={t("system.docParseTokenHide")}
        onChange={(e) => onChange(e.currentTarget.value)}
      />
      <p className={`mt-1 text-xs ${configured ? "text-muted-foreground" : "text-red-500"}`}>
        {configured ? t("system.docParseTokenConfigured") : t("system.docParseTokenUnset")}
      </p>
      {configured && (
        <label className="mt-2 flex items-center gap-2 text-sm">
          <Checkbox checked={clear} onCheckedChange={(v) => onClearChange(Boolean(v))} />
          {t("system.docParseTokenClear")}
        </label>
      )}
    </div>
  )
}

type SectionProps = {
  form: DocumentParseConfigResponse
  patch: (next: Partial<DocumentParseConfig>) => void
}

export function Etl4lmSection({ form, patch }: SectionProps) {
  const { t } = useTranslation()
  return (
    <div className="space-y-4 rounded-md border p-4">
      <Field label={t("system.docParseUrl")} hint={t("system.docParseEtl4lmHint")}>
        <Input value={form.etl4lm_url} onChange={(e) => patch({ etl4lm_url: e.currentTarget.value })} />
      </Field>
      <Field label={t("system.docParseOcrSdkUrl")} hint={t("system.docParseOcrSdkHint")}>
        <Input
          value={form.etl4lm_ocr_sdk_url}
          onChange={(e) => patch({ etl4lm_ocr_sdk_url: e.currentTarget.value })}
        />
      </Field>
      <Field label={t("system.docParseTimeout")}>
        <InputNumber
          className="w-[200px]"
          min={1}
          value={form.etl4lm_timeout}
          onChange={(v) => patch({ etl4lm_timeout: v ?? 1 })}
        />
      </Field>
    </div>
  )
}

export function MineruSection({ form, patch }: SectionProps) {
  const { t } = useTranslation()
  return (
    <div className="space-y-4 rounded-md border p-4">
      <Field label={t("system.docParseUrl")} hint={t("system.docParseMineruHint")}>
        <Input value={form.mineru_url} onChange={(e) => patch({ mineru_url: e.currentTarget.value })} />
      </Field>
      <Field label={t("system.docParseBackend")} hint={t("system.docParseBackendHint")}>
        <Input
          value={form.mineru_backend}
          placeholder="pipeline"
          onChange={(e) => patch({ mineru_backend: e.currentTarget.value })}
        />
      </Field>

      <TokenField
        value={form.mineru_token}
        configured={form.mineru_token_configured}
        clear={Boolean(form.mineru_clear_token)}
        onChange={(token) => patch({ mineru_token: token })}
        onClearChange={(clear) => patch({ mineru_clear_token: clear })}
      />

      <Field label={t("system.docParseKeyHeader")} hint={t("system.docParseKeyHeaderHint")}>
        <Input
          value={form.mineru_api_key_header}
          placeholder="x-api-key"
          onChange={(e) => patch({ mineru_api_key_header: e.currentTarget.value })}
        />
      </Field>

      <Field label={t("system.docParseTimeout")}>
        <InputNumber
          className="w-[200px]"
          min={1}
          value={form.mineru_timeout}
          onChange={(v) => patch({ mineru_timeout: v ?? 1 })}
        />
      </Field>
    </div>
  )
}

export function MineruV4Section({ form, patch }: SectionProps) {
  const { t } = useTranslation()
  return (
    <div className="space-y-4 rounded-md border p-4">
      <Field label={t("system.docParseApiRoot")} hint={t("system.docParseApiRootHint")}>
        <Input
          value={form.mineru_v4_api_url}
          placeholder="https://mineru.net/api/v4"
          onChange={(e) => patch({ mineru_v4_api_url: e.currentTarget.value })}
        />
      </Field>
      {form.mineru_v4_api_url.replace(/\/$/, "").endsWith("/agent/parse/file") && (
        <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          {t("system.docParseUploadNoBbox")}
        </p>
      )}

      <Field label={t("system.docParseTier")} hint={t("system.docParseTierHint")}>
        <Input value={form.mineru_v4_tier} onChange={(e) => patch({ mineru_v4_tier: e.currentTarget.value })} />
      </Field>

      <div>
        <Label>{t("system.docParseModelVersion")}</Label>
        <RadioGroup
          className="mt-2"
          value={form.mineru_v4_model_version}
          onValueChange={(v) => patch({ mineru_v4_model_version: v as DocumentParseConfig["mineru_v4_model_version"] })}
        >
          {MODEL_VERSIONS.map((mv) => (
            <Radio key={mv} value={mv}>
              {t(`system.docParseModelVersion_${mv}`)}
            </Radio>
          ))}
        </RadioGroup>
        <p className="mt-1 text-xs text-muted-foreground">{t("system.docParseModelVersionHint")}</p>
      </div>

      <div>
        <Label>{t("system.docParseOcrMode")}</Label>
        <RadioGroup
          className="mt-2"
          value={form.mineru_v4_ocr_mode}
          onValueChange={(v) => patch({ mineru_v4_ocr_mode: v as DocumentParseConfig["mineru_v4_ocr_mode"] })}
        >
          {OCR_MODES.map((mode) => (
            <Radio key={mode} value={mode}>
              {t(`system.docParseOcrMode_${mode}`)}
            </Radio>
          ))}
        </RadioGroup>
      </div>

      <TokenField
        value={form.mineru_v4_token}
        configured={form.mineru_v4_token_configured}
        clear={Boolean(form.mineru_v4_clear_token)}
        onChange={(token) => patch({ mineru_v4_token: token })}
        onClearChange={(clear) => patch({ mineru_v4_clear_token: clear })}
      />
      {form.mineru_v4_api_key_env && (
        <p className="text-xs text-muted-foreground">
          {t("system.docParseTokenSource", { name: form.mineru_v4_api_key_env })}
        </p>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Field label={t("system.docParseRequestTimeout")}>
          <InputNumber
            className="w-full"
            min={1}
            value={form.mineru_v4_request_timeout_seconds}
            onChange={(v) => patch({ mineru_v4_request_timeout_seconds: v ?? 1 })}
          />
        </Field>
        <Field label={t("system.docParseJobTimeout")}>
          <InputNumber
            className="w-full"
            min={1}
            value={form.mineru_v4_job_timeout_seconds}
            onChange={(v) => patch({ mineru_v4_job_timeout_seconds: v ?? 1 })}
          />
        </Field>
        <Field label={t("system.docParsePollInterval")}>
          <InputNumber
            className="w-full"
            min={0.1}
            step={0.1}
            value={form.mineru_v4_poll_interval_seconds}
            onChange={(v) => patch({ mineru_v4_poll_interval_seconds: v ?? 0.1 })}
          />
        </Field>
      </div>
    </div>
  )
}
