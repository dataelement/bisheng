import { Button } from "@bisheng/ui"
import type { HostedAppDetail } from "@/controllers/API/hostedApp"
import { appActionState } from "../appActions"
import { useTranslation } from "react-i18next"
import { useNavigate } from "react-router-dom"
import { useHostedAppActions } from "../../useHostedAppActions"
import { isDeleteBlockedByState } from "../types"
import { Panel } from "./Panel"

interface DangerZoneCardProps {
  app: HostedAppDetail
}

export function DangerZoneCard({ app }: DangerZoneCardProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { deleteApp } = useHostedAppActions({
    onChanged: (kind, result) => {
      // A deleted application has no detail page left to stand on; anything
      // else (a refusal, a lost race) keeps the user here to see the toast.
      if (kind === "delete" && result && result.ok !== false) {
        navigate("/build/apps")
      }
    },
  })

  const blocked = isDeleteBlockedByState(app.state)

  if (!appActionState(app.allowed_actions).delete) return null

  const handleDelete = async () => {
    if (blocked) return
    await deleteApp({ appId: app.app_id, name: app.name, state: app.state })
  }

  return (
    <Panel
      tone="danger"
      title={t("hostedApp.dangerZone.title")}
      description={
        <>
          {t("hostedApp.dangerZone.deleteDesc")}
          {blocked && (
            <span className="mt-1 block">
              {t("hostedApp.dangerZone.blockedByOnline")}
            </span>
          )}
        </>
      }
      actions={
        <Button
          variant="destructive"
          size="sm"
          disabled={blocked}
          onClick={handleDelete}
        >
          {t("hostedApp.dangerZone.delete")}
        </Button>
      }
    />
  )
}
