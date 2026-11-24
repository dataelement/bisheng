import { Badge } from "@/components/bs-ui/badge"
import { Button } from "@/components/bs-ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"
import AutoPagination from "@/components/bs-ui/pagination/autoPagination"
import { toast } from "@/components/bs-ui/toast/use-toast"
import {
  DeveloperTokenRecord,
  DeveloperTokenSyncRecord,
  listDeveloperTokenSyncRecordsApi,
} from "@/controllers/API/developerToken"
import { formatIsoDateTime } from "@/util/utils"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"

const PAGE_SIZE = 10

interface DeveloperTokenSyncRecordsDialogProps {
  token: DeveloperTokenRecord | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

function getStatusBadgeVariant(status: DeveloperTokenSyncRecord["status"]) {
  if (status === "success") return "default"
  if (status === "running") return "secondary"
  if (status === "skipped") return "outline"
  return "destructive"
}

export default function DeveloperTokenSyncRecordsDialog({
  token,
  open,
  onOpenChange,
}: DeveloperTokenSyncRecordsDialogProps) {
  const { t } = useTranslation()
  const [rows, setRows] = useState<DeveloperTokenSyncRecord[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<DeveloperTokenSyncRecord | null>(null)

  const loadPage = useCallback(async (tokenId: number, nextPage: number) => {
    setLoading(true)
    try {
      const result = await listDeveloperTokenSyncRecordsApi(tokenId, {
        page: nextPage,
        limit: PAGE_SIZE,
      })
      setRows(result.data)
      setTotal(result.total)
      setPage(nextPage)
    } catch {
      toast({
        title: t("prompt"),
        variant: "error",
        description: t("system.developerToken.syncRecords.loadFailed"),
      })
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    if (!open || !token) {
      setRows([])
      setTotal(0)
      setPage(1)
      setDetail(null)
      return
    }
    void loadPage(token.id, 1)
  }, [loadPage, open, token])

  const handleCopy = async (message: string) => {
    try {
      await navigator.clipboard.writeText(message)
      toast({
        title: t("prompt"),
        variant: "success",
        description: t("system.developerToken.syncRecords.copied"),
      })
    } catch {
      toast({
        title: t("prompt"),
        variant: "error",
        description: t("system.developerToken.syncRecords.copyFailed"),
      })
    }
  }

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-5xl">
          <DialogHeader>
            <DialogTitle>
              {t("system.developerToken.syncRecords.title", {
                name: token?.name || "-",
              })}
            </DialogTitle>
          </DialogHeader>
          <p className="text-xs text-muted-foreground">
            {t("system.developerToken.syncRecords.hint")}
          </p>
          {loading && rows.length === 0 ? (
            <p className="py-6 text-sm text-muted-foreground">
              {t("system.developerToken.syncRecords.loading")}
            </p>
          ) : rows.length === 0 ? (
            <p className="py-6 text-sm text-muted-foreground">
              {t("system.developerToken.syncRecords.empty")}
            </p>
          ) : (
            <div className="max-h-[60vh] overflow-auto rounded-md border">
              <table className="min-w-full text-sm">
                <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2">{t("system.developerToken.syncRecords.columns.id")}</th>
                    <th className="px-3 py-2">{t("system.developerToken.syncRecords.columns.interface")}</th>
                    <th className="px-3 py-2">{t("system.developerToken.syncRecords.columns.trigger")}</th>
                    <th className="px-3 py-2">{t("system.developerToken.syncRecords.columns.status")}</th>
                    <th className="px-3 py-2">{t("system.developerToken.syncRecords.columns.fileName")}</th>
                    <th className="px-3 py-2">{t("system.developerToken.syncRecords.columns.startTime")}</th>
                    <th className="px-3 py-2">{t("system.developerToken.syncRecords.columns.duration")}</th>
                    <th className="px-3 py-2">{t("system.developerToken.syncRecords.columns.error")}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id} className="border-t">
                      <td className="px-3 py-2">{row.id}</td>
                      <td className="max-w-[220px] truncate px-3 py-2" title={row.interface}>
                        {row.interface}
                      </td>
                      <td className="px-3 py-2">
                        {t(`system.developerToken.syncRecords.triggerTypes.${row.trigger_type}`, {
                          defaultValue: row.trigger_type,
                        })}
                      </td>
                      <td className="px-3 py-2">
                        <Badge variant={getStatusBadgeVariant(row.status)}>
                          {t(`system.developerToken.syncRecords.statuses.${row.status}`, {
                            defaultValue: row.status,
                          })}
                        </Badge>
                      </td>
                      <td className="max-w-[160px] truncate px-3 py-2" title={row.file_name || undefined}>
                        {row.file_name || "-"}
                      </td>
                      <td className="px-3 py-2">{formatIsoDateTime(row.start_time)}</td>
                      <td className="px-3 py-2">
                        {row.duration_ms != null ? `${row.duration_ms} ms` : "-"}
                      </td>
                      <td className="px-3 py-2">
                        {row.error_message ? (
                          <Button size="sm" variant="outline" onClick={() => setDetail(row)}>
                            {t("system.developerToken.syncRecords.viewError")}
                          </Button>
                        ) : (
                          "-"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {total > PAGE_SIZE && (
            <AutoPagination
              className="justify-end"
              page={page}
              pageSize={PAGE_SIZE}
              total={total}
              onChange={(nextPage) => {
                if (token) {
                  void loadPage(token.id, nextPage)
                }
              }}
            />
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {t("system.developerToken.syncRecords.close")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(detail)} onOpenChange={(next) => !next && setDetail(null)}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>{t("system.developerToken.syncRecords.errorDetailTitle")}</DialogTitle>
          </DialogHeader>
          {detail?.error_truncated && (
            <p className="text-xs text-muted-foreground">
              {t("system.developerToken.syncRecords.truncatedHint")}
            </p>
          )}
          <pre className="max-h-[50vh] overflow-auto whitespace-pre-wrap break-words rounded-md border bg-muted/20 p-3 text-xs">
            {detail?.error_message || "-"}
          </pre>
          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              disabled={!detail?.error_message}
              onClick={() => {
                if (detail?.error_message) {
                  void handleCopy(detail.error_message)
                }
              }}
            >
              {t("system.developerToken.syncRecords.copy")}
            </Button>
            <Button variant="outline" onClick={() => setDetail(null)}>
              {t("system.developerToken.syncRecords.close")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
