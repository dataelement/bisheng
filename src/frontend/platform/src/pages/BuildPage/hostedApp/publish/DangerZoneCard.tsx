/**
 * Danger zone of the publish tab — explicit deletion, owner only (AC-61 / AC-62).
 *
 * The action itself is F054's `useHostedAppActions.deleteApp`, reused rather
 * than re-implemented: the confirmation copy *is* part of the contract (it has
 * to say that code, conversation history and production data all go), and a
 * second dialog would drift from the card's within one release.
 *
 * Two guards, and they are not the same guard:
 *
 * - **Owner only.** A tenant administrator may stop and resume somebody's
 *   application but may not delete it, and the permission runtime cannot say so
 *   — it short-circuits administrators to ALLOW. The section is therefore not
 *   rendered at all for a non-owner: there is nothing here they can do, and a
 *   greyed-out "delete everything" button is an invitation to go looking for
 *   the way around it.
 * - **Online blocks deletion** (AC-42). Disabled with the remedy spelled out
 *   ("take it offline first") rather than hidden, because that one *is*
 *   reachable — the owner simply has to do something first.
 *
 * Both are comfort only. The backend refuses either way.
 */
import { Button } from "@/components/bs-ui/button"
import type { HostedAppDetail } from "@/controllers/API/hostedApp"
import { userContext } from "@/contexts/userContext"
import { useContext } from "react"
import { useTranslation } from "react-i18next"
import { useNavigate } from "react-router-dom"
import { useHostedAppActions } from "../../useHostedAppActions"
import { isDeleteBlockedByState } from "../types"

interface DangerZoneCardProps {
  app: HostedAppDetail
}

export function DangerZoneCard({ app }: DangerZoneCardProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { user } = useContext(userContext)
  const { deleteApp } = useHostedAppActions({
    onChanged: (kind, result) => {
      // A deleted application has no detail page left to stand on; anything
      // else (a refusal, a lost race) keeps the user here to see the toast.
      if (kind === "delete" && result && result.ok !== false) {
        navigate("/build/apps")
      }
    },
  })

  const isOwner = Number(user?.user_id) === Number(app.owner_user_id)
  const blocked = isDeleteBlockedByState(app.state)

  if (!isOwner) return null

  const handleDelete = async () => {
    if (blocked) return
    await deleteApp({ appId: app.app_id, name: app.name, state: app.state })
  }

  return (
    <section className="rounded-md border border-red-300 bg-background-login p-4 dark:border-red-800">
      <h2 className="mb-1 text-sm font-medium text-red-600 dark:text-red-400">
        {t("hostedApp.dangerZone.title")}
      </h2>
      <p className="mb-3 text-xs text-muted-foreground">
        {t("hostedApp.dangerZone.deleteDesc")}
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="destructive"
          size="sm"
          disabled={blocked}
          onClick={handleDelete}
        >
          {t("hostedApp.dangerZone.delete")}
        </Button>
        {blocked && (
          <span className="text-xs text-muted-foreground">
            {t("hostedApp.dangerZone.blockedByOnline")}
          </span>
        )}
      </div>
    </section>
  )
}
