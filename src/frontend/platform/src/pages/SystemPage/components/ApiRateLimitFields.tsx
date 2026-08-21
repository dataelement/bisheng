import { Input } from "@/components/bs-ui/input"
import type { ApiRateLimitLimits } from "@/controllers/API/apiRateLimit"
import { useTranslation } from "react-i18next"

const DIMENSIONS: Array<keyof ApiRateLimitLimits> = ["second", "minute", "hour", "day"]

interface LimitInputsProps {
  value: ApiRateLimitLimits
  onChange: (value: ApiRateLimitLimits) => void
}

export default function ApiRateLimitFields({ value, onChange }: LimitInputsProps) {
  const { t } = useTranslation()
  return (
    <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
      {DIMENSIONS.map((dimension) => (
        <label key={dimension} className="space-y-1 text-sm">
          <span>{t(`system.apiRateLimit.dimensions.${dimension}`)}</span>
          <Input
            type="number"
            min={0}
            step={1}
            value={value[dimension] ?? ""}
            placeholder={t("system.apiRateLimit.unlimited")}
            onChange={(event) => {
              const raw = event.target.value
              onChange({
                ...value,
                [dimension]: raw === "" ? null : Number(raw),
              })
            }}
          />
        </label>
      ))}
    </div>
  )
}
