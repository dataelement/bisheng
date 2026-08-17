/**
 * Detail-page header: back link, icon, name, description and the state badge.
 *
 * The top "应用 / 工具 / 工作台配置" sub-tabs disappear on this page because the
 * layout renders them only on the three exact build paths — same behaviour as
 * the knowledge-base detail page, hence the explicit back link here.
 */
import AppAvator from "@/components/bs-comp/cardComponent/avatar"
import { Button } from "@/components/bs-ui/button"
import type { HostedAppDetail } from "@/controllers/API/hostedApp"
import { AppNumType } from "@/types/app"
import { ChevronLeft } from "lucide-react"
import { useTranslation } from "react-i18next"
import { useNavigate } from "react-router-dom"
import { stateBadgeClass, stateI18nKey } from "./types"

interface HostedAppHeaderProps {
  app: HostedAppDetail
}

export function HostedAppHeader({ app }: HostedAppHeaderProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()

  return (
    <div className="flex items-start gap-3 px-2 pb-4">
      <Button
        variant="outline"
        size="icon"
        className="mt-0.5 size-8"
        aria-label={t("hostedApp.detail.back")}
        onClick={() => navigate("/build/apps")}
      >
        <ChevronLeft className="size-4" />
      </Button>
      <AppAvator
        id={app.name}
        flowType={AppNumType.HOSTED_APP}
        url={app.logo || ""}
        className="mt-0.5 size-8 min-w-8"
      />
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <h1 className="truncate text-lg font-semibold">{app.name}</h1>
          <span
            className={`rounded-sm px-1.5 py-0.5 text-xs ${stateBadgeClass(app.state)}`}
          >
            {t(stateI18nKey(app.state))}
          </span>
        </div>
        <p className="mt-1 max-w-3xl break-all text-sm text-muted-foreground">
          {app.description}
        </p>
      </div>
    </div>
  )
}
