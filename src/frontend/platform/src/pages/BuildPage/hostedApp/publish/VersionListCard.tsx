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
 * The list is paged through `useTable` (design K11: `react-query` is frozen
 * on the platform, and this hook is the platform's own table state). It asks
 * the backend for `{ data, total }` one page at a time; the shared pager also
 * stays visible for a single page or an empty list.
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
import { Pagination } from "@bisheng/ui";
import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import {
  getHostedAppErrorMessage,
  getHostedAppVersionPageApi,
  type HostedAppVersion,
} from "@/controllers/API/hostedApp"
import { useTable } from "@/util/hook"
import { useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { versionOutcomeI18nKey } from "../types"
import { VersionReleaseNotes } from "../VersionReleaseNotes"
import { formatTimestamp, Panel, StatusTag } from "./Panel"

const PAGE_SIZE = 10

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

export function VersionListCard(props: VersionListCardProps) {
  return <VersionHistory key={props.appId} {...props} />
}

function VersionHistory({ appId, reloadKey = "" }: VersionListCardProps) {
  const { t } = useTranslation()
  const paginationLocale = usePaginationLocale();
  // `useTable` swallows a rejected fetch (it only clears `loading`), and a
  // non-owner is refused with a business code inside a 200 envelope. The
  // message is captured here so the refusal is shown, not rendered as "no
  // versions yet".
  const [failure, setFailure] = useState("")

  const {
    data,
    total,
    page,
    pageSize,
    loading,
    loaded,
    setPage,
    reload,
    filterData,
  } = useTable<HostedAppVersion>(
    { pageSize: PAGE_SIZE },
    (param: { page: number; pageSize: number }) =>
      getHostedAppVersionPageApi(appId, {
        page: param.page,
        pageSize: param.pageSize,
      })
        .then((res) => {
          setFailure("")
          return res
        })
        .catch((error: unknown) => {
          setFailure(
            getHostedAppErrorMessage(error) ||
              t("hostedApp.versionList.loadFailed"),
          )
          throw error
        }),
  )

  // The hook loads on mount by itself; these two only react to *changes*. A
  // different application starts over from page 1, a moved release re-reads
  // the page the reader is on.
  const tableRef = useRef({ reload, filterData })
  tableRef.current = { reload, filterData }
  const prevRef = useRef({ appId, reloadKey })
  useEffect(() => {
    const prev = prevRef.current
    if (prev.appId === appId && prev.reloadKey === reloadKey) return
    prevRef.current = { appId, reloadKey }
    if (prev.appId !== appId) tableRef.current.filterData({})
    else tableRef.current.reload()
  }, [appId, reloadKey])

  const rows = failure ? [] : data
  const waiting = loading || !loaded

  return (
    <Panel
      title={t("hostedApp.versionList.title")}
      description={t("hostedApp.versionList.readonlyHint")}
    >
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full min-w-[560px] text-sm">
          <thead className="bg-muted/50 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-normal">
                {t("hostedApp.versionList.no")}
              </th>
              <th className="px-3 py-2 text-left font-normal">
                {t("hostedApp.versionList.kind")}
              </th>
              <th className="px-3 py-2 text-left font-normal">
                {t("hostedApp.versionList.submittedAt")}
              </th>
              <th className="px-3 py-2 text-left font-normal">
                {t("hostedApp.versionList.outcome")}
              </th>
              <th className="w-28 px-3 py-2 text-left font-normal">
                {t("operations")}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((version) => (
              <tr key={version.version_id} className="border-t">
                <td className="px-3 py-2">
                  <span className="mr-2">{`v${version.version_no}`}</span>
                  {version.is_current && (
                    <StatusTag className="bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300">
                      {t("hostedApp.versionList.current")}
                    </StatusTag>
                  )}
                </td>
                <td className="px-3 py-2">
                  {t(
                    version.kind === "initial"
                      ? "hostedApp.versionList.kindInitial"
                      : "hostedApp.versionList.kindIteration",
                  )}
                </td>
                <td className="px-3 py-2 tabular-nums">
                  {formatTimestamp(version.submitted_at)}
                </td>
                <td className="px-3 py-2">
                  {t(versionOutcomeI18nKey(version))}
                </td>
                <td className="w-28 whitespace-nowrap px-3 py-2">
                  <VersionReleaseNotes notes={version.release_notes} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {waiting && (
        <p className="mt-3 text-sm text-muted-foreground">
          {t("hostedApp.versionList.loading")}
        </p>
      )}
      {!waiting && !failure && rows.length === 0 && (
        <p className="mt-3 text-sm text-muted-foreground">
          {t("hostedApp.versionList.empty")}
        </p>
      )}
      {!!failure && (
        <p className="mt-3 text-sm text-muted-foreground">{failure}</p>
      )}
      {!failure && (
        <Pagination locale={paginationLocale} size="small"
          className="mt-3 justify-end"
          current={page}
          pageSize={pageSize}
          total={total}
          showTotal={true}
          onChange={(next: number) => setPage(next)}
        />
      )}
    </Panel>
  )
}
