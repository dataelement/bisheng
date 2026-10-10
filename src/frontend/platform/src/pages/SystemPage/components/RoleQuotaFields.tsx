import { Checkbox } from "@/components/bs-ui/checkBox"
import { Input } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { useTranslation } from "react-i18next"
import { clampKnowledgeQuotaGbDisplay, RoleQuotaState } from "./roleQuotaConfig"

interface QuotaCountFieldProps {
  label: string
  description?: string
  unlimited: boolean
  count: string
  onUnlimitedChange: (next: boolean) => void
  onCountChange: (next: string) => void
}

/** An integer count quota: an "unlimited" checkbox that hides the number input. */
function QuotaCountField({
  label,
  description,
  unlimited,
  count,
  onUnlimitedChange,
  onCountChange,
}: QuotaCountFieldProps) {
  const { t } = useTranslation()
  return (
    <div className="rounded-md border p-3">
      <Label>{label}</Label>
      {description && <p className="mt-1 text-xs text-muted-foreground">{description}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <Checkbox checked={unlimited} onCheckedChange={(v) => onUnlimitedChange(Boolean(v))} />
        <span className="text-sm">{t("system.unlimited")}</span>
        {!unlimited && (
          <Input
            type="number"
            min={0}
            value={count}
            onChange={(e) => onCountChange(e.target.value)}
            className="w-[120px]"
          />
        )}
      </div>
    </div>
  )
}

interface RoleQuotaFieldsProps {
  value: RoleQuotaState
  onChange: (next: RoleQuotaState) => void
}

/**
 * The quota section of the role dialog. Controlled: it owns no state, so the
 * dialog keeps a single `RoleQuotaState` for snapshots and submission.
 */
export function RoleQuotaFields({ value, onChange }: RoleQuotaFieldsProps) {
  const { t } = useTranslation()
  const patch = (next: Partial<RoleQuotaState>) => onChange({ ...value, ...next })

  return (
    <>
      <div className="rounded-md border p-3">
        <Label>{t("system.knowledgeSpaceFileUploadLimit")}</Label>
        <p className="mt-1 text-xs text-muted-foreground">{t("system.knowledgeSpaceFileLimitDesc")}</p>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <Checkbox
            checked={value.fileUnlimited}
            onCheckedChange={(v) => patch({ fileUnlimited: Boolean(v) })}
          />
          <span className="text-sm">{t("system.unlimited")}</span>
          {!value.fileUnlimited && (
            <>
              <Input
                type="number"
                step={0.1}
                value={value.fileGb}
                onChange={(e) => patch({ fileGb: e.target.value })}
                onBlur={() => patch({ fileGb: clampKnowledgeQuotaGbDisplay(value.fileGb) })}
                className="w-[120px]"
                inputMode="decimal"
              />
              <span className="text-sm">GB</span>
            </>
          )}
        </div>
      </div>

      <QuotaCountField
        label={t("system.channelQuotaLimit")}
        unlimited={value.channelUnlimited}
        count={value.channelCount}
        onUnlimitedChange={(v) => patch({ channelUnlimited: v })}
        onCountChange={(v) => patch({ channelCount: v })}
      />

      <QuotaCountField
        label={t("system.spaceCreateQuotaLimit")}
        description={t("system.spaceCreateQuotaLimitDesc")}
        unlimited={value.spaceCreateUnlimited}
        count={value.spaceCreateCount}
        onUnlimitedChange={(v) => patch({ spaceCreateUnlimited: v })}
        onCountChange={(v) => patch({ spaceCreateCount: v })}
      />

      <QuotaCountField
        label={t("system.spaceSubscribeQuotaLimit")}
        description={t("system.spaceSubscribeQuotaLimitDesc")}
        unlimited={value.spaceSubscribeUnlimited}
        count={value.spaceSubscribeCount}
        onUnlimitedChange={(v) => patch({ spaceSubscribeUnlimited: v })}
        onCountChange={(v) => patch({ spaceSubscribeCount: v })}
      />

      <QuotaCountField
        label={t("system.infoSourceSubscribeQuotaLimit")}
        description={t("system.infoSourceSubscribeQuotaLimitDesc")}
        unlimited={value.infoSourceUnlimited}
        count={value.infoSourceCount}
        onUnlimitedChange={(v) => patch({ infoSourceUnlimited: v })}
        onCountChange={(v) => patch({ infoSourceCount: v })}
      />
    </>
  )
}
