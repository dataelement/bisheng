import { Button } from "@/components/bs-ui/button"
import { Input } from "@/components/bs-ui/input"
import { toast } from "@/components/bs-ui/toast/use-toast"
import type {
  ApiRateLimitConfig,
} from "@/controllers/API/apiRateLimit"
import {
  getApiRateLimitConfigApi,
  updateApiRateLimitConfigApi,
} from "@/controllers/API/apiRateLimit"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import {
  findInvalidApiRateLimitRule,
  isValidApiRateLimitConfig,
  normalizeApiRateLimitConfig,
} from "./apiRateLimitValidation"
import ApiRateLimitFields from "./ApiRateLimitFields"
import ApiRateLimitRouteList from "./ApiRateLimitRouteList"

export default function ApiRateLimit() {
  const { t } = useTranslation()
  const [config, setConfig] = useState<ApiRateLimitConfig | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    void getApiRateLimitConfigApi().then(setConfig)
  }, [])

  if (!config) {
    return <div className="p-4 text-sm text-muted-foreground">{t("loading")}</div>
  }

  const handleSave = async () => {
    const normalized = normalizeApiRateLimitConfig(config)
    const invalidRule = findInvalidApiRateLimitRule(normalized.routes)
    if (!isValidApiRateLimitConfig(normalized)) {
      toast({
        title: t("prompt"),
        variant: "error",
        description: invalidRule === null
          ? t("system.apiRateLimit.limitInvalid")
          : t("system.apiRateLimit.ruleInvalid", { index: invalidRule + 1 }),
      })
      return
    }
    setSaving(true)
    try {
      const saved = await updateApiRateLimitConfigApi({
        expected_revision: normalized.revision,
        global: normalized.global,
        routes: normalized.routes,
      })
      setConfig(saved)
      toast({
        title: t("prompt"),
        variant: "success",
        description: t("system.apiRateLimit.saved"),
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="h-full space-y-5 overflow-y-auto p-4">
      <section className="space-y-3 rounded-md border p-4">
        <div>
          <h2 className="font-medium">{t("system.apiRateLimit.globalTitle")}</h2>
          <p className="text-xs text-muted-foreground">
            {t("system.apiRateLimit.globalHelp")}
          </p>
        </div>
        <ApiRateLimitFields
          value={config.global.limits}
          onChange={(limits) => setConfig({
            ...config,
            global: { ...config.global, limits },
          })}
        />
        <label className="block space-y-1 text-sm">
          <span>{t("system.apiRateLimit.message")}</span>
          <Input
            value={config.global.message}
            maxLength={500}
            onChange={(event) => setConfig({
              ...config,
              global: { ...config.global, message: event.target.value },
            })}
          />
        </label>
      </section>

      <ApiRateLimitRouteList
        routes={config.routes}
        onChange={(routes) => setConfig({ ...config, routes })}
      />

      <div className="flex justify-end">
        <Button disabled={saving} onClick={handleSave}>
          {saving ? t("system.apiRateLimit.saving") : t("system.apiRateLimit.save")}
        </Button>
      </div>
    </div>
  )
}
