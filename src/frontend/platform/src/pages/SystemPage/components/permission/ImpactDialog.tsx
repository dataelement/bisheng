import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog";
import {
  getPermissionCatalogDraftAffectedUsersApi,
  type PermissionCatalogAction,
  type PermissionCatalogActionChange,
  type PermissionCatalogAffectedUser,
  type PermissionCatalogAffectedUsersPage,
  type PermissionCatalogDraft,
  type PermissionCatalogModel,
  type PermissionCatalogModelChange,
  type PublishPermissionCatalogDraftRequest,
} from "@/controllers/API/permission";
import { Alert, Button } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { actionLabel } from "./actionLabels";
import { formatBlockerMessage } from "./blockerMessages";

interface ImpactDialogProps {
  variant?: "modelEdit"
  open: boolean
  draft: PermissionCatalogDraft | null
  onOpenChange: (open: boolean) => void
  onPublish: (
    draftId: number,
    payload: PublishPermissionCatalogDraftRequest,
  ) => Promise<unknown>
  onLoadAffectedUsers?: (
    draftId: number,
    page: number,
    pageSize: number,
  ) => Promise<PermissionCatalogAffectedUsersPage>
  // Used only to resolve blocker model keys and action codes into the display
  // names an operator recognises; optional so the dialog still renders raw
  // blockers when the catalog is unavailable.
  models?: PermissionCatalogModel[]
  actions?: PermissionCatalogAction[]
  now?: Date
}

const AFFECTED_USERS_PAGE_SIZE = 20

function isDraftExpiredOrChangedError(error: unknown): boolean {
  const code = (error as { status_code?: number; code?: number } | null)?.status_code
    ?? (error as { code?: number } | null)?.code
  if (code === 25007 || code === 25008) return true
  const message = typeof error === "string"
    ? error
    : ((error as { status_message?: string; message?: string } | null)?.status_message
      ?? (error as { message?: string } | null)?.message
      ?? "")
  return /expired|version|changed|no longer active/i.test(message)
}

function createPublishIdempotencyKey(): string {
  return `catalog-publish-${Date.now()}-${Math.random()
    .toString(36)
    .slice(2, 10)}`
}

