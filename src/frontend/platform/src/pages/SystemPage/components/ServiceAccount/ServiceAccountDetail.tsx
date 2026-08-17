import { Button } from "@/components/bs-ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs"
import { getServiceAccountApi } from "@/controllers/API/serviceAccount"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { ServiceAccountDetail as ServiceAccountDetailData } from "@/types/api/serviceAccount"
import { ChevronLeft } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { ApiKeysTab } from "./ApiKeysTab"
import { OverviewTab } from "./OverviewTab"
import type { ServiceAccountDetailTab } from "./ServiceAccountPanel"

interface ServiceAccountDetailProps {
  id: number
  /** Which tab opens first — `keys` right after creation (AC-43) */
  initialTab: ServiceAccountDetailTab
  /** Opens the issue dialog on the key tab's first frame (AC-43) */
  autoOpenIssue: boolean
  onBack: () => void
}

/**
 * Detail shell: three tabs (overview / API keys / resource grants).
 *
 * The connection-info block belongs to F053 and is deliberately absent here;
 * the grants tab is a placeholder until T066 fills it.
 */
export function ServiceAccountDetail({
  id,
  initialTab,
  autoOpenIssue,
  onBack,
}: ServiceAccountDetailProps) {
  const { t } = useTranslation("serviceAccount")
  const [detail, setDetail] = useState<ServiceAccountDetailData | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    captureAndAlertRequestErrorHoc(getServiceAccountApi(id)).then((res) => {
      setLoading(false)
      if (!res) return
      setDetail(res)
    })
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="flex h-full flex-col px-2">
      <div className="flex shrink-0 items-center gap-2 py-2">
        <Button variant="ghost" size="sm" className="px-1" onClick={onBack}>
          <ChevronLeft className="mr-1 size-4" />
          {t("detail.back")}
        </Button>
        <span className="truncate text-lg font-medium">{detail?.name || ""}</span>
        {detail && (
          <span className="text-sm text-muted-foreground">
            {t(`status.${detail.status}`)}
          </span>
        )}
      </div>
      <Tabs defaultValue={initialTab} className="flex min-h-0 w-full flex-1 flex-col">
        <TabsList className="shrink-0 self-start">
          <TabsTrigger value="overview">{t("detail.tabs.overview")}</TabsTrigger>
          <TabsTrigger value="keys">{t("detail.tabs.keys")}</TabsTrigger>
          <TabsTrigger value="grants">{t("detail.tabs.grants")}</TabsTrigger>
        </TabsList>
        <TabsContent value="overview" className="min-h-0 flex-1 overflow-y-auto">
          {detail && !loading && (
            <OverviewTab detail={detail} onChanged={load} onDeleted={onBack} />
          )}
        </TabsContent>
        <TabsContent value="keys" className="min-h-0 flex-1 overflow-y-auto">
          <ApiKeysTab
            serviceAccountId={id}
            accountEnabled={detail?.status === "enabled"}
            autoOpenIssue={autoOpenIssue}
            onKeysChanged={load}
          />
        </TabsContent>
        <TabsContent value="grants" className="min-h-0 flex-1 overflow-y-auto">
          <div className="space-y-2 py-8 text-center text-sm text-muted-foreground">
            <p>{t("detail.grantsPlaceholder")}</p>
            {/* Zero grants means every open-API call fails — that is correct, not a bug. */}
            <p>{t("detail.grantsEmptyHint")}</p>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}
