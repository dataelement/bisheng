/**
 * Visibility scope — the second of the two doors onto the platform's permission
 * dialog (the first is the ⚙️ menu on the build-page card). Both open the very
 * same `PermissionDialog`; this section adds no authoring UI of its own, which
 * is what keeps one application's visibility from having two definitions.
 *
 * It sits in `PublishTab`'s `settingsSlot` rather than editing that file: F054,
 * F055 and F056 each own a block of that tab, and the slots exist so three
 * features can land without three edits to one JSX tree.
 *
 * Two behaviours here are load-bearing and easy to "simplify" away:
 *
 * - **The grants request is gated on `can_manage_permission`.** The platform's
 *   response interceptor turns a 403 on a GET into a whole-page redirect to
 *   `/403`, so firing the request for a non-manager would throw the user out of
 *   the detail page instead of showing them a quiet section. The gate is
 *   comfort only — the backend 403 is the actual boundary.
 * - **No react-query.** v3 is frozen by lint in this app; the neighbouring
 *   `useQuery` calls are legacy, not a pattern to copy.
 */
import { Button } from "@/components/bs-ui/button"
import { PermissionDialog } from "@/components/bs-comp/permission/PermissionDialog"
import {
  getResourcePermissionContextApi,
  getResourcePermissionGrantsApi,
  type PermissionGrantAssignee,
} from "@/controllers/API/permission"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import type { HostedAppDetail } from "@/controllers/API/hostedApp"
import { AlertTriangle } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { SubSection } from "./Panel"
import { isOwnerOnly, summarizeGrants } from "./visibilityScope"

interface VisibilityScopeSectionProps {
  app: HostedAppDetail
}

export function VisibilityScopeSection({ app }: VisibilityScopeSectionProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [canManage, setCanManage] = useState<boolean | null>(null)
  const [grants, setGrants] = useState<PermissionGrantAssignee[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    const context = await captureAndAlertRequestErrorHoc(
      getResourcePermissionContextApi("app", app.app_id),
    )
    const manage = !!context?.can_manage_permission
    setCanManage(manage)
    if (!manage) {
      setGrants([])
      setHasMore(false)
      setLoading(false)
      return
    }
    const page = await captureAndAlertRequestErrorHoc(
      getResourcePermissionGrantsApi("app", app.app_id),
    )
    setGrants(page?.data ?? [])
    setHasMore(!!page?.has_more)
    setLoading(false)
  }, [app.app_id])

  useEffect(() => {
    load()
  }, [load])

  const showBanner = isOwnerOnly(app.state, grants)

  const summary = loading
    ? t("hostedApp.visibility.loading")
    : // `total`, not `count`: i18next reserves `count` for plural selection
      // and types it as a number, which this "12+" string is not.
      t("hostedApp.visibility.summary", {
        total: summarizeGrants(grants, hasMore),
      })

  return (
    <SubSection
      label={t("hostedApp.visibility.title")}
      actions={
        canManage === false ? null : (
          <Button
            variant="outline"
            size="sm"
            disabled={canManage !== true}
            onClick={() => setOpen(true)}
          >
            {t("hostedApp.visibility.configure")}
          </Button>
        )
      }
    >
      {canManage === false ? (
        <p className="text-sm text-muted-foreground">
          {t("hostedApp.visibility.noManagePermission")}
        </p>
      ) : showBanner ? (
        // The banner replaces the summary rather than sitting on top of it:
        // "granted to 0 subjects" under "only you can see it" says it twice.
        <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 dark:border-amber-800 dark:bg-amber-950">
          <AlertTriangle
            aria-hidden="true"
            className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400"
          />
          <span className="text-sm">{t("hostedApp.visibility.ownerOnlyBanner")}</span>
        </div>
      ) : (
        <p className="text-sm">{summary}</p>
      )}

      <PermissionDialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next)
          // Re-read instead of updating optimistically: changing who can see an
          // application is a rare, deliberate act, and one round trip buys a
          // summary that is certainly right.
          if (!next) load()
        }}
        resourceType="app"
        resourceId={app.app_id}
        resourceName={app.name}
      />
    </SubSection>
  )
}