export function ImpactDialog({
  variant,
  open,
  draft,
  onOpenChange,
  onPublish,
  onLoadAffectedUsers,
  models,
  actions,
  now,
}: ImpactDialogProps) {
  const { t } = useTranslation("permission")
  const [publishing, setPublishing] = useState(false)
  const [publishFailed, setPublishFailed] = useState(false)
  const [expiredDeadline, setExpiredDeadline] = useState<number | null>(null)
  const [serverExpired, setServerExpired] = useState(false)
  const [affectedUsers, setAffectedUsers] = useState<PermissionCatalogAffectedUser[]>(
    () => draft?.impact.affected_users ?? [],
  )
  const [affectedUsersTotal, setAffectedUsersTotal] = useState<number | undefined>(
    () => draft?.impact.affected_user_count,
  )
  const [affectedUsersHasMore, setAffectedUsersHasMore] = useState<boolean>(
    () => Boolean(draft?.impact.affected_users_has_more),
  )
  const [affectedUsersCrossTenant, setAffectedUsersCrossTenant] = useState<boolean>(
    () => Boolean(draft?.impact.affected_users_cross_tenant),
  )
  const [affectedUsersPage, setAffectedUsersPage] = useState(1)
  const [loadingUsers, setLoadingUsers] = useState(false)
  const [usersLoadFailed, setUsersLoadFailed] = useState(false)
  const previousFocus = useRef<HTMLElement | null>(null)
  const expiresAt = Date.parse(draft?.impact.expires_at ?? "")
  const hasExpired = () => expiresAt <= (now?.getTime() ?? Date.now())
  const expired = serverExpired || expiredDeadline === expiresAt || hasExpired()

  useEffect(() => {
    setServerExpired(false)
    setAffectedUsers(draft?.impact.affected_users ?? [])
    setAffectedUsersTotal(draft?.impact.affected_user_count)
    setAffectedUsersHasMore(Boolean(draft?.impact.affected_users_has_more))
    setAffectedUsersCrossTenant(Boolean(draft?.impact.affected_users_cross_tenant))
    setAffectedUsersPage(1)
    setLoadingUsers(false)
    setUsersLoadFailed(false)
  }, [draft])

  useEffect(() => {
    if (!open || now || expired || !Number.isFinite(expiresAt)) return
    const timer = window.setTimeout(
      () => setExpiredDeadline(expiresAt),
      Math.max(0, expiresAt - Date.now()),
    )
    return () => window.clearTimeout(timer)
  }, [expiresAt, expired, now, open])

  if (!draft) return null

  const blocked = draft.impact.blockers.length > 0
  const modelChanges = draft.impact.model_changes ?? []
  const modelEdit = variant === "modelEdit"
  const hasAffectedUsers = typeof affectedUsersTotal === "number"

  const duplicateUsernames = new Set<string>()
  const seenUsernames = new Set<string>()
  for (const item of affectedUsers) {
    if (seenUsernames.has(item.username)) duplicateUsernames.add(item.username)
    else seenUsernames.add(item.username)
  }

  const handleLoadMoreUsers = async () => {
    if (loadingUsers || !affectedUsersHasMore || expired) return
    if (hasExpired()) {
      setExpiredDeadline(expiresAt)
      return
    }
    const nextPage = affectedUsersPage + 1
    setLoadingUsers(true)
    setUsersLoadFailed(false)
    try {
      const fetcher = onLoadAffectedUsers ?? (
        (id: number, page: number, pageSize: number) =>
          getPermissionCatalogDraftAffectedUsersApi(id, { page, page_size: pageSize }, { silent: true })
      )
      const result = await fetcher(draft.draft_id, nextPage, AFFECTED_USERS_PAGE_SIZE)
      setAffectedUsers((current) => {
        const seen = new Set(current.map((item) => item.user_id))
        const appended = result.items.filter((item) => !seen.has(item.user_id))
        return [...current, ...appended]
      })
      setAffectedUsersTotal(result.total)
      setAffectedUsersHasMore(result.has_more)
      setAffectedUsersCrossTenant(result.cross_tenant)
      setAffectedUsersPage(result.page)
    } catch (error) {
      if (isDraftExpiredOrChangedError(error)) {
        setServerExpired(true)
      } else {
        setUsersLoadFailed(true)
      }
    } finally {
      setLoadingUsers(false)
    }
  }

  const levelName = (level: number | null) =>
    level === null
      ? t("actionLevel.unassigned")
      : t(`actionLevel.riskLevels.${level}`)

  const displayActionName = (code: string, fallback?: string) =>
    actionLabel(
      t,
      code,
      actions?.find((action) => action.code === code)?.name ?? fallback,
    )

  const displayModelName = (change: PermissionCatalogModelChange) => {
    if (
      change.kind === "STANDARD" &&
      ["viewer", "editor", "manager", "owner"].includes(change.model_key)
    ) {
      return t(`level.${change.model_key}`)
    }
    return change.model_name
  }

  const actionChangeLines = (change: PermissionCatalogActionChange) => {
    const name = displayActionName(change.action_code, change.action_name)
    const lines: string[] = []
    if (change.before_level !== change.after_level) {
      lines.push(
        t("impact.actionLevelChanged", {
          name,
          from: levelName(change.before_level),
          to: levelName(change.after_level),
        }),
      )
    }
    if (change.before_active !== change.after_active) {
      lines.push(
        t(
          change.after_active
            ? "impact.actionEnabled"
            : "impact.actionDisabled",
          { name },
        ),
      )
    }
    if (lines.length === 0) {
      lines.push(t("impact.actionConfigurationChanged", { name }))
    }
    return lines
  }

  const actionChangeDetails = (draft.impact.action_changes ?? []).flatMap((change) =>
    actionChangeLines(change).map((text, index) => ({ key: `${change.action_code}-${index}`, text })),
  )

  const handlePublish = async () => {
    if (publishing || expired || blocked) return
    if (hasExpired()) {
      setExpiredDeadline(expiresAt)
      return
    }
    setPublishing(true)
    setPublishFailed(false)
    try {
      await onPublish(draft.draft_id, {
        expected_current_release_id: draft.base_release_id,
        idempotency_key: createPublishIdempotencyKey(),
        confirmed: true,
      })
      onOpenChange(false)
    } catch {
      setPublishFailed(true)
    } finally {
      setPublishing(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => !publishing && onOpenChange(nextOpen)}>
      <DialogContent
        close={false}
        className="flex max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-lg flex-col gap-4 rounded-2xl border-border-base bg-bg-page p-4 shadow-modal dark:bg-bg-page sm:rounded-2xl"
        onOpenAutoFocus={() => {
          previousFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
        }}
        onCloseAutoFocus={(event) => {
          if (!previousFocus.current?.isConnected) return
          event.preventDefault()
          previousFocus.current.focus()
        }}
      >
        <DialogHeader className="shrink-0 text-left">
          <DialogTitle className="text-h4 text-text-1">{t(modelEdit ? "model.confirmEdit" : "impact.title")}</DialogTitle>
          <DialogDescription className="text-body text-text-2">
            {actionChangeDetails.length > 0
              ? t("actionLevel.pendingChanges", { count: actionChangeDetails.length })
              : t("impact.description")}
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 space-y-4 overflow-y-auto overscroll-contain">
          {actionChangeDetails.length > 0 && (
            <section className="space-y-2" aria-labelledby="impact-change-title">
              <h3 id="impact-change-title" className="text-body-sm font-medium text-text-1">
                {t("impact.changeTitle")}
              </h3>
              <ul className="space-y-1 rounded-lg border border-border-base px-3 py-2 text-body-sm text-text-2">
                {actionChangeDetails.map(({ key, text }) => <li key={key}>{text}</li>)}
              </ul>
            </section>
          )}

          {modelEdit && hasAffectedUsers ? (
            <section className="space-y-2 rounded-lg bg-fill-1 px-3 py-2" aria-labelledby="impact-users-title">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 id="impact-users-title" className="text-body-sm font-medium text-text-1">
                  {t("impact.affectedUsers")}
                </h3>
                <p data-testid="impact-affected-user-count" className="text-body font-semibold tabular-nums text-text-1">
                  {affectedUsersTotal}
                  <span className="ml-1 text-caption text-text-2">{t("impact.userUnit")}</span>
                </p>
              </div>
              <p className="text-caption text-text-2">
                {affectedUsersTotal > 0
                  ? t("impact.affectedUsersDescription", { count: affectedUsersTotal })
                  : t("impact.noAffectedUsers")}
              </p>
              {affectedUsersTotal > 0 && (
                <div
                  data-testid="impact-affected-users-list"
                  className="max-h-48 overflow-y-auto overscroll-contain rounded-lg border border-border-base bg-bg-page"
                >
                  <ul className="divide-y divide-border-base">
                    {affectedUsers.map((user) => (
                      <li
                        key={user.user_id}
                        className="flex items-center justify-between gap-2 px-3 py-2 text-body-sm text-text-1"
                      >
                        <span className="min-w-0 truncate">
                          {user.username}
                          {duplicateUsernames.has(user.username) && (
                            <span className="ml-1 text-caption text-text-3">#{user.user_id}</span>
                          )}
                        </span>
                        {affectedUsersCrossTenant && user.tenant_name && (
                          <span className="shrink-0 text-caption text-text-3">
                            {user.tenant_name}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                  {usersLoadFailed && (
                    <div className="flex items-center justify-between gap-2 border-t border-border-base px-3 py-2 text-caption text-danger">
                      <span>{t("impact.affectedUsersLoadFailed")}</span>
                      <Button
                        type="button"
                        size="small"
                        variant="link"
                        disabled={loadingUsers || expired}
                        onClick={() => void handleLoadMoreUsers()}
                      >
                        {t("catalog.retry")}
                      </Button>
                    </div>
                  )}
                  {affectedUsersHasMore && !usersLoadFailed && (
                    <div className="border-t border-border-base px-3 py-1.5 text-center">
                      <Button
                        type="button"
                        size="small"
                        variant="text"
                        color="default"
                        loading={loadingUsers}
                        disabled={loadingUsers || expired}
                        onClick={() => void handleLoadMoreUsers()}
                      >
                        {loadingUsers ? t("impact.loadingMoreUsers") : t("impact.loadMoreUsers")}
                      </Button>
                    </div>
                  )}
                </div>
              )}
            </section>
          ) : (
            <section className="space-y-1 rounded-lg bg-fill-1 px-3 py-2" aria-labelledby="impact-record-title">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 id="impact-record-title" className="text-body-sm font-medium text-text-1">
                  {t("impact.affectedRecords")}
                </h3>
                <p data-testid="impact-assignee-count" className="text-body font-semibold tabular-nums text-text-1">
                  {draft.impact.assignee_count}
                  <span className="ml-1 text-caption text-text-2">{t("impact.recordUnit")}</span>
                </p>
              </div>
              <p className="text-caption text-text-2">
                {draft.impact.assignee_count > 0 ? t("impact.recordDescription") : t("impact.noRecordChanges")}
              </p>
            </section>
          )}

          {modelChanges.length > 0 && (
            <section className="space-y-2" aria-labelledby="impact-model-title">
              <h3 id="impact-model-title" className="text-body-sm font-medium text-text-1">
                {t("impact.modelChanges")}
              </h3>
              <div className="divide-y divide-border-base rounded-lg border border-border-base">
                {modelChanges.map((change) => {
                  const levelChanged = change.before_level !== change.after_level
                  const actionsChanged =
                    change.added_action_codes.length > 0 ||
                    change.removed_action_codes.length > 0
                  return (
                    <article
                      key={change.model_key}
                      className="px-3 py-2 text-body-sm"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="font-medium text-text-1">
                          {displayModelName(change)}
                        </p>
                        <span className="text-caption text-text-3">
                          {t(
                            change.kind === "CUSTOM"
                              ? "model.kind.custom"
                              : "model.kind.standard",
                          )}
                        </span>
                      </div>
                      <ul className="mt-1 space-y-1 text-text-2">
                        {change.affected_assignee_count > 0 && (
                          <li>
                            {t("impact.modelAffectedRecords", {
                              count: change.affected_assignee_count,
                            })}
                          </li>
                        )}
                        {change.added_action_codes.length > 0 && (
                          <li className="text-success">
                            {t("impact.actionsAdded", {
                              actions: change.added_action_codes
                                .map((code) => displayActionName(code))
                                .join(t("impact.actionSeparator")),
                            })}
                          </li>
                        )}
                        {change.removed_action_codes.length > 0 && (
                          <li className="text-danger">
                            {t("impact.actionsRemoved", {
                              actions: change.removed_action_codes
                                .map((code) => displayActionName(code))
                                .join(t("impact.actionSeparator")),
                            })}
                          </li>
                        )}
                        {levelChanged && (
                          <li>
                            {t("impact.modelLevelChanged", {
                              from: levelName(change.before_level),
                              to: levelName(change.after_level),
                            })}
                          </li>
                        )}
                        {change.kind === "CUSTOM" &&
                          levelChanged &&
                          !actionsChanged && (
                            <li>{t("impact.customLevelOnly")}</li>
                          )}
                        {!levelChanged && !actionsChanged && (
                          <li>{t("impact.modelConfigurationChanged")}</li>
                        )}
                      </ul>
                    </article>
                  )
                })}
              </div>
            </section>
          )}

          {blocked && (
            <div
              className="rounded-lg bg-danger-tint p-3 text-body-sm text-text-1"
              role="alert"
            >
              <div className="flex items-center gap-2 font-medium">
                <Outlined.Attention aria-hidden="true" className="size-4 shrink-0 text-danger" />
                {t("impact.blocked")}
              </div>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                {draft.impact.blockers.map((blocker) => (
                  <li key={blocker}>
                    {formatBlockerMessage(t, blocker, { models, actions })}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {expired && (
            <Alert
              type="warning"
              description={t("impact.expired")}
              live
            />
          )}

          {publishFailed && !expired && (
            <Alert type="error" description={t("impact.publishFailed")} live />
          )}
        </div>

        <DialogFooter className="shrink-0 flex-row justify-end gap-3 sm:space-x-0">
          <Button type="button" color="default" variant="outlined" disabled={publishing} onClick={() => onOpenChange(false)}>
            {t("impact.cancel")}
          </Button>
          <Button type="button" disabled={publishing || expired || blocked} onClick={() => void handlePublish()}>
            {publishing ? t("impact.publishing") : t(modelEdit ? "model.confirmEdit" : "impact.publish")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
