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
import type { DeveloperTokenRecord } from "@/controllers/API/developerToken"
import { formatIsoDateTime } from "@/util/utils"
import { useTranslation } from "react-i18next"
import {
  FileSyncRuleSummaryLabels,
  formatFileSyncRuleSummary,
} from "./developerTokenFileSyncRuleValidation"

interface DeveloperTokenTableProps {
  rows: DeveloperTokenRecord[]
  loading: boolean
  fileSyncSummaryLabels: FileSyncRuleSummaryLabels
  onEdit: (row: DeveloperTokenRecord) => void
  onViewSecret: (row: DeveloperTokenRecord) => void
  onDelete: (row: DeveloperTokenRecord) => void
}

export default function DeveloperTokenTable({
  rows,
  loading,
  fileSyncSummaryLabels,
  onEdit,
  onViewSecret,
  onDelete,
}: DeveloperTokenTableProps) {
  const { t } = useTranslation()
  return (
    <div className="min-h-0 overflow-x-auto rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("system.developerToken.columns.name")}</TableHead>
            <TableHead>{t("system.developerToken.columns.prefix")}</TableHead>
            <TableHead>{t("system.developerToken.columns.binding")}</TableHead>
            <TableHead>{t("system.developerToken.columns.status")}</TableHead>
            <TableHead>{t("system.developerToken.columns.controls")}</TableHead>
            <TableHead>{t("system.developerToken.columns.routes")}</TableHead>
            <TableHead>{t("system.developerToken.columns.fileSync")}</TableHead>
            <TableHead>{t("system.developerToken.columns.lastUsed")}</TableHead>
            <TableHead className="text-right">{t("system.developerToken.columns.actions")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {loading && rows.length === 0 ? (
            <EmptyRow text={t("system.developerToken.loading")} />
          ) : rows.length === 0 ? (
            <EmptyRow text={t("system.developerToken.empty")} />
          ) : (
            rows.map((row) => (
              <TableRow key={row.id}>
                <TableCell className="font-medium">{row.name}</TableCell>
                <TableCell className="font-mono text-xs">{row.token_prefix}</TableCell>
                <TableCell className="text-xs">
                  <div>{row.user_name || row.user_id}</div>
                  <div className="text-muted-foreground">{row.tenant_name || row.tenant_id}</div>
                </TableCell>
                <TableCell>
                  <Badge variant={row.enabled ? "default" : "destructive"}>
                    {t(`system.developerToken.${row.enabled ? "enabled" : "disabled"}`)}
                  </Badge>
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  <div>
                    {row.override_ip_whitelist
                      ? t("system.developerToken.overrideIp")
                      : t("system.developerToken.globalIp")}
                  </div>
                  <div>
                    {row.override_rate_limit
                      ? t("system.developerToken.overrideRate")
                      : t("system.developerToken.globalRate")}
                    {row.rate_limit_per_minute ? ` ${row.rate_limit_per_minute}/min` : ""}
                  </div>
                </TableCell>
                <TableCell className="text-xs">
                  {row.route_rule_count > 0
                    ? t("system.developerToken.routeRules.count", { count: row.route_rule_count })
                    : t("system.developerToken.routeRules.allRoutes")}
                </TableCell>
                <TableCell className="max-w-80 text-xs">
                  {formatFileSyncRuleSummary(row.file_sync_rule, fileSyncSummaryLabels)}
                </TableCell>
                <TableCell className="text-xs">
                  <div>{row.last_used_time ? formatIsoDateTime(row.last_used_time) : "-"}</div>
                  <div className="text-muted-foreground">{row.last_used_ip || "-"}</div>
                </TableCell>
                <TableCell className="space-x-2 text-right">
                  <Button size="sm" variant="outline" onClick={() => onEdit(row)}>
                    {t("system.developerToken.edit")}
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => onViewSecret(row)}>
                    {t("system.developerToken.viewSecret")}
                  </Button>
                  <Button size="sm" variant="destructive" onClick={() => onDelete(row)}>
                    {t("system.developerToken.delete")}
                  </Button>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  )
}

function EmptyRow({ text }: { text: string }) {
  return (
    <TableRow>
      <TableCell colSpan={9} className="text-center text-muted-foreground">
        {text}
      </TableCell>
    </TableRow>
  )
}
