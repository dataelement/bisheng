/**
 * The build page's third card type (AC-51 / AC-52 / AC-53).
 *
 * Split out of `apps.tsx` because that file is already at the 600-line ceiling,
 * but also because the card and the detail page have to agree on three things
 * and only will if they share code: the state badge, the confirmation copy
 * (via `useHostedAppActions`) and the fact that the version dropdown is
 * **read-only**.
 *
 * That last one is the trap. The workflow card's `CardSelectVersion` writes the
 * picked version back as the app's current version, and the `version_list` the
 * list endpoint attaches is always empty for a hosted application — reusing it
 * would give an empty dropdown that mutates a *workflow* when clicked. So this
 * file has its own select: it loads `app_version` lazily on open and does
 * nothing at all when an item is picked.
 */
import CardComponent from "@/components/bs-comp/cardComponent"
import AppAvator from "@/components/bs-comp/cardComponent/avatar"
import { Badge } from "@/components/bs-ui/badge"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select"
import {
  getHostedAppVersionsApi,
  type HostedAppActionResult,
  type HostedAppVersion,
} from "@/controllers/API/hostedApp"
import { AppType } from "@/types/app"
import { useCallback, useState } from "react"
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
  /** Projected 2 (online) / 1 (everything else) so the shared switch works. */
  status?: number
  flow_type?: number
  /** The real application state; the badge falls back when it is absent. */
  app_state?: string
  write?: boolean
}

interface HostedAppVersionSelectProps {
  appId: string
}

/**
 * Read-only version dropdown (AC-52).
 *
 * Loads on first open rather than on mount: a page of 14 cards would otherwise
 * fire 14 requests nobody asked for. Picking an item is deliberately inert —
 * there is no version switch for hosted applications.
 */
function HostedAppVersionSelect({ appId }: HostedAppVersionSelectProps) {
  const { t } = useTranslation()
  const [versions, setVersions] = useState<HostedAppVersion[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)

  const handleOpenChange = useCallback(
    (open: boolean) => {
      if (!open || versions !== null || loading) return
      setLoading(true)
      getHostedAppVersionsApi(appId)
        .then((rows) => {
          // An empty `value` throws inside Radix's SelectItem and takes the
          // whole card list down with it; drop such a row instead.
          setVersions((rows || []).filter((row) => !!row.version_id))
          setFailed(false)
        })
        .catch(() => setFailed(true))
        .finally(() => setLoading(false))
    },
    [appId, loading, versions],
  )

  const current = versions?.find((item) => item.is_current)
  const label = current
    ? `v${current.version_no}`
    : t("hostedApp.version.placeholder")

  return (
    <Select value="" onOpenChange={handleOpenChange}>
      <SelectTrigger
        className="w-[120px] h-6"
        onClick={(event) => event.stopPropagation()}
        title={t("hostedApp.version.readonlyTip")}
      >
        <SelectValue placeholder={label}>{label}</SelectValue>
      </SelectTrigger>
      <SelectContent onClick={(event) => event.stopPropagation()}>
        <SelectGroup>
          {loading && (
            <div className="px-2 py-1.5 text-xs text-muted-foreground">
              {t("hostedApp.version.loading")}
            </div>
          )}
          {!loading && failed && (
            <div className="px-2 py-1.5 text-xs text-muted-foreground">
              {t("hostedApp.version.loadFailed")}
            </div>
          )}
          {!loading && !failed && versions !== null && versions.length === 0 && (
            <div className="px-2 py-1.5 text-xs text-muted-foreground">
              {t("hostedApp.version.empty")}
            </div>
          )}
          {!loading &&
            !failed &&
            (versions || []).map((version) => (
              <SelectItem key={version.version_id} value={version.version_id}>
                {`v${version.version_no}`}
                {version.is_current ? ` · ${t("hostedApp.version.current")}` : ""}
                {version.is_pending ? ` · ${t("hostedApp.version.pending")}` : ""}
              </SelectItem>
            ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}

interface HostedAppCardProps {
  item: HostedAppListItem
  currentUser: unknown
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
      onDelete={canDelete ? handleDelete : undefined}
      deleteDisabledHint={
        isDeleteBlockedByState(state) || online
          ? t("hostedApp.actions.deleteBlockedHint")
          : undefined
      }
      showSwitch={canSwitch}
      canSwitch={canSwitch}
      headSelecter={<HostedAppVersionSelect appId={String(item.id)} />}
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
          <Badge className="py-0 px-1 rounded-none rounded-br-md bg-[#6366f1]">
            {t("hostedApp.typeName")}
          </Badge>
        </div>
      }
    />
  )
}
