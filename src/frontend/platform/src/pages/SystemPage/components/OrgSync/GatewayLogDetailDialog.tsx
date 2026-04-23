import { Badge } from "@/components/bs-ui/badge"
import { Button } from "@/components/bs-ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table"
import { OrgSyncLog } from "@/types/api/orgSync"
import { formatIsoDateTime } from "@/util/utils"
import { useTranslation } from "react-i18next"

function statusVariant(
  status: string
): "default" | "secondary" | "destructive" | "outline" {
  if (status === "success") return "default"
  if (status === "partial") return "secondary"
  if (status === "failed") return "destructive"
  return "outline"
}

function pickErrMsg(row: Record<string, unknown>): string {
  const v = row.error_msg ?? row.error ?? row.message
  return typeof v === "string" ? v : JSON.stringify(v ?? "")
}

function pickExternalId(row: Record<string, unknown>): string {
  const v = row.external_id ?? row.externalId
  return typeof v === "string" ? v : String(v ?? "")
}

function pickEntity(row: Record<string, unknown>): string {
  const v = row.entity_type ?? row.event_type ?? row.type
  return typeof v === "string" ? v : String(v ?? "")
}

function isGatewayBatchSummary(row: Record<string, unknown>): boolean {
  return pickEntity(row) === "gateway_batch_summary"
}

function formatGatewaySummary(
  row: Record<string, unknown>,
  t: (key: string, opts?: Record<string, string | number>) => string,
): string {
  const ok = Number(row.members_sync_ok ?? 0)
  const fail = Number(row.members_sync_fail ?? 0)
  const leaders = Number(row.members_with_leader_depts ?? 0)
  const du = Number(row.dept_upsert_applied ?? 0)
  const dr = Number(row.dept_remove_applied ?? 0)
  return t("gatewayDetail.batchSummaryLine", {
    ok,
    fail,
    leaders,
    deptUpsert: du,
    deptRemove: dr,
  })
}

export function GatewayLogDetailDialog({
  log,
  onClose,
}: {
  log: OrgSyncLog | null
  onClose: () => void
}) {
  const { t } = useTranslation("orgSync")

  return (
    <Dialog open={!!log} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {t("gatewayDetail.title")} #{log?.id ?? ""}
          </DialogTitle>
        </DialogHeader>

        {log && (() => {
          const details = (log.error_details ?? []) as Record<string, unknown>[]
          const summaryRows = details.filter(isGatewayBatchSummary)
          const errorRows = details.filter((r) => !isGatewayBatchSummary(r))
          return (
          <div className="flex flex-col gap-4 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-muted-foreground">
                {t("gatewayDetail.status")}
              </span>
              <Badge variant={statusVariant(log.status)}>
                {t(`runStatus.${log.status}`, log.status)}
              </Badge>
              <span className="text-muted-foreground">
                {t("gatewayDetail.configId")}: {log.config_id}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-x-4 gap-y-1">
              <span className="text-muted-foreground">
                {t("gatewayDetail.startTime")}
              </span>
              <span>{formatIsoDateTime(log.start_time)}</span>
              <span className="text-muted-foreground">
                {t("gatewayDetail.endTime")}
              </span>
              <span>{formatIsoDateTime(log.end_time)}</span>
            </div>

            <div>
              <div className="mb-1 font-medium">{t("columns.deptSummary")}</div>
              <span className="text-xs text-muted-foreground">
                +{log.dept_created} / ~{log.dept_updated} / ×{log.dept_archived}
              </span>
            </div>
            <div>
              <div className="mb-1 font-medium">{t("columns.memberSummary")}</div>
              <span className="text-xs text-muted-foreground">
                +{log.member_created} / ~{log.member_updated} / 🚫
                {log.member_disabled} / ↻{log.member_reactivated}
              </span>
              <p className="mt-1 text-xs text-muted-foreground">
                {t("gatewayDetail.counterHint")}
              </p>
            </div>

            {summaryRows.length > 0 ? (
              <div className="rounded-md border border-dashed bg-muted/40 p-3 text-xs">
                <div className="mb-1 font-medium">{t("gatewayDetail.batchSummaryTitle")}</div>
                {summaryRows.map((row, idx) => (
                  <p key={idx} className="text-muted-foreground">
                    {formatGatewaySummary(row, t)}
                  </p>
                ))}
              </div>
            ) : null}

            {errorRows.length > 0 ? (
              <div>
                <div className="mb-2 font-medium">{t("gatewayDetail.errorsTitle")}</div>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("gatewayDetail.colType")}</TableHead>
                      <TableHead>{t("gatewayDetail.colExternalId")}</TableHead>
                      <TableHead>{t("gatewayDetail.colMessage")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {errorRows.map((row, idx) => (
                      <TableRow key={idx}>
                        <TableCell className="max-w-[120px] truncate font-mono text-xs">
                          {pickEntity(row)}
                        </TableCell>
                        <TableCell className="max-w-[140px] truncate font-mono text-xs">
                          {pickExternalId(row)}
                        </TableCell>
                        <TableCell className="break-all text-xs">
                          {pickErrMsg(row)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : null}

            <div className="flex justify-end">
              <Button variant="outline" onClick={onClose}>
                {t("actions.close")}
              </Button>
            </div>
          </div>
          )
        })()}
      </DialogContent>
    </Dialog>
  )
}
