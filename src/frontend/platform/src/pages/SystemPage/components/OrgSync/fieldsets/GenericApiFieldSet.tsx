import { Input, PassInput } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { useTranslation } from "react-i18next"
import { MASKED_PLACEHOLDER } from "../constants"

export interface GenericApiFormValues {
  endpoint_url: string
  api_key: string
}

interface GenericApiFieldSetProps {
  value: GenericApiFormValues
  onChange: (next: GenericApiFormValues) => void
  isEdit: boolean
  errors?: Partial<Record<keyof GenericApiFormValues, string>>
}

export function GenericApiFieldSet({
  value,
  onChange,
  isEdit,
  errors = {},
}: GenericApiFieldSetProps) {
  const { t } = useTranslation("orgSync")
  const update = (patch: Partial<GenericApiFormValues>) =>
    onChange({ ...value, ...patch })

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <Label htmlFor="generic-endpoint">
          {t("generic.endpointUrl")}{" "}
          <span className="text-destructive">*</span>
        </Label>
        <Input
          id="generic-endpoint"
          value={value.endpoint_url}
          onChange={(e) => update({ endpoint_url: e.target.value })}
          placeholder={t("generic.endpointUrlPlaceholder")}
        />
        {errors.endpoint_url && (
          <span className="text-xs text-destructive">
            {errors.endpoint_url}
          </span>
        )}
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor="generic-api-key">{t("generic.apiKey")}</Label>
        <PassInput
          id="generic-api-key"
          value={value.api_key}
          onChange={(e) => update({ api_key: e.target.value })}
          placeholder={
            isEdit
              ? t("generic.apiKeyMaskedHint")
              : t("generic.apiKeyPlaceholder")
          }
        />
        {errors.api_key && (
          <span className="text-xs text-destructive">{errors.api_key}</span>
        )}
      </div>
    </div>
  )
}

export function validateGenericApiForm(
  values: GenericApiFormValues,
  _isEdit: boolean,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- i18next TFunction has complex overloads
  t: any
): Partial<Record<keyof GenericApiFormValues, string>> {
  const errors: Partial<Record<keyof GenericApiFormValues, string>> = {}
  if (!values.endpoint_url.trim()) {
    errors.endpoint_url = t("generic.endpointUrlRequired")
  } else if (!/^https?:\/\//i.test(values.endpoint_url.trim())) {
    errors.endpoint_url = t("generic.endpointUrlInvalid")
  }
  return errors
}

export function makeGenericApiSubmitPayload(
  values: GenericApiFormValues,
  isEdit: boolean
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    endpoint_url: values.endpoint_url.trim(),
  }
  if (values.api_key.trim() && !(isEdit && values.api_key === MASKED_PLACEHOLDER)) {
    payload.api_key = values.api_key.trim()
  }
  return payload
}

export const GENERIC_API_INITIAL: GenericApiFormValues = {
  endpoint_url: "",
  api_key: "",
}
