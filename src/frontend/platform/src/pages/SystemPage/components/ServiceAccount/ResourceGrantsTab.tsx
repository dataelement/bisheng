import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table"
import { message } from "@/components/bs-ui/toast/use-toast"
import { listServiceAccountKeysApi, listServiceAccountResourceGrantsApi, mutateServiceAccountResourceGrantsApi } from "@/controllers/API/serviceAccount"
import { getResourcePermissionContextApi } from "@/controllers/API/permission"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import type { ApiKeyItem, ServiceAccountResourceGrant } from "@/types/api/openApi"
import { Loader2 } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { ResourceGrantDialog } from "./ResourceGrantDialog"

export interface ResourceGrantsTabProps {
  serviceAccountId: number
}

export function ResourceGrantsTab({ serviceAccountId }: ResourceGrantsTabProps) {
  const { t } = useTranslation()
  const [grants, setGrants] = useState<ServiceAccountResourceGrant[]>([])
  const [keys, setKeys] = useState<ApiKeyItem[]>([])
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingGrant, setEditingGrant] = useState<ServiceAccountResourceGrant | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadingData, setLoadingData] = useState(true)

  const load = useCallback(async () => {
    setLoadingData(true)
    try {
      const [grantRows, keyRows] = await Promise.all([
        captureAndAlertRequestErrorHoc(listServiceAccountResourceGrantsApi(serviceAccountId)),
        captureAndAlertRequestErrorHoc(listServiceAccountKeysApi(serviceAccountId)),
      ])
      if (grantRows) setGrants(grantRows)
      if (keyRows) setKeys(keyRows)
    } finally {
      setLoadingData(false)
    }
  }, [serviceAccountId])

  useEffect(() => { void load() }, [load])

  const remove = async (rows: ServiceAccountResourceGrant[]) => {
    setLoading(true)
    let completed = true
    try {
      const groups = rows.reduce<Record<string, ServiceAccountResourceGrant[]>>((result, row) => {
        const key = `${row.resource_type}:${row.resource_id}`
        result[key] = [...(result[key] || []), row]
        return result
      }, {})
      for (const group of Object.values(groups)) {
        if (!group?.length) continue
        const resource = group[0]
        const context = await captureAndAlertRequestErrorHoc(
          getResourcePermissionContextApi(resource.resource_type as never, resource.resource_id),
        )
        if (!context) {
          completed = false
          break
        }
        const result = await captureAndAlertRequestErrorHoc(mutateServiceAccountResourceGrantsApi(
          serviceAccountId,
          resource.resource_type,
          resource.resource_id,
          {
            idempotency_key: crypto.randomUUID(),
            expected_resource_version: context.resource_version,
            expected_catalog_release_id: context.catalog_release_id,
            changes: group.map((grant) => ({
              op: "REMOVE" as const,
              assignee_id: grant.assignee_id,
              expected_assignee_version: grant.assignee_version,
            })),
          },
        ))
        if (!result) {
          completed = false
          break
        }
      }
      if (completed) message({ description: t("openApiManagement.feedback.grantRevoked") })
      await load()
    } finally {
      setLoading(false)
    }
  }

  const handleRevoke = (grant: ServiceAccountResourceGrant) => {
    bsConfirm({
      desc: t(
        grant.source_type === "CREATOR_GRANT"
          ? "openApiManagement.grants.creatorRevokeConfirm"
          : "openApiManagement.grants.revokeConfirm",
        { name: grant.resource_name },
      ),
      onOk: (close) => { close(); void remove([grant]) },
    })
  }

  const editableGrants = grants.filter((grant) => (
    grant.editable && !grant.protected && grant.source_type !== "CREATOR_GRANT"
  ))
  const handleRevokeAll = () => {
    bsConfirm({
      desc: t("openApiManagement.grants.revokeAllConfirm", { count: editableGrants.length }),
      onOk: (close) => { close(); void remove(editableGrants) },
    })
  }

  const handleDialogOpenChange = (nextOpen: boolean) => {
    setDialogOpen(nextOpen)
    if (!nextOpen) setEditingGrant(null)
  }

  return (
    <div className="space-y-4">
      <div className="space-y-2 rounded-md border p-3 text-sm">
        <p>{t("openApiManagement.grants.keyScopeSummary", { count: keys.filter((key) => key.is_valid).length })}</p>
        {keys.filter((key) => key.is_valid).map((key) => (
          <p key={key.id} className="text-muted-foreground">
            <span className="font-medium text-foreground">{key.name}: </span>
            {key.scopes.join(", ") || t("openApiManagement.grants.noKeyScopes")}
          </p>
        ))}
        {keys.some((key) => key.is_valid && key.scopes.includes("delegate")) ? (
          <p className="font-medium text-orange-500">{t("openApiManagement.grants.delegateWarning")}</p>
        ) : null}
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="outline" disabled={loading || loadingData || !editableGrants.length} onClick={handleRevokeAll}>
          {t("openApiManagement.actions.revokeAll")}
        </Button>
        <Button disabled={loading || loadingData} onClick={() => { setEditingGrant(null); setDialogOpen(true) }}>
          {t("openApiManagement.grants.add")}
        </Button>
      </div>
      <Table>
        <TableHeader><TableRow>
          <TableHead>{t("openApiManagement.grants.resource")}</TableHead>
          <TableHead>{t("openApiManagement.grants.resourceType")}</TableHead>
          <TableHead>{t("openApiManagement.grants.model")}</TableHead>
          <TableHead>{t("openApiManagement.grants.source")}</TableHead>
          <TableHead className="text-right">{t("operations")}</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {grants.map((grant) => (
            <TableRow key={grant.assignee_id}>
              <TableCell>{grant.resource_name}</TableCell>
              <TableCell>{t(`openApiManagement.resourceTypes.${grant.resource_type}`)}</TableCell>
              <TableCell>{grant.model_name}</TableCell>
              <TableCell>{t(`openApiManagement.grantSources.${grant.source_type}`)}</TableCell>
              <TableCell className="text-right">
                <Button
                  variant="link"
                  disabled={loading || !grant.editable || grant.protected || grant.source_type === "CREATOR_GRANT"}
                  onClick={() => { setEditingGrant(grant); setDialogOpen(true) }}
                >
                  {t("edit")}
                </Button>
                <Button variant="link" disabled={loading || !grant.editable || grant.protected} onClick={() => handleRevoke(grant)}>
                  {t("openApiManagement.actions.revoke")}
                </Button>
              </TableCell>
            </TableRow>
          ))}
          {loadingData ? <TableRow><TableCell colSpan={5} className="py-8 text-center"><Loader2 aria-label={t("loading")} className="mx-auto size-5 animate-spin" /></TableCell></TableRow> : null}
          {!loadingData && !grants.length ? <TableRow><TableCell colSpan={5} className="text-center text-muted-foreground">{t("openApiManagement.grants.empty")}</TableCell></TableRow> : null}
        </TableBody>
      </Table>
      <ResourceGrantDialog serviceAccountId={serviceAccountId} existingGrants={grants} editingGrant={editingGrant} open={dialogOpen} onOpenChange={handleDialogOpenChange} onGranted={load} />
    </div>
  )
}
