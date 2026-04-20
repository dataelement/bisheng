import { Input, PassInput } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { useTranslation } from "react-i18next"

export interface FeishuFormValues {
  app_id: string
  app_secret: string
}

interface FeishuFieldSetProps {
  value: FeishuFormValues
  onChange: (next: FeishuFormValues) => void
  isEdit: boolean
  errors?: Partial<Record<keyof FeishuFormValues, string>>
}

const MASKED_PLACEHOLDER = "****"

export function FeishuFieldSet({
  value,
  onChange,
  isEdit,
  errors = {},
}: FeishuFieldSetProps) {
  const { t } = useTranslation("orgSync")
  const update = (patch: Partial<FeishuFormValues>) =>
    onChange({ ...value, ...patch })

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <Label htmlFor="feishu-app-id">
          {t("feishu.appId")} <span className="text-destructive">*</span>
        </Label>
        <Input
          id="feishu-app-id"
          value={value.app_id}
          onChange={(e) => update({ app_id: e.target.value })}
          placeholder={t("feishu.appIdPlaceholder")}
        />
        {errors.app_id && (
          <span className="text-xs text-destructive">{errors.app_id}</span>
        )}
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor="feishu-app-secret">
          {t("feishu.appSecret")} <span className="text-destructive">*</span>
        </Label>
        <PassInput
          id="feishu-app-secret"
          value={value.app_secret}
          onChange={(e) => update({ app_secret: e.target.value })}
          placeholder={
            isEdit
              ? t("feishu.appSecretMaskedHint")
              : t("feishu.appSecretPlaceholder")
          }
        />
        {errors.app_secret && (
          <span className="text-xs text-destructive">
            {errors.app_secret}
          </span>
        )}
      </div>
    </div>
  )
}

export function validateFeishuForm(
  values: FeishuFormValues,
  isEdit: boolean,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- i18next TFunction has complex overloads
  t: any
): Partial<Record<keyof FeishuFormValues, string>> {
  const errors: Partial<Record<keyof FeishuFormValues, string>> = {}
  if (!values.app_id.trim()) errors.app_id = t("feishu.appIdRequired")
  if (!values.app_secret.trim()) {
    errors.app_secret = t("feishu.appSecretRequired")
  } else if (!isEdit && values.app_secret === MASKED_PLACEHOLDER) {
    errors.app_secret = t("feishu.appSecretCannotBeMasked")
  }
  return errors
}

export function makeFeishuSubmitPayload(
  values: FeishuFormValues,
  isEdit: boolean
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    app_id: values.app_id.trim(),
  }
  if (!(isEdit && values.app_secret === MASKED_PLACEHOLDER)) {
    payload.app_secret = values.app_secret.trim()
  }
  return payload
}

export const FEISHU_INITIAL: FeishuFormValues = {
  app_id: "",
  app_secret: "",
}
