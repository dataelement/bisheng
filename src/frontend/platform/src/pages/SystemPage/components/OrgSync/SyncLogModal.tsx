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
import { useOrgSyncStore } from "@/store/orgSyncStore"
import { OrgSyncConfig } from "@/types/api/orgSync"
import { formatIsoDateTime } from "@/util/utils"
import { useEffect } from "react"
import { useTranslation } from "react-i18next"

interface SyncLogModalProps {
  config: OrgSyncConfig | null
  onClose: () => void
}

function statusVariant(
  status: string
): "default" | "secondary" | "destructive" | "outline" {
  if (status === "success") return "default"
  if (status === "partial") return "secondary"
  if (status === "failed") return "destructive"
  return "outline"
}

export function SyncLogModal({ config, onClose }: SyncLogModalProps) {
  const { t } = useTranslation("orgSync")
  const logs = useOrgSyncStore((s) => s.logs)
  const logTotal = useOrgSyncStore((s) => s.logTotal)
  const logsLoading = useOrgSyncStore((s) => s.logsLoading)
  const fetchLogs = useOrgSyncStore((s) => s.fetchLogs)
  const clearLogs = useOrgSyncStore((s) => s.clearLogs)

  useEffect(() => {
    if (config) {
      fetchLogs(config.id)
    } else {
      clearLogs()
    }
  }, [config, fetchLogs, clearLogs])

  const handleClose = () => {
    clearLogs()
    onClose()
  }

  return (
    <Dialog open={!!config} onOpenChange={(open) => !open && handleClose()}>
      <DialogContent className="max-h-[80vh] max-w-4xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {t("syncLog.title", { name: config?.config_name ?? "" })}{" "}
            <span className="text-sm text-muted-foreground">
              ({logTotal})
            </span>
          </DialogTitle>
        </DialogHeader>

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("syncLog.status")}</TableHead>
              <TableHead>{t("syncLog.triggerType")}</TableHead>
              <TableHead>{t("syncLog.deptChanges")}</TableHead>
              <TableHead>{t("syncLog.memberChanges")}</TableHead>
              <TableHead>{t("syncLog.startTime")}</TableHead>
              <TableHead>{t("syncLog.endTime")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {logsLoading ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center">
                  {t("loading")}
                </TableCell>
              </TableRow>
            ) : logs.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center">
                  {t("syncLog.empty")}
                </TableCell>
              </TableRow>
            ) : (
              logs.map((log) => (
                <TableRow key={log.id}>
                  <TableCell>
                    <Badge variant={statusVariant(log.status)}>
                      {t(`runStatus.${log.status}`, log.status)}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {t(`triggerType.${log.trigger_type}`, log.trigger_type)}
                  </TableCell>
                  <TableCell>
                    <span className="text-xs">
                      +{log.dept_created} / ~{log.dept_updated} / ×
                      {log.dept_archived}
                    </span>
                  </TableCell>
                  <TableCell>
                    <span className="text-xs">
                      +{log.member_created} / ~{log.member_updated} / 🚫
                      {log.member_disabled} / ↻{log.member_reactivated}
                    </span>
                  </TableCell>
                  <TableCell>{formatIsoDateTime(log.start_time)}</TableCell>
                  <TableCell>{formatIsoDateTime(log.end_time)}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>

        <div className="flex justify-end">
          <Button variant="outline" onClick={handleClose}>
            {t("actions.close")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
