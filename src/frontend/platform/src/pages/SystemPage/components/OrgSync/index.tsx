import { PlusIcon } from "@/components/bs-icons"
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
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
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { useOrgSyncStore } from "@/store/orgSyncStore"
import { OrgSyncConfig } from "@/types/api/orgSync"
import { formatIsoDateTime } from "@/util/utils"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { ProviderDialog } from "./ProviderDialog"
import { SyncLogModal } from "./SyncLogModal"
import { TestConnectionButton } from "./TestConnectionButton"

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

export default function OrgSync() {
  const { t } = useTranslation("orgSync")
  const { message } = useToast()

  const configs = useOrgSyncStore((s) => s.configs)
  const loading = useOrgSyncStore((s) => s.loading)
  const fetchConfigs = useOrgSyncStore((s) => s.fetchConfigs)
  const editingConfig = useOrgSyncStore((s) => s.editingConfig)
  const setEditingConfig = useOrgSyncStore((s) => s.setEditingConfig)
  const deleteConfig = useOrgSyncStore((s) => s.deleteConfig)
  const executeSync = useOrgSyncStore((s) => s.executeSync)

  const [dialogOpen, setDialogOpen] = useState(false)
  const [logModalConfig, setLogModalConfig] = useState<OrgSyncConfig | null>(null)

  useEffect(() => {
    fetchConfigs()
  }, [fetchConfigs])

  const handleCreate = () => {
    setEditingConfig(null)
    setDialogOpen(true)
  }

  const handleEdit = (config: OrgSyncConfig) => {
    setEditingConfig(config)
    setDialogOpen(true)
  }

  const handleExecute = (config: OrgSyncConfig) => {
    bsConfirm({
      title: t("confirmExecute.title"),
      desc: t("confirmExecute.desc", { name: config.config_name }),
      okTxt: t("actions.execute"),
      onOk: (close: () => void) => {
        captureAndAlertRequestErrorHoc(executeSync(config.id)).then((ok) => {
          if (ok !== false) {
            message({
              title: t("executeSuccess.title"),
              description: t("executeSuccess.desc"),
              variant: "success",
            })
          }
          close()
        })
      },
    })
  }

  const handleDelete = (config: OrgSyncConfig) => {
    bsConfirm({
      title: t("confirmDelete.title"),
      desc: t("confirmDelete.desc", { name: config.config_name }),
      okTxt: t("actions.delete"),
      onOk: (close: () => void) => {
        captureAndAlertRequestErrorHoc(deleteConfig(config.id)).then((ok) => {
          if (ok !== false) {
            message({
              title: t("deleteSuccess"),
              description: config.config_name,
              variant: "success",
            })
          }
          close()
        })
      },
    })
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">{t("title")}</h2>
          <p className="text-sm text-muted-foreground">{t("description")}</p>
        </div>
        <Button onClick={handleCreate}>
          <PlusIcon className="mr-1" />
          {t("actions.create")}
        </Button>
      </div>

      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("columns.configName")}</TableHead>
              <TableHead>{t("columns.provider")}</TableHead>
              <TableHead>{t("columns.syncStatus")}</TableHead>
              <TableHead>{t("columns.lastSync")}</TableHead>
              <TableHead>{t("columns.lastResult")}</TableHead>
              <TableHead className="text-right">
                {t("columns.actions")}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && configs.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground">
                  {t("loading")}
                </TableCell>
              </TableRow>
            ) : configs.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground">
                  {t("emptyHint")}
                </TableCell>
              </TableRow>
            ) : (
              configs.map((config) => (
                <TableRow key={config.id}>
                  <TableCell className="font-medium">{config.config_name}</TableCell>
                  <TableCell>
                    <Badge variant="outline">
                      {t(`providers.${config.provider}`, config.provider)}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {config.sync_status === "running" ? (
                      <Badge variant="outline">{t("syncStatus.running")}</Badge>
                    ) : (
                      <Badge variant="secondary">{t("syncStatus.idle")}</Badge>
                    )}
                  </TableCell>
                  <TableCell>{formatIsoDateTime(config.last_sync_at)}</TableCell>
                  <TableCell>
                    <RunStatusBadge status={config.last_sync_result} />
                  </TableCell>
                  <TableCell className="flex justify-end gap-2">
                    <TestConnectionButton configId={config.id} />
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={config.sync_status === "running"}
                      onClick={() => handleExecute(config)}
                    >
                      {t("actions.execute")}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleEdit(config)}
                    >
                      {t("actions.edit")}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setLogModalConfig(config)}
                    >
                      {t("actions.viewLogs")}
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => handleDelete(config)}
                    >
                      {t("actions.delete")}
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <ProviderDialog
        open={dialogOpen}
        onOpenChange={(open) => {
          setDialogOpen(open)
          if (!open) setEditingConfig(null)
        }}
        editingConfig={editingConfig}
      />
      <SyncLogModal
        config={logModalConfig}
        onClose={() => setLogModalConfig(null)}
      />
    </div>
  )
}
