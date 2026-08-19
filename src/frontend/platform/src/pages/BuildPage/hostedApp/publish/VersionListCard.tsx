/**
 * Read-only version record of one hosted application (AC-39 / AC-61).
 *
 * **There is no switch and no rollback here, by design.** The obvious reuse —
 * `BuildPage/CardSelectVersion.tsx` — is a trap twice over: it writes the
 * picked version back as the app's current version the moment it changes, and
 * the `version_list` the app list attaches is always empty for a hosted
 * application. Reusing it would give an empty dropdown that mutates a
 * *workflow* when clicked.
 *
 * The outcome column is mapped through i18n rather than printing the enum:
 * `online` / `rejected` / `withdrawn` are wire values, and an owner reading
 * "withdrawn" in a Chinese UI is reading a database column.
 *
 * A version with no outcome yet is *not* blank. It is either staged to go live
 * (`is_pending`, set the moment approval passes) or still under approval — two
 * states that look identical in the row data and completely different to the
 * person waiting on them.
 */
import {
  getHostedAppErrorMessage,
  getHostedAppVersionsApi,
  type HostedAppVersion,
} from "@/controllers/API/hostedApp"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { versionOutcomeI18nKey } from "../types"

interface VersionListCardProps {
  appId: string
  /**
   * Changes whenever the release moved, so the list re-reads.
   *
   * Passed from the page shell rather than watched here: a manual publish
   * latches the version's outcome on the server, and a list that only loaded
   * on mount would keep showing "pending online" for a version that is live.
   */
  reloadKey?: string
}

export function VersionListCard({ appId, reloadKey = "" }: VersionListCardProps) {
  const { t } = useTranslation()
  const [versions, setVersions] = useState<HostedAppVersion[]>([])
  const [loading, setLoading] = useState(true)
  const [failure, setFailure] = useState("")

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getHostedAppVersionsApi(appId)
      .then((rows) => {
        if (cancelled) return
        setVersions(rows || [])
        setFailure("")
      })
      .catch((error) => {
        if (cancelled) return
        setVersions([])
        setFailure(
          getHostedAppErrorMessage(error) ||
            t("hostedApp.versionList.loadFailed"),
        )
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [appId, reloadKey, t])

  return (
    <section className="rounded-md border bg-background-login p-4">
      <h2 className="mb-1 text-sm font-medium">
        {t("hostedApp.versionList.title")}
      </h2>
      <p className="mb-3 text-xs text-muted-foreground">
        {t("hostedApp.versionList.readonlyHint")}
      </p>

      <div className="overflow-x-auto rounded-md border">
        <table className="w-full min-w-[560px] text-sm">
          <thead className="bg-background-login text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left">
                {t("hostedApp.versionList.no")}
              </th>
              <th className="px-3 py-2 text-left">
                {t("hostedApp.versionList.kind")}
              </th>
              <th className="px-3 py-2 text-left">
                {t("hostedApp.versionList.submittedAt")}
              </th>
              <th className="px-3 py-2 text-left">
                {t("hostedApp.versionList.outcome")}
              </th>
            </tr>
          </thead>
          <tbody>
            {versions.map((version) => (
              <tr key={version.version_id} className="border-t">
                <td className="px-3 py-2">
                  <span className="mr-2">{`v${version.version_no}`}</span>
                  {version.is_current && (
                    <span className="rounded-sm bg-emerald-100 px-1 text-xs text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300">
                      {t("hostedApp.versionList.current")}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2">
                  {t(
                    version.kind === "initial"
                      ? "hostedApp.versionList.kindInitial"
                      : "hostedApp.versionList.kindIteration",
                  )}
                </td>
                <td className="px-3 py-2">{version.submitted_at || "-"}</td>
                <td className="px-3 py-2">{t(versionOutcomeI18nKey(version))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {loading && (
        <p className="mt-3 text-sm text-muted-foreground">
          {t("hostedApp.versionList.loading")}
        </p>
      )}
      {!loading && !failure && versions.length === 0 && (
        <p className="mt-3 text-sm text-muted-foreground">
          {t("hostedApp.versionList.empty")}
        </p>
      )}
      {!!failure && (
        <p className="mt-3 text-sm text-muted-foreground">{failure}</p>
      )}
    </section>
  )
}
