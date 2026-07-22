import { Button } from "@/components/bs-ui/button"
import { Input } from "@/components/bs-ui/input"
import { toast } from "@/components/bs-ui/toast/use-toast"
import {
  DeveloperTokenGlobalConfig,
  getDeveloperTokenGlobalConfigApi,
  updateDeveloperTokenGlobalConfigApi,
} from "@/controllers/API/developerToken"
import type { ClipboardEvent, CompositionEvent, FormEvent, KeyboardEvent } from "react"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import {
  findInvalidIpWhitelistRule,
  formatLimitInput,
  isRateLimitControlKey,
  isRateLimitInputAllowed,
  isRateLimitValueValid,
  parseLimit,
  sanitizeRateLimitInput,
} from "./developerTokenValidation"

const EMPTY_CONFIG: DeveloperTokenGlobalConfig = {
  ip_whitelist: "",
  rate_limit_per_minute: null,
}

export default function DeveloperTokenGlobalSettings() {
  const { t } = useTranslation()
  const [config, setConfig] = useState<DeveloperTokenGlobalConfig>(EMPTY_CONFIG)
  const [rateLimit, setRateLimit] = useState("")
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    void getDeveloperTokenGlobalConfigApi().then((result) => {
      setConfig(result)
      setRateLimit(formatLimitInput(result.rate_limit_per_minute))
    })
  }, [])

  const showRateLimitError = () => {
    toast({
      title: t("prompt"),
      variant: "error",
      description: t("system.developerToken.rateLimitIntegerError"),
    })
  }

  const handleRateLimitChange = (value: string) => {
    if (!isRateLimitInputAllowed(value)) {
      setRateLimit(sanitizeRateLimitInput(value))
      showRateLimitError()
      return
    }
    setRateLimit(value)
  }

  const handleRateLimitKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (isRateLimitControlKey(event.key) || event.metaKey || event.ctrlKey || event.altKey) return
    if (!/^\d$/.test(event.key)) event.preventDefault()
  }

  const handleRateLimitBeforeInput = (event: FormEvent<HTMLInputElement>) => {
    const nativeEvent = event.nativeEvent as InputEvent
    if (nativeEvent.data && !isRateLimitInputAllowed(nativeEvent.data)) event.preventDefault()
  }

  const handleRateLimitPaste = (event: ClipboardEvent<HTMLInputElement>) => {
    if (!isRateLimitInputAllowed(event.clipboardData.getData("text"))) {
      event.preventDefault()
      showRateLimitError()
    }
  }

  const handleRateLimitCompositionEnd = (event: CompositionEvent<HTMLInputElement>) => {
    const value = event.currentTarget.value
    if (isRateLimitInputAllowed(value)) return
    const sanitized = sanitizeRateLimitInput(value)
    event.currentTarget.value = sanitized
    setRateLimit(sanitized)
    showRateLimitError()
  }

  const handleSave = async () => {
    const invalidIpRule = findInvalidIpWhitelistRule(config.ip_whitelist)
    if (invalidIpRule) {
      toast({
        title: t("prompt"),
        variant: "error",
        description: t("system.developerToken.ipWhitelistInvalidError", { rule: invalidIpRule }),
      })
      return
    }
    if (!isRateLimitValueValid(rateLimit)) {
      showRateLimitError()
      return
    }
    setSaving(true)
    try {
      const result = await updateDeveloperTokenGlobalConfigApi({
        ip_whitelist: config.ip_whitelist || "",
        rate_limit_per_minute: parseLimit(rateLimit),
      })
      setConfig(result)
      setRateLimit(formatLimitInput(result.rate_limit_per_minute))
      toast({
        title: t("prompt"),
        variant: "success",
        description: t("system.developerToken.saved"),
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3 border-b pb-4">
      <div className="grid gap-3 md:grid-cols-[1fr_220px_auto]">
        <label className="space-y-1 text-sm">
          <span>{t("system.developerToken.globalWhitelist")}</span>
          <textarea
            className="min-h-20 w-full rounded-md border bg-search-input px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring"
            value={config.ip_whitelist}
            onChange={(event) => setConfig({ ...config, ip_whitelist: event.target.value })}
            placeholder={t("system.developerToken.ipWhitelistPlaceholder")}
          />
          <div className="text-xs text-muted-foreground">
            {t("system.developerToken.ipWhitelistHelp")}
          </div>
        </label>
        <label className="space-y-1 text-sm">
          <span>{t("system.developerToken.globalRateLimit")}</span>
          <Input
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            placeholder={t("system.developerToken.globalRateLimitPlaceholder")}
            value={rateLimit}
            onBeforeInput={handleRateLimitBeforeInput}
            onKeyDown={handleRateLimitKeyDown}
            onPaste={handleRateLimitPaste}
            onCompositionEnd={handleRateLimitCompositionEnd}
            onChange={(event) => handleRateLimitChange(event.target.value)}
          />
        </label>
        <div className="flex items-end">
          <Button disabled={saving} onClick={handleSave}>
            {t("system.developerToken.saveConfig")}
          </Button>
        </div>
      </div>
    </div>
  )
}
