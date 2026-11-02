/**
 * Hosted-application detail page — `/build/apps/:appId` (AC-54 / AC-58).
 *
 * A management page, not an editor: three tabs, no conversation pane, no
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
import { appActionState } from "./appActions"
import { AppSecretSettings } from "./publish/AppSecretSettings"
import { LoadingIcon } from "@/components/bs-icons/loading"
import { Tabs } from "@bisheng/ui"
import { useTranslation } from "react-i18next"
import { useParams, useSearchParams } from "react-router-dom"
import { HostedAppHeader } from "./Header"
import { useHostedApp } from "./hooks/useHostedApp"
import { usePublishStatus } from "./hooks/usePublishStatus"
import { ApprovalStatusCard } from "./publish/ApprovalStatusCard"
import { CapabilityListCard } from "./publish/CapabilityListCard"
import { DangerZoneCard } from "./publish/DangerZoneCard"
import { Panel } from "./publish/Panel"
import { TierSelectCard } from "./publish/TierSelectCard"
import { VersionDiff } from "./publish/VersionDiff"
import { VersionListCard } from "./publish/VersionListCard"
import { VisibilityScopeSection } from "./publish/VisibilityScopeSection"
import { DataTab } from "./tabs/DataTab"
import { LogsTab } from "./tabs/LogsTab"
import { PublishTab } from "./tabs/PublishTab"
import { VersionsTab } from "./tabs/VersionsTab"

/** Four tabs (design D13-B): publish · data · run logs · versions. */
const TABS = ["publish", "data", "logs", "versions"] as const

export function HostedAppDetail() {
  const { t } = useTranslation()
  const { appId } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()

  const requested = searchParams.get("tab") || ""
  const requestedTab = (TABS as readonly string[]).includes(requested) ? requested : "publish"

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

  // The release read model is loaded here rather than inside the publish cards:
  // the same payload decides what three of them render *and* whether F054's
  // manual-publish button is drawn, and three components fetching it separately
  // would be three chances to disagree about one release.
  const {
    status: publishStatus,
    loading: publishLoading,
    forbidden: publishForbidden,
    errorMessage: publishError,
    reload: reloadPublishStatus,
  } = usePublishStatus(appId)

  const actions = appActionState(app?.allowed_actions)
  const activeTab = !actions.edit && ['data','logs'].includes(requestedTab) ? 'publish' : requestedTab

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
        activeKey={activeTab}
        onChange={handleTabChange}
        className="flex min-h-0 w-full flex-1 flex-col [&>[role=tabpanel]]:min-h-0 [&>[role=tabpanel]]:flex-1 [&>[role=tabpanel]]:overflow-hidden [&>[role=tabpanel]>div]:h-full"
        items={[
          { key: "publish", label: t("hostedApp.detail.tabs.publish"), children: <div className="min-h-0 flex-1 overflow-y-auto">
          <PublishTab
            app={app}
            instance={instance}
            instanceError={instanceError}
            onChanged={() => {
              reload()
              reloadInstance()
              reloadPublishStatus()
            }}
            canManualPublish={publishStatus?.can?.manual_publish}
            pendingReason={publishStatus?.pending_reason ?? null}
            pipelineSlot={
              <ApprovalStatusCard
                app={app}
                status={publishStatus}
                loading={publishLoading}
                forbidden={publishForbidden}
                errorMessage={publishError}
                onChanged={() => {
                  reload()
                  reloadPublishStatus()
                }}
              />
            }
            settingsSlot={
              <Panel title={t("hostedApp.publish.settingsTitle")}>
                <div className="flex flex-col gap-4">
                  {/*
                    AC-61 — the tier the release runs on. `can.submit` is the
                    server's own verdict on whether this application can be
                    submitted from inside the platform at all; it is false for
                    every CLI application (AC-06), which makes the section
                    read-only and its tier list unnecessary.
                  */}
                  <TierSelectCard
                    tier={publishStatus?.tier ?? null}
                    canSubmit={publishStatus?.can?.submit}
                  />
                  {/* AC-61 / AC-63 — what the release asks the platform for,
                      with anything that no longer resolves marked. Rendered
                      whenever the read model loaded: an application that
                      declares nothing says so, because a section that
                      disappears reads as "the page failed to load it". */}
                  {actions.edit && !!publishStatus && (
                    <CapabilityListCard capabilities={publishStatus.capabilities} />
                  )}
                  {actions.edit && <AppSecretSettings appId={app.app_id} canManage={actions.edit} canRebuild={actions.rebuild} />}
                  {actions.managePermission && <VisibilityScopeSection app={app} />}
                </div>
              </Panel>
            }
            historySlot={
              <VersionListCard
                appId={app.app_id}
                // Re-read whenever the release moved: a manual publish
                // latches the version's outcome server-side, and a list
                // loaded once would keep showing "pending online" for a
                // version that is already live.
                reloadKey={`${app.state}|${app.current_version_id || ""}|${app.pending_version_id || ""}`}
              />
            }
            dangerZoneSlot={<DangerZoneCard app={app} />}
          />
          </div> },
          ...(actions.edit ? [{ key: "data", label: t("hostedApp.detail.tabs.data"), children: <div className="min-h-0 flex-1 overflow-hidden">
          <DataTab appId={app.app_id} appName={app.slug || app.name} />
          </div> },
          { key: "logs", label: t("hostedApp.detail.tabs.logs"), children: <div className="min-h-0 flex-1 overflow-hidden">
          <LogsTab appId={app.app_id} />
          </div> }] : []),
          { key: "versions", label: t("hostedApp.detail.tabs.versions"), children: <div className="min-h-0 flex-1 overflow-y-auto">
          <VersionsTab
            appId={app.app_id}
            contentSlot={
              actions.edit ? <VersionDiff
                appId={app.app_id}
                reloadKey={`${app.state}|${app.current_version_id || ""}|${app.pending_version_id || ""}`}
              /> : null
            }
          />
          </div> },
        ]}
      />
    </div>
  )
}

// React.lazy in the router needs a default export; the named one above is
// what the codebase's component convention asks for. Both point at the same
// component.
export default HostedAppDetail
