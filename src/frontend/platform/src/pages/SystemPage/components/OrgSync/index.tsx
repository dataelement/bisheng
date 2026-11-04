import { Button, Pagination } from '@bisheng/ui';
import { Tag } from "@bisheng/ui";


import {
Table,
TableBody,
TableCell,
TableHead,
TableHeader,
TableRow,
} from "@/components/bs-ui/table";
import { listGatewayOrgSyncLogsApi } from "@/controllers/API/orgSync";
import { showApiError } from "@/controllers/request";
import { OrgSyncLog } from "@/types/api/orgSync";
import { formatIsoDateTime } from "@/util/utils";
import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import { useCallback,useEffect,useState } from "react";
import { useTranslation } from "react-i18next";
import { GatewayLogDetailDialog } from "./GatewayLogDetailDialog";

const PAGE_SIZE = 20

function RunStatusBadge({ status }: { status: string | null | undefined }) {
  const { t } = useTranslation("orgSync")
  if (!status) return <span className="text-muted-foreground">-</span>
  const variantMap: Record<string, "success" | "warning" | "danger" | "brand"> = {
    success: "success",
    partial: "warning",
    failed: "danger",
    running: "brand",
  }
  const label = t(`runStatus.${status}`, status)
  return <Tag size="small" dot color={variantMap[status] || "default"}>{label}</Tag>
}

function hasErrorDetails(log: OrgSyncLog): boolean {
  return Array.isArray(log.error_details) && log.error_details.length > 0
}

export default function OrgSync() {
  const { t } = useTranslation("orgSync")
  const paginationLocale = usePaginationLocale()

  // Page-local server data — fetched here per C7 (stores must not call HTTP).
  const [gatewayLogs, setGatewayLogs] = useState<OrgSyncLog[]>([])
  const [gatewayTotal, setGatewayTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)

  const [detailLog, setDetailLog] = useState<OrgSyncLog | null>(null)

  const fetchGatewayLogs = useCallback(async (nextPage: number) => {
    setLoading(true)
    setPage(nextPage)
    await listGatewayOrgSyncLogsApi({ page: nextPage, limit: PAGE_SIZE }).then(({ data, total }) => {
        setGatewayLogs(data)
        setGatewayTotal(total)
      }).catch(showApiError).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    fetchGatewayLogs(1)
  }, [fetchGatewayLogs])

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4">
      <div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("columns.time")}</TableHead>
              <TableHead>{t("columns.status")}</TableHead>
              <TableHead>{t("columns.deptSummary")}</TableHead>
              <TableHead>{t("columns.memberSummary")}</TableHead>
              <TableHead>{t("columns.hasErrors")}</TableHead>
              <TableHead className="text-right">{t("columns.actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && gatewayLogs.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground">
                  {t("loading")}
                </TableCell>
              </TableRow>
            ) : gatewayLogs.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground">
                  {t("emptyHint")}
                </TableCell>
              </TableRow>
            ) : (
              gatewayLogs.map((log) => (
                <TableRow key={log.id}>
                  <TableCell className="whitespace-nowrap font-mono text-xs">
                    {formatIsoDateTime(log.end_time || log.start_time)}
                  </TableCell>
                  <TableCell>
                    <RunStatusBadge status={log.status} />
                  </TableCell>
                  <TableCell>
                    <span className="text-xs text-muted-foreground">
                      +{log.dept_created} / ~{log.dept_updated} / ×{log.dept_archived}
                    </span>
                  </TableCell>
                  <TableCell>
                    <span className="text-xs text-muted-foreground">
                      +{log.member_created} / ~{log.member_updated} / 🚫
                      {log.member_disabled} / ↻{log.member_reactivated}
                    </span>
                  </TableCell>
                  <TableCell>
                    {hasErrorDetails(log) ? (
                      <Tag size="small" dot color="danger">{t("columns.yes")}</Tag>
                    ) : (
                      <span className="text-muted-foreground">{t("columns.no")}</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button size="small" variant="outlined" onClick={() => setDetailLog(log)} color="default">
                      {t("actions.viewDetail")}
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <Pagination
        locale={paginationLocale}
        current={page}
        pageSize={PAGE_SIZE}
        total={gatewayTotal}
        showTotal
        disabled={loading}
        onChange={(nextPage) => void fetchGatewayLogs(nextPage)}
      />

      <GatewayLogDetailDialog log={detailLog} onClose={() => setDetailLog(null)} />
    </div>
  )
}
