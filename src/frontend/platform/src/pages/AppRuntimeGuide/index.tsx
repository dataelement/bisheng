/**
 * `/apps/*` fallback — "the app factory is not deployed in this environment".
 *
 * Why a SPA route for a path the SPA does not own: when the runtime layer is
 * installed, nginx has a `location /apps/` that wins on prefix length and this
 * route is never reached. When it is *not* installed, `/apps/foo` falls through
 * to `location /` and lands on the platform's index.html — where today it hits
 * `* → /404` if logged in, or the login page if not. Both are exactly what
 * AC-30 forbids. One route in each table fixes that with zero nginx changes.
 *
 * The flag is read from the anonymous `/api/v1/env`, so the page can tell "the
 * switch is off" from "the switch is on but the layer is unreachable" without a
 * session — the link may well have arrived by QR code on someone's phone.
 */
import { Button, StateView, SystemErrorIllustration } from "@bisheng/ui"
import { getAppConfig } from "@/controllers/API"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"

export function AppRuntimeGuide() {
  const { t } = useTranslation()
  const [enabled, setEnabled] = useState<boolean | null>(null)

  useEffect(() => {
    let cancelled = false
    getAppConfig()
      .then((config) => {
        if (!cancelled) setEnabled(!!config?.app_runtime_enabled)
      })
      .catch(() => {
        // Unreachable env endpoint is itself a "not usable" answer; the copy
        // below already says "unavailable", so nothing more to do here.
        if (!cancelled) setEnabled(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const description =
    enabled === true
      ? t("hostedApp.guide.descEnabled")
      : t("hostedApp.guide.descDisabled")

  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-bg-page px-6 py-8">
      <StateView
        image={<SystemErrorIllustration />}
        title={t("hostedApp.guide.title")}
        description={
          <>
            <span className="block">{description}</span>
            <span className="block">{t("hostedApp.guide.contact")}</span>
          </>
        }
        action={
          <Button
            onClick={() => {
              window.location.href = __APP_ENV__.BASE_URL + "/"
            }}
          >
            {t("hostedApp.guide.backHome")}
          </Button>
        }
      />
    </div>
  )
}

export default AppRuntimeGuide
