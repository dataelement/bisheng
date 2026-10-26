/**
 * Version tab — the read-only record of every version of this application.
 *
 * Source is `app_version` through the same wrapper the card's dropdown uses, so
 * the two can never disagree about what "current" means. There is deliberately
 * no switch and no rollback: version records are append-only, and the pipeline
 * (F055) owns everything that would write one — it fills `contentSlot` with the
 * pipeline-side columns.
 */
import {
  getHostedAppErrorMessage,
  getHostedAppVersionsApi,
  type HostedAppVersion,
} from "@/controllers/API/hostedApp"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { versionTerminalStateI18nKey } from "../types"

interface VersionsTabProps {
  appId: string
  /** F055 — pipeline / approval detail per version. */
  contentSlot?: React.ReactNode
}

export function VersionsTab({ appId, contentSlot = null }: VersionsTabProps) {
  const { t } = useTranslation()
  const [versions, setVersions] = useState<HostedAppVersion[]>([])
  const [loading, setLoading] = useState(true)
  const [failure, setFailure] = useState("")

  useEffect(() => {
    setLoading(true)
    getHostedAppVersionsApi(appId)
      .then((rows) => {
        setVersions(rows || [])
        setFailure("")
      })
      .catch((error) => {
        setVersions([])
        setFailure(
          getHostedAppErrorMessage(error) || t("hostedApp.versions.loadFailed"),
        )
      })
      .finally(() => setLoading(false))
  }, [appId, t])

  return (
    <div className="flex flex-col gap-4 pb-6">
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="bg-background-login text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left">{t("hostedApp.versions.no")}</th>
              <th className="px-3 py-2 text-left">{t("hostedApp.versions.kind")}</th>
              <th className="px-3 py-2 text-left">
                {t("hostedApp.versions.terminalState")}
              </th>
              <th className="px-3 py-2 text-left">
                {t("hostedApp.versions.submittedAt")}
              </th>
              <th className="px-3 py-2 text-left">
                {t("hostedApp.versions.marker")}
              </th>
            </tr>
          </thead>
          <tbody>
            {versions.map((version) => {
              // Mapped, never printed raw: `online` / `rejected` / `withdrawn`
              // are wire values, and an owner reading "withdrawn" in a Chinese
              // UI is reading a database column. A version with no latched
              // outcome keeps the dash — the marker column next door already
              // says whether it is staged or still under approval.
              const outcomeKey = versionTerminalStateI18nKey(
                version.terminal_state,
              )
              return (
                <tr key={version.version_id} className="border-t">
                  <td className="px-3 py-2">{`v${version.version_no}`}</td>
                  <td className="px-3 py-2">
                    {t(
                      version.kind === "initial"
                        ? "hostedApp.versions.kindInitial"
                        : "hostedApp.versions.kindIteration",
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {outcomeKey ? t(outcomeKey) : "-"}
                  </td>
                  <td className="px-3 py-2">{version.submitted_at || "-"}</td>
                  <td className="px-3 py-2">
                    {version.is_current && (
                      <span className="mr-1 rounded-sm bg-emerald-100 px-1 text-xs text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300">
                        {t("hostedApp.versions.current")}
                      </span>
                    )}
                    {version.is_pending && (
                      <span className="rounded-sm bg-amber-100 px-1 text-xs text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
                        {t("hostedApp.versions.pending")}
                      </span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {!loading && !failure && versions.length === 0 && (
        <p className="text-sm text-muted-foreground">
          {t("hostedApp.versions.empty")}
        </p>
      )}
      {!!failure && <p className="text-sm text-muted-foreground">{failure}</p>}
      {contentSlot}
    </div>
  )
}
