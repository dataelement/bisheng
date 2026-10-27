import { Switch } from "@/components/bs-ui/switch"
import { mutateResourceGrantsApi, type ResourcePermissionContext, type PermissionResourceType, type PermissionGrantMutationChange } from "@/controllers/API/permission"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { useState } from "react"
import { useTranslation } from "react-i18next"

interface AllMembersPermissionProps {
  resourceType: PermissionResourceType
  resourceId: string
  context: ResourcePermissionContext
  onChanged: () => Promise<void>
}

export function AllMembersPermission({ resourceType, resourceId, context, onChanged }: AllMembersPermissionProps) {
  const { t } = useTranslation("permission")
  const [pending, setPending] = useState(false)
  const sources = context.all_members_sources ?? []
  if (!context.can_manage_permission || !context.tenant_id || !context.all_members_model_key) return null

  const handleChange = async (enabled: boolean) => {
    setPending(true)
    const changes: PermissionGrantMutationChange[] = enabled
      ? [{ op: "ADD", model_key: context.all_members_model_key!, subject: { type: "tenant", id: context.tenant_id! } }]
      : sources.map(source => ({ op: "REMOVE", assignee_id: source.assignee_id, expected_assignee_version: source.assignee_version }))
    try {
      await captureAndAlertRequestErrorHoc(mutateResourceGrantsApi(resourceType, resourceId, {
        idempotency_key: crypto.randomUUID(),
        expected_resource_version: context.resource_version,
        expected_catalog_release_id: context.catalog_release_id,
        changes,
      }))
      await onChanged()
    } finally {
      setPending(false)
    }
  }

  return <div className="mx-5 flex items-center justify-between gap-4 border-b py-3">
    <div>
      <p className="text-sm font-medium">{t("allMembers.title")}</p>
      <p className="text-xs text-muted-foreground">{t(sources.length ? "allMembers.publicHint" : "allMembers.selectedHint")}</p>
    </div>
    <Switch aria-label={t("allMembers.title")} checked={sources.length > 0} disabled={pending} onCheckedChange={handleChange} />
  </div>
}
