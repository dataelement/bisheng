import type { User } from "@/types/api/user"
/** Hosted application cards share state badges and actions with the detail page. */
import CardComponent from "@/components/bs-comp/cardComponent"
import AppAvator from "@/components/bs-comp/cardComponent/avatar"
import { Button, Tag } from "@bisheng/ui"
import {
  getHostedAppVersionsApi,
  type HostedAppActionResult,
  type HostedAppVersion,
} from "@/controllers/API/hostedApp"
import { AppType } from "@/types/app"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { useNavigate } from "react-router-dom"
import {
  isDeleteBlockedByState,
  isOnline,
  isStateShownBySwitch,
  stateBadgeClass,
  stateI18nKey,
} from "./hostedApp/types"
import { useHostedAppActions, type HostedAppActionKind } from "./useHostedAppActions"

/** The row shape the app list yields for a hosted application (flow_type 35). */
export interface HostedAppListItem {
  id: string
  name: string
  description?: string
  logo?: string
  user_name?: string
  user_id?: number
  owner_active?: boolean
  /** Projected 2 (online) / 1 (everything else) so the shared switch works. */
  status?: number
  flow_type?: number
  /** The real application state; the badge falls back when it is absent. */
  app_state?: string
  write?: boolean
}

interface HostedAppVersionLabelProps {
  appId: string
  online: boolean
}

/** Hosted applications show version information; history lives on the detail page. */
function HostedAppVersionLabel({ appId, online }: HostedAppVersionLabelProps) {
  const { t } = useTranslation()
  const [versions, setVersions] = useState<HostedAppVersion[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [retryAttempt, setRetryAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    setVersions(null)
    setLoading(true)
    setFailed(false)
    getHostedAppVersionsApi(appId)
      .then((rows) => {
        if (cancelled) return
        setVersions((rows || []).filter((row) => !!row.version_id))
        setFailed(false)
      })
      .catch(() => { if (!cancelled) setFailed(true) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [appId, retryAttempt])

  const current = versions?.find((item) => item.is_current)
  const latest = versions?.reduce<HostedAppVersion | undefined>((newest, version) =>
    !newest || version.version_no > newest.version_no ? version : newest, undefined)
  const displayedVersion = online ? current : latest
  const label = loading
    ? t("hostedApp.version.loading")
    : failed
      ? t("hostedApp.version.loadFailed")
      : !versions?.length
        ? t("hostedApp.version.noCode")
        : displayedVersion
          ? t(online ? "hostedApp.version.running" : "hostedApp.version.latest", { version: `v${displayedVersion.version_no}` })
          : t("hostedApp.version.currentUnavailable")

  return (
    <span className="inline-flex h-6 max-w-40 items-center gap-1 whitespace-nowrap text-caption text-text-2">
      <span className="truncate" title={label}>{label}</span>
      {!loading && failed && (
        <Button
          color="primary"
          variant="link"
          size="small"
          type="button"
          onClick={(event) => {
            event.stopPropagation()
            setRetryAttempt(attempt => attempt + 1)
          }}
        >
          {t("build.retry")}
        </Button>
      )}
    </span>
  )
}

interface HostedAppCardProps {
  item: HostedAppListItem
  currentUser: Partial<User> | null
  isAdmin: boolean
  canDelete: boolean
  canSwitch: boolean
  canManagePermission: boolean
  labelPannel?: React.ReactNode
  onPermission: (item: HostedAppListItem) => void
  /**
   * Called after every action attempt, successful or not. `result` carries the
   * server's own verdict (`state`) so the list can be corrected from it
   * without waiting for a refetch; it is null when the call failed, which is
   * itself a reason to re-sync — a rejected "stop" is usually a stop that
   * already happened.
   */
  onChanged: (kind: HostedAppActionKind, result: HostedAppActionResult | null) => void
}

export function HostedAppCard({
  item,
  currentUser,
  isAdmin,
  canDelete,
  canSwitch,
  canManagePermission,
  labelPannel = null,
  onPermission,
  onChanged,
}: HostedAppCardProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { stopApp, resumeApp, deleteApp } = useHostedAppActions({
    onChanged,
  })

  // The list projection carries `status` (2/1) for the shared switch. The real
  // state comes as `app_state`; when the backend has not attached it, "online"
  // is still knowable from status and the rest stays unlabelled rather than
  // guessed.
  const state =
    item.app_state ?? (item.status === 2 ? "online" : undefined)
  const online = isOnline(state) || item.status === 2
  const mayDelete = Boolean(currentUser?.is_global_super)
    || Number(item.user_id) === Number(currentUser?.user_id)
    || (item.owner_active === false && Boolean(currentUser?.is_child_admin))
  const appRef = { appId: String(item.id), name: item.name, state }

  const handleCheckedChange = async (checked: boolean) => {
    return checked ? await resumeApp(appRef) : await stopApp(appRef)
  }

  const handleDelete = async () => {
    await deleteApp(appRef)
  }

  return (
    <CardComponent<HostedAppListItem>
      data={item}
      id={item.id}
      logo={
        <AppAvator id={item.name} flowType={item.flow_type} url={item.logo} />
      }
      type={AppType.HOSTED_APP}
      title={item.name}
      description={item.description}
      user={item.user_name}
      currentUser={currentUser}
      isAdmin={isAdmin}
      checked={online}
      onClick={() => navigate(`/build/apps/${item.id}`)}
      onCheckedChange={handleCheckedChange}
      // ⚙️ menu keeps only "manage permission" and "delete": leaving
      // `onAddTemp` undefined and `showCopy` false hides the other two without
      // touching the shared component.
      onAddTemp={undefined}
      showCopy={false}
      onPermission={canManagePermission ? onPermission : undefined}
      onDelete={canDelete && mayDelete ? handleDelete : undefined}
      deleteDisabledHint={
        isDeleteBlockedByState(state) || online
          ? t("hostedApp.actions.deleteBlockedHint")
          : undefined
      }
      showSwitch={canSwitch}
      canSwitch={canSwitch}
      headSelecter={<HostedAppVersionLabel appId={String(item.id)} online={online} />}
      labelPannel={labelPannel}
      footer={
        <div className="absolute right-0 bottom-0 flex items-center gap-1">
          {/* Online / offline is what the head switch already says; a second
              copy of it down here was noise. `draft` and `pending_capacity`
              are not on that axis — no flip of the switch reaches either — so
              those two keep their badge. */}
          {state && !isStateShownBySwitch(state) && (
            <span
              className={`py-0 px-1 rounded-sm text-xs ${stateBadgeClass(state)}`}
            >
              {t(stateI18nKey(state))}
            </span>
          )}
          <Tag size="small">
            {t("hostedApp.typeName")}
          </Tag>
        </div>
      }
    />
  )
}
