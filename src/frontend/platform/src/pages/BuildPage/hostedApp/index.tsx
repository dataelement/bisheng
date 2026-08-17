/**
 * Hosted-application detail page — `/build/apps/:appId` (AC-54 / AC-58).
 *
 * A management page, not an editor: four tabs, no conversation pane, no
 * assistant. It rides the existing `build` route permission, so it adds no menu
 * entry and no permission point.
 *
 * The active tab lives in the query string. Local state alone would send the
 * user back to "publish" on every refresh, and a run-log tab you have to find
 * again after each reload is a tab nobody uses.
 *
 * A caller who may not see this application gets 16106 inside a 200 envelope,
 * which lands here as an inline notice. The alternative — a real 403 — makes
 * the platform interceptor navigate the whole SPA to `/403`.
 */
import { LoadingIcon } from "@/components/bs-icons/loading"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/bs-ui/tabs"
import { useTranslation } from "react-i18next"
import { useParams, useSearchParams } from "react-router-dom"
import { HostedAppHeader } from "./Header"
import { useHostedApp } from "./hooks/useHostedApp"
import { DataTab } from "./tabs/DataTab"
import { LogsTab } from "./tabs/LogsTab"
import { PublishTab } from "./tabs/PublishTab"
import { VersionsTab } from "./tabs/VersionsTab"

const TABS = ["publish", "data", "logs", "versions"] as const

export function HostedAppDetail() {
  const { t } = useTranslation()
  const { appId } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()

  const requested = searchParams.get("tab") || ""
  const activeTab = (TABS as readonly string[]).includes(requested)
    ? requested
    : "publish"

  const {
    app,
    instance,
    loading,
    error,
    errorMessage,
    instanceError,
    reload,
    reloadInstance,
  } = useHostedApp(appId)

  const handleTabChange = (value: string) => {
    // `replace` so the back button leaves the page instead of walking the tabs.
    setSearchParams({ tab: value }, { replace: true })
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <LoadingIcon />
      </div>
    )
  }

  if (error || !app) {
    const message =
      error === "forbidden"
        ? t("hostedApp.detail.noPermission")
        : error === "not_found"
          ? t("hostedApp.detail.notFound")
          : errorMessage || t("hostedApp.detail.loadFailed")
    return (
      <div className="flex h-full items-center justify-center px-10">
        <p className="text-sm text-muted-foreground">{message}</p>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 w-full flex-col px-6 pt-4">
      <HostedAppHeader app={app} />
      <Tabs
        value={activeTab}
        onValueChange={handleTabChange}
        className="flex min-h-0 w-full flex-1 flex-col"
      >
        <TabsList className="shrink-0 self-start">
          <TabsTrigger value="publish">
            {t("hostedApp.detail.tabs.publish")}
          </TabsTrigger>
          <TabsTrigger value="data">{t("hostedApp.detail.tabs.data")}</TabsTrigger>
          <TabsTrigger value="logs">{t("hostedApp.detail.tabs.logs")}</TabsTrigger>
          <TabsTrigger value="versions">
            {t("hostedApp.detail.tabs.versions")}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="publish" className="min-h-0 flex-1 overflow-y-auto">
          <PublishTab
            app={app}
            instance={instance}
            instanceError={instanceError}
            onChanged={() => {
              reload()
              reloadInstance()
            }}
          />
        </TabsContent>
        <TabsContent value="data" className="min-h-0 flex-1 overflow-y-auto">
          <DataTab />
        </TabsContent>
        <TabsContent value="logs" className="min-h-0 flex-1 overflow-hidden">
          <LogsTab appId={app.app_id} />
        </TabsContent>
        <TabsContent value="versions" className="min-h-0 flex-1 overflow-y-auto">
          <VersionsTab appId={app.app_id} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

// React.lazy in the router needs a default export; the named one above is
// what the codebase's component convention asks for. Both point at the same
// component.
export default HostedAppDetail
