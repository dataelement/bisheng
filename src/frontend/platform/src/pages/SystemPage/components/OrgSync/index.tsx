import { Badge } from "@/components/bs-ui/badge"
import { Button } from "@/components/bs-ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { useOrgSyncStore } from "@/store/orgSyncStore"
import { OrgSyncLog } from "@/types/api/orgSync"
import { formatIsoDateTime } from "@/util/utils"
import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { GatewayLogDetailDialog } from "./GatewayLogDetailDialog"

const PAGE_SIZE = 20

function RunStatusBadge({ status }: { status: string | null | undefined }) {
  const { t } = useTranslation("orgSync")
  if (!status) return <span className="text-muted-foreground">-</span>
  const variantMap: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
    success: "default",
    partial: "secondary",
    failed: "destructive",
    running: "outline",
  }
  const label = t(`runStatus.${status}`, status)
  return <Badge variant={variantMap[status] || "outline"}>{label}</Badge>
}

function hasErrorDetails(log: OrgSyncLog): boolean {
  return Array.isArray(log.error_details) && log.error_details.length > 0
}

/**
 * 仅展示网关掉 HMAC 推送写入的 org_sync_log（扁平列表 + 详情）。
 */
export default function OrgSync() {
  const { t } = useTranslation("orgSync")

  const gatewayLogs = useOrgSyncStore((s) => s.gatewayLogs)
  const gatewayTotal = useOrgSyncStore((s) => s.gatewayTotal)
  const loading = useOrgSyncStore((s) => s.loading)
  const page = useOrgSyncStore((s) => s.page)
  const fetchGatewayLogs = useOrgSyncStore((s) => s.fetchGatewayLogs)

  const [detailLog, setDetailLog] = useState<OrgSyncLog | null>(null)

  useEffect(() => {
    captureAndAlertRequestErrorHoc(fetchGatewayLogs(1))
  }, [fetchGatewayLogs])

  const maxPage = useMemo(
    () => Math.max(1, Math.ceil(gatewayTotal / PAGE_SIZE)),
    [gatewayTotal]
  )

  const goPrev = () => {
    if (page <= 1) return
    const next = page - 1
    captureAndAlertRequestErrorHoc(fetchGatewayLogs(next))
  }

  const goNext = () => {
    if (page >= maxPage) return
    const next = page + 1
    captureAndAlertRequestErrorHoc(fetchGatewayLogs(next))
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <div>
        <h2 className="text-lg font-semibold">{t("title")}</h2>
        <p className="text-sm text-muted-foreground">{t("description")}</p>
      </div>

      <div className="rounded-lg border">
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
                      <Badge variant="destructive">{t("columns.yes")}</Badge>
                    ) : (
                      <span className="text-muted-foreground">{t("columns.no")}</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setDetailLog(log)}
                    >
                      {t("actions.viewDetail")}
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {gatewayTotal > 0 && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>
            {t("pagination.total", { total: gatewayTotal })}{" "}
            {t("pagination.pageOf", { page, maxPage })}
          </span>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={page <= 1 || loading}
              onClick={goPrev}
            >
              {t("pagination.prev")}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={page >= maxPage || loading}
              onClick={goNext}
            >
              {t("pagination.next")}
            </Button>
          </div>
        </div>
      )}

      <GatewayLogDetailDialog log={detailLog} onClose={() => setDetailLog(null)} />
    </div>
  )
}
