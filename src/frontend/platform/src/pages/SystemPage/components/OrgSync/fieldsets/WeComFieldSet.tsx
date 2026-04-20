import { Badge } from "@/components/bs-ui/badge"
import { Button } from "@/components/bs-ui/button"
import { Input, PassInput } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { X } from "lucide-react"
import { useState } from "react"
import { useTranslation } from "react-i18next"
import { MASKED_PLACEHOLDER } from "../constants"

export interface WeComFormValues {
  corpid: string
  corpsecret: string // May be "****" in edit mode (means keep stored value)
  agent_id: string
  allow_dept_ids: number[]
}

interface WeComFieldSetProps {
  value: WeComFormValues
  onChange: (next: WeComFormValues) => void
  isEdit: boolean
  errors?: Partial<Record<keyof WeComFormValues, string>>
}

export function WeComFieldSet({
  value,
  onChange,
  isEdit,
  errors = {},
}: WeComFieldSetProps) {
  const { t } = useTranslation("orgSync")
  const [deptInput, setDeptInput] = useState("")

  const update = (patch: Partial<WeComFormValues>) => {
    onChange({ ...value, ...patch })
  }

  const addDeptId = () => {
    const trimmed = deptInput.trim()
    if (!trimmed) return
    const parsed = Number(trimmed)
    if (!Number.isInteger(parsed)) return
    if (value.allow_dept_ids.includes(parsed)) {
      setDeptInput("")
      return
    }
    update({ allow_dept_ids: [...value.allow_dept_ids, parsed] })
    setDeptInput("")
  }

  const removeDeptId = (id: number) => {
    update({ allow_dept_ids: value.allow_dept_ids.filter((n) => n !== id) })
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <Label htmlFor="wecom-corpid">
          {t("wecom.corpid")} <span className="text-destructive">*</span>
        </Label>
        <Input
          id="wecom-corpid"
          value={value.corpid}
          onChange={(e) => update({ corpid: e.target.value })}
          placeholder={t("wecom.corpidPlaceholder")}
        />
        {errors.corpid && (
          <span className="text-xs text-destructive">{errors.corpid}</span>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <Label htmlFor="wecom-corpsecret">
          {t("wecom.corpsecret")} <span className="text-destructive">*</span>
        </Label>
        <PassInput
          id="wecom-corpsecret"
          value={value.corpsecret}
          onChange={(e) => update({ corpsecret: e.target.value })}
          placeholder={
            isEdit
              ? t("wecom.corpsecretMaskedHint")
              : t("wecom.corpsecretPlaceholder")
          }
        />
        {errors.corpsecret && (
          <span className="text-xs text-destructive">{errors.corpsecret}</span>
        )}
        {isEdit && value.corpsecret === MASKED_PLACEHOLDER && (
          <span className="text-xs text-muted-foreground">
            {t("wecom.corpsecretEditHint")}
          </span>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <Label htmlFor="wecom-agent-id">
          {t("wecom.agentId")} <span className="text-destructive">*</span>
        </Label>
        <Input
          id="wecom-agent-id"
          value={value.agent_id}
          onChange={(e) => update({ agent_id: e.target.value })}
          placeholder={t("wecom.agentIdPlaceholder")}
        />
        {errors.agent_id && (
          <span className="text-xs text-destructive">{errors.agent_id}</span>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <Label>{t("wecom.allowDeptIds")}</Label>
        <span className="text-xs text-muted-foreground">
          {t("wecom.allowDeptIdsHint")}
        </span>
        <div className="flex gap-2">
          <Input
            type="number"
            inputMode="numeric"
            value={deptInput}
            onChange={(e) => setDeptInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault()
                addDeptId()
              }
            }}
            placeholder={t("wecom.allowDeptIdsPlaceholder")}
          />
          <Button type="button" variant="outline" onClick={addDeptId}>
            {t("actions.add")}
          </Button>
        </div>
        <div className="flex flex-wrap gap-2">
          {value.allow_dept_ids.length === 0 ? (
            <span className="text-xs text-muted-foreground">
              {t("wecom.allowDeptIdsDefault")}
            </span>
          ) : (
            value.allow_dept_ids.map((id) => (
              <Badge key={id} variant="secondary" className="gap-1">
                {id}
                <button
                  type="button"
                  onClick={() => removeDeptId(id)}
                  aria-label={t("actions.remove")}
                  className="inline-flex items-center"
                >
                  <X size={12} />
                </button>
              </Badge>
            ))
          )}
        </div>
        {errors.allow_dept_ids && (
          <span className="text-xs text-destructive">
            {errors.allow_dept_ids}
          </span>
        )}
      </div>
    </div>
  )
}

export function validateWeComForm(
  values: WeComFormValues,
  isEdit: boolean,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- i18next TFunction has complex overloads
  t: any
): Partial<Record<keyof WeComFormValues, string>> {
  const errors: Partial<Record<keyof WeComFormValues, string>> = {}
  if (!values.corpid.trim()) errors.corpid = t("wecom.corpidRequired")
  if (!values.agent_id.trim()) errors.agent_id = t("wecom.agentIdRequired")
  if (!values.corpsecret.trim()) {
    errors.corpsecret = t("wecom.corpsecretRequired")
  } else if (!isEdit && values.corpsecret === MASKED_PLACEHOLDER) {
    errors.corpsecret = t("wecom.corpsecretCannotBeMasked")
  }
  return errors
}

export function makeWeComSubmitPayload(
  values: WeComFormValues,
  isEdit: boolean
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    corpid: values.corpid.trim(),
    agent_id: values.agent_id.trim(),
    allow_dept_ids:
      values.allow_dept_ids.length > 0 ? values.allow_dept_ids : [1],
  }
  // Drop masked placeholder on update — the backend interprets absence as
  // "keep stored value".
  if (!(isEdit && values.corpsecret === MASKED_PLACEHOLDER)) {
    payload.corpsecret = values.corpsecret.trim()
  }
  return payload
}

export const WECOM_INITIAL: WeComFormValues = {
  corpid: "",
  corpsecret: "",
  agent_id: "",
  allow_dept_ids: [],
}
