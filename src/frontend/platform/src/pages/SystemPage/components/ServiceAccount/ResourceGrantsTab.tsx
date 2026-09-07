import { Button } from "@/components/bs-ui/button"
import { Input } from "@/components/bs-ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table"
import {
  listServiceAccountResourceGrantsApi,
  mutateServiceAccountResourceGrantsApi,
} from "@/controllers/API/serviceAccount"
import {
  getGrantablePermissionModelsApi,
  getResourcePermissionContextApi,
  type GrantablePermissionModel,
  type PermissionGrantAssignee,
  type PermissionGrantMutationChange,
} from "@/controllers/API/permission"
import { useState } from "react"
import { useTranslation } from "react-i18next"

export interface ResourceGrantsTabProps {
  serviceAccountId: number
}

export function ResourceGrantsTab({ serviceAccountId }: ResourceGrantsTabProps) {
  const { t } = useTranslation()
  const [resourceType, setResourceType] = useState("")
  const [resourceId, setResourceId] = useState("")
  const [models, setModels] = useState<GrantablePermissionModel[]>([])
  const [grants, setGrants] = useState<PermissionGrantAssignee[]>([])
  const [resourceVersion, setResourceVersion] = useState(0)
  const [catalogReleaseId, setCatalogReleaseId] = useState(0)

  const load = async () => {
    const [context, availableModels, page] = await Promise.all([
      getResourcePermissionContextApi(resourceType as never, resourceId),
      getGrantablePermissionModelsApi(resourceType as never, resourceId),
      listServiceAccountResourceGrantsApi(serviceAccountId, resourceType, resourceId),
    ])
    setResourceVersion(context.resource_version)
    setCatalogReleaseId(context.catalog_release_id)
    setModels(availableModels)
    setGrants(page.data)
  }

  const mutate = async (changes: PermissionGrantMutationChange[]) => {
    const result = await mutateServiceAccountResourceGrantsApi(
      serviceAccountId,
      resourceType,
      resourceId,
      {
        idempotency_key: crypto.randomUUID(),
        expected_resource_version: resourceVersion,
        expected_catalog_release_id: catalogReleaseId,
        changes,
      },
    )
    setResourceVersion(result.resource_version)
    await load()
  }

  const handleGrant = async (modelKey: string) => {
    await mutate([{
      op: "ADD",
      model_key: modelKey,
      subject: { type: "service_account", id: String(serviceAccountId) },
    }])
  }

  const handleRevoke = async (grant: PermissionGrantAssignee) => {
    await mutate([{
      op: "REMOVE",
      assignee_id: grant.assignee_id,
      expected_assignee_version: grant.assignee_version,
    }])
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
        <Input value={resourceType} placeholder={t("openApiManagement.grants.resourceType")} onChange={(event) => setResourceType(event.target.value)} />
        <Input value={resourceId} placeholder={t("openApiManagement.grants.resourceId")} onChange={(event) => setResourceId(event.target.value)} />
        <Button variant="outline" disabled={!resourceType.trim() || !resourceId.trim()} onClick={load}>{t("openApiManagement.actions.load")}</Button>
      </div>
      <div className="flex flex-wrap gap-2">
        {models.map((model) => (
          <Button key={model.key} size="sm" variant="outline" onClick={() => handleGrant(model.key)}>
            {t("openApiManagement.grants.grantModel", { model: model.name })}
          </Button>
        ))}
      </div>
      <Table>
        <TableHeader><TableRow>
          <TableHead>{t("openApiManagement.grants.model")}</TableHead>
          <TableHead>{t("openApiManagement.grants.source")}</TableHead>
          <TableHead>{t("openApiManagement.grants.scope")}</TableHead>
          <TableHead className="text-right">{t("operations")}</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {grants.map((grant) => (
            <TableRow key={grant.assignee_id}>
              <TableCell>{grant.model.name}</TableCell>
              <TableCell>{grant.source.type}</TableCell>
              <TableCell>{grant.scope}</TableCell>
              <TableCell className="text-right"><Button variant="link" disabled={!grant.editable || grant.protected} onClick={() => handleRevoke(grant)}>{t("openApiManagement.actions.revoke")}</Button></TableCell>
            </TableRow>
          ))}
          {!grants.length ? <TableRow><TableCell colSpan={4} className="text-center text-muted-foreground">{t("openApiManagement.empty")}</TableCell></TableRow> : null}
        </TableBody>
      </Table>
    </div>
  )
}
