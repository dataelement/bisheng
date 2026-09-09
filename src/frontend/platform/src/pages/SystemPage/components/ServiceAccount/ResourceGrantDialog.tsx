import { Button } from "@/components/bs-ui/button"
import { Checkbox } from "@/components/bs-ui/checkBox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"
import { SearchInput } from "@/components/bs-ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select"
import { toast } from "@/components/bs-ui/toast/use-toast"
import {
  listServiceAccountGrantableResourcesApi,
  mutateServiceAccountResourceGrantsApi,
} from "@/controllers/API/serviceAccount"
import {
  getGrantablePermissionModelsApi,
  getResourcePermissionContextApi,
  type GrantablePermissionModel,
} from "@/controllers/API/permission"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import type {
  ServiceAccountGrantableResource,
  ServiceAccountResourceGrant,
} from "@/types/api/openApi"
import { Loader2 } from "lucide-react"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"

const RESOURCE_TYPES = [
  "knowledge_space",
  "knowledge_library",
  "workflow",
  "assistant",
  "tool",
  "channel",
  "dashboard",
] as const

export interface ResourceGrantDialogProps {
  serviceAccountId: number
  existingGrants: ServiceAccountResourceGrant[]
  editingGrant: ServiceAccountResourceGrant | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onGranted: () => Promise<void>
}

export function ResourceGrantDialog({
  serviceAccountId,
  existingGrants,
  editingGrant,
  open,
  onOpenChange,
  onGranted,
}: ResourceGrantDialogProps) {
  const { t } = useTranslation()
  const [resourceType, setResourceType] = useState<string>(RESOURCE_TYPES[0])
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
      void captureAndAlertRequestErrorHoc(
        listServiceAccountGrantableResourcesApi(serviceAccountId, {
          resource_type: resourceType,
          keyword: keyword.trim() || undefined,
        }),
      )
        .then((rows) => {
          if (active && rows) setResources(rows)
        })
        .finally(() => {
          if (active) setLoadingResources(false)
        })
    }, 250)
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [editingGrant, keyword, open, resourceType, serviceAccountId])

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
    void captureAndAlertRequestErrorHoc(
      getGrantablePermissionModelsApi(
        editingGrant.resource_type as never,
        editingGrant.resource_id,
      ),
    )
      .then((available) => {
        if (available) setModels(available)
      })
      .finally(() => setLoadingModels(false))
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
        const available = await captureAndAlertRequestErrorHoc(
          getGrantablePermissionModelsApi(
            resource.resource_type as never,
            resource.resource_id,
          ),
        )
        if (available) setModels(available)
      } finally {
        setLoadingModels(false)
      }
    }
  }

  const handleGrant = async () => {
    if (!selectedResources.length || !modelKey) return
    setLoading(true)
    try {
      let completed = true
      let completedCount = 0
      for (const selected of selectedResources) {
        const context = await captureAndAlertRequestErrorHoc(
          getResourcePermissionContextApi(
            selected.resource_type as never,
            selected.resource_id,
          ),
        )
        if (!context) {
          completed = false
          break
        }
        const result = await captureAndAlertRequestErrorHoc(
          mutateServiceAccountResourceGrantsApi(
            serviceAccountId,
            selected.resource_type,
            selected.resource_id,
            {
              idempotency_key: crypto.randomUUID(),
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
            },
          ),
        )
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
      toast({
        title: t(
          editingGrant
            ? "openApiManagement.grants.change"
            : "openApiManagement.grants.add",
        ),
        description: t(
          editingGrant
            ? "openApiManagement.feedback.grantUpdated"
            : "openApiManagement.feedback.grantAdded",
        ),
        variant: "success",
      })
      onOpenChange(false)
      setSelectedResources([])
      setModelKey("")
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
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {t(
              editingGrant
                ? "openApiManagement.grants.change"
                : "openApiManagement.grants.add",
            )}
          </DialogTitle>
          <DialogDescription>
            {t("openApiManagement.grants.addHint")}
          </DialogDescription>
        </DialogHeader>
        {!editingGrant ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <Select
              value={resourceType}
              onValueChange={(value) => {
                setResourceType(value)
                setSelectedResources([])
                setModels([])
                setModelKey("")
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {RESOURCE_TYPES.map((type) => (
                  <SelectItem key={type} value={type}>
                    {t(`openApiManagement.resourceTypes.${type}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <SearchInput
              value={keyword}
              placeholder={t("openApiManagement.grants.search")}
              onChange={(event) => setKeyword(event.target.value)}
            />
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
                <Loader2 aria-hidden="true" className="size-4 animate-spin" />
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
            value={modelKey}
            disabled={!selectedResources.length || loadingModels}
            onValueChange={setModelKey}
          >
            <SelectTrigger>
              <SelectValue
                placeholder={t("openApiManagement.grants.modelPlaceholder")}
              />
            </SelectTrigger>
            <SelectContent>
              {models.map((model) => (
                <SelectItem key={model.key} value={model.key}>
                  {model.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
        <DialogFooter>
          <Button
            variant="outline"
            disabled={loading}
            onClick={() => onOpenChange(false)}
          >
            {t("cancel")}
          </Button>
          <Button
            disabled={
              loading ||
              !selectedResources.length ||
              !modelKey ||
              modelKey === editingGrant?.model_key
            }
            onClick={handleGrant}
          >
            {loading ? (
              <Loader2
                aria-hidden="true"
                className="mr-2 size-4 animate-spin"
              />
            ) : null}
            {t("confirmButton")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
