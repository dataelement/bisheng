import { useServiceAccountRequestScope } from "./useServiceAccountManagementScope";
import { Button, SearchInput, Select, notification } from '@bisheng/ui';

import { Checkbox } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";


import {
Dialog,
DialogContent,
DialogDescription,
DialogFooter,
DialogHeader,
DialogTitle,
} from "@/components/bs-ui/dialog";

import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";

import {
getGrantablePermissionModelsApi,
getResourcePermissionContextApi,
type GrantablePermissionModel,
} from "@/controllers/API/permission";
import {
listServiceAccountGrantableResourcesApi,
mutateServiceAccountResourceGrantsApi,
} from "@/controllers/API/serviceAccount";
import { showApiError } from "@/controllers/request";
import type {
ServiceAccountGrantableResource,
ServiceAccountResourceGrant,
} from "@/types/api/openApi";
import { useEffect,useState } from "react";
import { useTranslation } from "react-i18next";
import {
createResourceGrantIdempotencyKey,
SERVICE_ACCOUNT_PERMISSION_TIERS,
SERVICE_ACCOUNT_RESOURCE_TYPES,
} from "./resourceGrantUtils";

function filterPermissionTiers(models: GrantablePermissionModel[]) {
  return SERVICE_ACCOUNT_PERMISSION_TIERS.flatMap((key) => {
    const model = models.find((item) => item.key === key)
    return model ? [model] : []
  })
}

export interface ResourceGrantDialogProps {
  serviceAccountId: number
  serviceAccountName: string
  existingGrants: ServiceAccountResourceGrant[]
  editingGrant: ServiceAccountResourceGrant | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onGranted: () => Promise<void>
}

export function ResourceGrantDialog({
  serviceAccountId,
  serviceAccountName,
  existingGrants,
  editingGrant,
  open,
  onOpenChange,
  onGranted,
}: ResourceGrantDialogProps) {
  const requestScope = useServiceAccountRequestScope();
  const { t } = useTranslation()
  const selectLabels = useSelectLabels()
  const [resourceType, setResourceType] = useState<string>(
    SERVICE_ACCOUNT_RESOURCE_TYPES[0],
  )
  const [keyword, setKeyword] = useState("")
  const [resources, setResources] = useState<ServiceAccountGrantableResource[]>(
    [],
  )
  const [selectedResources, setSelectedResources] = useState<
    ServiceAccountGrantableResource[]
  >([])
  const [models, setModels] = useState<GrantablePermissionModel[]>([])
  const [modelKey, setModelKey] = useState("")
  const [loading, setLoading] = useState(false)
  const [loadingResources, setLoadingResources] = useState(false)
  const [loadingModels, setLoadingModels] = useState(false)

  useEffect(() => {
    if (open) return
    setSelectedResources([])
    setModels([])
    setModelKey("")
    setKeyword("")
  }, [open])

  useEffect(() => {
    if (!open || editingGrant) return
    let active = true
    setResources([])
    setLoadingResources(true)
    const timer = window.setTimeout(() => {
      void listServiceAccountGrantableResourcesApi(serviceAccountId, {
          resource_type: resourceType,
          keyword: keyword.trim() || undefined,
        }, requestScope)
        .then((rows) => {
          if (active && rows) setResources(rows)
        })
        .catch(showApiError).finally(() => {
          if (active) setLoadingResources(false)
        })
    }, 250)
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [editingGrant, keyword, open, resourceType, serviceAccountId, requestScope])

  useEffect(() => {
    if (!open || !editingGrant) return
    const resource: ServiceAccountGrantableResource = {
      resource_type: editingGrant.resource_type,
      resource_id: editingGrant.resource_id,
      resource_name: editingGrant.resource_name,
      mode: "CUSTOM",
      resource_version: 0,
    }
    setResourceType(editingGrant.resource_type)
    setSelectedResources([resource])
    setModelKey(editingGrant.model_key)
    setModels([])
    setLoadingModels(true)
    void getGrantablePermissionModelsApi(
        editingGrant.resource_type as never,
        editingGrant.resource_id,
      )
      .then((available) => {
        if (available) setModels(filterPermissionTiers(available))
      })
      .catch(showApiError).finally(() => setLoadingModels(false))
  }, [editingGrant, open])

  const isGranted = (resource: ServiceAccountGrantableResource) =>
    existingGrants.some(
      (grant) =>
        grant.resource_type === resource.resource_type &&
        grant.resource_id === resource.resource_id,
    )

  const handleSelect = async (resource: ServiceAccountGrantableResource) => {
    if (isGranted(resource)) return
    const alreadySelected = selectedResources.some(
      (item) => item.resource_id === resource.resource_id,
    )
    if (alreadySelected) {
      const next = selectedResources.filter(
        (item) => item.resource_id !== resource.resource_id,
      )
      setSelectedResources(next)
      if (!next.length) {
        setModels([])
        setModelKey("")
      }
      return
    }
    setSelectedResources((current) => [...current, resource])
    if (!selectedResources.length) {
      setModelKey("")
      setModels([])
      setLoadingModels(true)
      try {
        const available = await getGrantablePermissionModelsApi(
            resource.resource_type as never,
            resource.resource_id,
          )
        if (available) setModels(filterPermissionTiers(available))
      } catch (error) {
        showApiError(error)
      } finally {
        setLoadingModels(false)
      }
    }
  }

  const handleGrant = async () => {
    if (!selectedResources.length || !modelKey) return
    setLoading(true)
    let completedCount = 0
    try {
      let completed = true
      for (const selected of selectedResources) {
        const context = await getResourcePermissionContextApi(
            selected.resource_type as never,
            selected.resource_id,
          )
        if (!context) {
          completed = false
          break
        }
        const result = await mutateServiceAccountResourceGrantsApi(
            serviceAccountId,
            selected.resource_type,
            selected.resource_id,
            {
              idempotency_key: createResourceGrantIdempotencyKey(),
              expected_resource_version: context.resource_version,
              expected_catalog_release_id: context.catalog_release_id,
              changes: editingGrant
                ? [
                    {
                      op: "MOVE",
                      assignee_id: editingGrant.assignee_id,
                      expected_assignee_version: editingGrant.assignee_version,
                      target_model_key: modelKey,
                    },
                  ]
                : [
                    {
                      op: "ADD",
                      model_key: modelKey,
                      subject: {
                        type: "service_account",
                        id: String(serviceAccountId),
                      },
                    },
                  ],
            }, requestScope)
        if (!result) {
          completed = false
          break
        }
        completedCount += 1
      }
      await onGranted()
      if (!completed) {
        setSelectedResources((current) => current.slice(completedCount))
        return
      }
      notification.open({ type: "success", title: String(t(
          editingGrant
            ? "openApiManagement.grants.change"
            : "openApiManagement.grants.add",
        ) ?? ''), description: String(t(
          editingGrant
            ? "openApiManagement.feedback.grantUpdated"
            : "openApiManagement.feedback.grantAdded",
        ) ?? '') })
      onOpenChange(false)
      setSelectedResources([])
      setModelKey("")
    } catch (error) {
      setSelectedResources(current => current.slice(completedCount))
      if (completedCount > 0) await onGranted().catch(showApiError)
      showApiError(error)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && loading) return
        onOpenChange(nextOpen)
      }}
    >
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>
            {t(
              editingGrant
                ? "openApiManagement.grants.change"
                : "openApiManagement.grants.add",
            )}
          </DialogTitle>
          <DialogDescription>
            {t("openApiManagement.grants.fixedSubjectHint", {
              name: serviceAccountName,
            })}
          </DialogDescription>
        </DialogHeader>
        {!editingGrant ? (
          <div className="space-y-3">
            <label className="space-y-1 text-sm">
              <span>{t("openApiManagement.grants.resourceType")}</span>
              <Select
                {...selectLabels}
                options={SERVICE_ACCOUNT_RESOURCE_TYPES.map((type) => ({
                  value: type,
                  label: t(`openApiManagement.resourceTypes.${type}`),
                }))}
                value={resourceType || null}
                onChange={(value) => {
                  if (value == null) return
                  setResourceType(String(value))
                  setSelectedResources([])
                  setModels([])
                  setModelKey("")
                }}
                aria-label={t("openApiManagement.grants.resourceType")}
              />
            </label>
            <label className="space-y-1 text-sm">
              <span>{t("openApiManagement.grants.resourceSearch")}</span>
              <SearchInput value={keyword} placeholder={t("openApiManagement.grants.search")} onChange={(event) => setKeyword(event.target.value)} />
            </label>
          </div>
        ) : null}
        {!editingGrant ? (
          <div className="max-h-64 overflow-y-auto rounded-md border">
            {resources.map((resource, index) => {
              const granted = isGranted(resource)
              const checked = selectedResources.some(
                (item) =>
                  item.resource_type === resource.resource_type &&
                  item.resource_id === resource.resource_id,
              )
              const checkboxId = `service-account-resource-${index}`
              return (
                <label
                  key={`${resource.resource_type}:${resource.resource_id}`}
                  htmlFor={checkboxId}
                  className={`flex w-full items-center gap-3 border-b px-3 py-2 text-left last:border-b-0 ${granted ? "cursor-not-allowed opacity-50" : "cursor-pointer hover:bg-muted"}`}
                >
                  <Checkbox
                    id={checkboxId}
                    checked={checked}
                    disabled={granted}
                    onCheckedChange={(value) => {
                      if (value === true || checked) void handleSelect(resource)
                    }}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm">
                      {resource.resource_name}
                    </span>
                    <span className="block text-xs text-muted-foreground">
                      {resource.resource_id}
                    </span>
                  </span>
                  {granted ? (
                    <span className="text-xs text-muted-foreground">
                      {t("openApiManagement.grants.granted")}
                    </span>
                  ) : null}
                </label>
              )
            })}
            {loadingResources ? (
              <p className="flex items-center justify-center gap-2 p-6 text-sm text-muted-foreground">
                <Outlined.Loading className="size-4 animate-spin" />
                {t("openApiManagement.grants.loadingResources")}
              </p>
            ) : null}
            {!loadingResources && !resources.length ? (
              <p className="p-6 text-center text-sm text-muted-foreground">
                {t("openApiManagement.grants.noResources")}
              </p>
            ) : null}
          </div>
        ) : (
          <div className="rounded-md border p-3 text-sm">
            <p className="font-medium">{editingGrant.resource_name}</p>
            <p className="text-muted-foreground">
              {t(
                `openApiManagement.resourceTypes.${editingGrant.resource_type}`,
              )}{" "}
              · {editingGrant.resource_id}
            </p>
          </div>
        )}
        <label className="space-y-1 text-sm">
          <span>{t("openApiManagement.grants.model")}</span>
          <Select
            {...selectLabels}
            options={models
              .filter((model) => model.key != null && model.key !== "")
              .map((model) => ({
                value: model.key,
                label: t(`openApiManagement.permissionTiers.${model.key}`),
              }))}
            value={modelKey || null}
            disabled={!selectedResources.length || loadingModels}
            onChange={(value) => setModelKey(value == null ? "" : String(value))}
            placeholder={t("openApiManagement.grants.modelPlaceholder")}
            aria-label={t("openApiManagement.grants.model")}
          />
        </label>
        <DialogFooter>
          <Button variant="outlined" disabled={loading} onClick={() => onOpenChange(false)} color="default">
            {t("cancel")}
          </Button>
          <Button disabled={
              loading ||
              !selectedResources.length ||
              !modelKey ||
              modelKey === editingGrant?.model_key
            } onClick={handleGrant}>
            {loading ? <Outlined.Loading className="mr-2 size-4 animate-spin" /> : null}
            {t(
              editingGrant
                ? "confirmButton"
                : "openApiManagement.grants.confirmGrant",
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
