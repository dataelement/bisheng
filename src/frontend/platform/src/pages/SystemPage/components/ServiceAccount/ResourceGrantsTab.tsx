import {
  LoadIcon,
  PlusIcon,
  ThunmbIcon,
  TipIcon,
  TrashIcon,
} from "@/components/bs-icons"
import { Button } from "@/components/bs-ui/button"
import { SearchInput } from "@/components/bs-ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table"
import {
  Portal,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/bs-ui/tooltip"
import { message, toast } from "@/components/bs-ui/toast/use-toast"
import {
  listServiceAccountKeysApi,
  listServiceAccountResourceGrantsApi,
  mutateServiceAccountResourceGrantsApi,
} from "@/controllers/API/serviceAccount"
import { getResourcePermissionContextApi } from "@/controllers/API/permission"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import type {
  ApiKeyItem,
  ServiceAccountResourceGrant,
} from "@/types/api/openApi"
import { copyText } from "@/utils"
import { useCallback, useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { ResourceGrantDialog } from "./ResourceGrantDialog"
import { ResourceGrantRevokeDialogs } from "./ResourceGrantRevokeDialogs"
import {
  getRequiredScope,
  formatServiceAccountGrantTime,
  isServiceAccountGrantEffective,
  isServiceAccountPermissionTier,
  RESOURCE_GRANT_FILTER_ALL,
  SERVICE_ACCOUNT_PERMISSION_TIERS,
  SERVICE_ACCOUNT_RESOURCE_TYPES,
} from "./resourceGrantUtils"

export interface ResourceGrantsTabProps {
  serviceAccountId: number
  serviceAccountName: string
}

export function ResourceGrantsTab({
  serviceAccountId,
  serviceAccountName,
}: ResourceGrantsTabProps) {
  const { t } = useTranslation()
  const [grants, setGrants] = useState<ServiceAccountResourceGrant[]>([])
  const [keys, setKeys] = useState<ApiKeyItem[]>([])
  const [keyword, setKeyword] = useState("")
  const [resourceType, setResourceType] = useState(RESOURCE_GRANT_FILTER_ALL)
  const [sourceType, setSourceType] = useState(RESOURCE_GRANT_FILTER_ALL)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [revokeGrant, setRevokeGrant] =
    useState<ServiceAccountResourceGrant | null>(null)
  const [revokeAllOpen, setRevokeAllOpen] = useState(false)
  const [updatingGrantId, setUpdatingGrantId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadingData, setLoadingData] = useState(true)

  const load = useCallback(async () => {
    setLoadingData(true)
    try {
      const [grantRows, keyRows] = await Promise.all([
        captureAndAlertRequestErrorHoc(
          listServiceAccountResourceGrantsApi(serviceAccountId),
        ),
        captureAndAlertRequestErrorHoc(
          listServiceAccountKeysApi(serviceAccountId),
        ),
      ])
      if (grantRows) setGrants(grantRows)
      if (keyRows) setKeys(keyRows)
    } finally {
      setLoadingData(false)
    }
  }, [serviceAccountId])

  useEffect(() => {
    void load()
  }, [load])

  const filteredGrants = useMemo(() => {
    const normalizedKeyword = keyword.trim().toLocaleLowerCase()
    return grants.filter(
      (grant) =>
        (!normalizedKeyword ||
          grant.resource_name
            .toLocaleLowerCase()
            .includes(normalizedKeyword)) &&
        (resourceType === RESOURCE_GRANT_FILTER_ALL ||
          grant.resource_type === resourceType) &&
        (sourceType === RESOURCE_GRANT_FILTER_ALL ||
          grant.source_type === sourceType),
    )
  }, [grants, keyword, resourceType, sourceType])

  const directGrants = grants.filter(
    (grant) =>
      grant.editable && !grant.protected && grant.source_type === "DIRECT",
  )
  const automaticGrants = grants.filter(
    (grant) => grant.source_type === "CREATOR_GRANT",
  )

  const remove = async (rows: ServiceAccountResourceGrant[]) => {
    setLoading(true)
    let completed = true
    try {
      const groups = rows.reduce<Record<string, ServiceAccountResourceGrant[]>>(
        (result, row) => {
          const key = `${row.resource_type}:${row.resource_id}`
          result[key] = [...(result[key] || []), row]
          return result
        },
        {},
      )
      for (const group of Object.values(groups)) {
        if (!group?.length) continue
        const resource = group[0]
        const context = await captureAndAlertRequestErrorHoc(
          getResourcePermissionContextApi(
            resource.resource_type as never,
            resource.resource_id,
          ),
        )
        if (!context) {
          completed = false
          break
        }
        const result = await captureAndAlertRequestErrorHoc(
          mutateServiceAccountResourceGrantsApi(
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
          ),
        )
        if (!result) {
          completed = false
          break
        }
      }
      if (completed) {
        toast({
          title: t("openApiManagement.serviceAccount.grants"),
          description: t("openApiManagement.feedback.grantRevoked"),
          variant: "success",
        })
      }
      await load()
      return completed
    } finally {
      setLoading(false)
    }
  }

  const handleTierChange = async (
    grant: ServiceAccountResourceGrant,
    targetModelKey: string,
  ) => {
    if (targetModelKey === grant.model_key) return
    setUpdatingGrantId(grant.assignee_id)
    try {
      const context = await captureAndAlertRequestErrorHoc(
        getResourcePermissionContextApi(
          grant.resource_type as never,
          grant.resource_id,
        ),
      )
      if (!context) return
      const result = await captureAndAlertRequestErrorHoc(
        mutateServiceAccountResourceGrantsApi(
          serviceAccountId,
          grant.resource_type,
          grant.resource_id,
          {
            idempotency_key: crypto.randomUUID(),
            expected_resource_version: context.resource_version,
            expected_catalog_release_id: context.catalog_release_id,
            changes: [
              {
                op: "MOVE",
                assignee_id: grant.assignee_id,
                expected_assignee_version: grant.assignee_version,
                target_model_key: targetModelKey,
              },
            ],
          },
        ),
      )
      if (!result) return
      toast({
        title: t("openApiManagement.grants.change"),
        description: t("openApiManagement.feedback.grantUpdated"),
        variant: "success",
      })
      await load()
    } finally {
      setUpdatingGrantId(null)
    }
  }

  const handleCopyResource = async (grant: ServiceAccountResourceGrant) => {
    const resource = `${grant.resource_type}:${grant.resource_id}`
    await copyText(resource)
    message({
      className: "fixed bottom-6 left-1/2 mt-0 w-auto -translate-x-1/2 pr-4",
      description: t("openApiManagement.feedback.resourceCopied", {
        resource,
      }),
      variant: "success",
    })
  }

  const handleConfirmRevoke = async () => {
    if (!revokeGrant) return
    if (await remove([revokeGrant])) setRevokeGrant(null)
  }

  const handleConfirmRevokeAll = async () => {
    if (await remove(directGrants)) setRevokeAllOpen(false)
  }

  return (
    <TooltipProvider delayDuration={100}>
      <div className="space-y-4 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h3 className="text-base font-medium">
              {t("openApiManagement.grants.accessTitle")}
            </h3>
            <p className="text-sm text-muted-foreground">
              {t("openApiManagement.grants.accessHint")}
            </p>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <SearchInput
              className="w-52"
              value={keyword}
              aria-label={t("openApiManagement.grants.resourceSearch")}
              placeholder={t("openApiManagement.grants.resourceSearch")}
              onChange={(event) => setKeyword(event.target.value)}
            />
            <Select value={resourceType} onValueChange={setResourceType}>
              <SelectTrigger
                className="w-36"
                aria-label={t("openApiManagement.grants.typeFilter")}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={RESOURCE_GRANT_FILTER_ALL}>
                  {t("openApiManagement.grants.allTypes")}
                </SelectItem>
                {SERVICE_ACCOUNT_RESOURCE_TYPES.map((type) => (
                  <SelectItem key={type} value={type}>
                    {t(`openApiManagement.resourceTypes.${type}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={sourceType} onValueChange={setSourceType}>
              <SelectTrigger
                className="w-44"
                aria-label={t("openApiManagement.grants.sourceFilter")}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={RESOURCE_GRANT_FILTER_ALL}>
                  {t("openApiManagement.grants.allSources")}
                </SelectItem>
                <SelectItem value="DIRECT">
                  {t("openApiManagement.grantSources.DIRECT")}
                </SelectItem>
                <SelectItem value="CREATOR_GRANT">
                  {t("openApiManagement.grantSources.CREATOR_GRANT")}
                </SelectItem>
              </SelectContent>
            </Select>
            <Button
              variant="outline"
              disabled={loading || loadingData || !directGrants.length}
              onClick={() => setRevokeAllOpen(true)}
            >
              {t("openApiManagement.grants.revokeAll")}
            </Button>
            <Button
              disabled={loading || loadingData}
              onClick={() => setDialogOpen(true)}
            >
              <PlusIcon className="mr-1 size-4 text-primary" />
              {t("openApiManagement.grants.add")}
            </Button>
          </div>
        </div>

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("openApiManagement.grants.resource")}</TableHead>
              <TableHead>
                {t("openApiManagement.grants.resourceType")}
              </TableHead>
              <TableHead>{t("openApiManagement.grants.model")}</TableHead>
              <TableHead>{t("openApiManagement.grants.source")}</TableHead>
              <TableHead>{t("openApiManagement.grants.effective")}</TableHead>
              <TableHead>{t("openApiManagement.grants.grantedAt")}</TableHead>
              <TableHead>
                <span className="sr-only">{t("operations")}</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredGrants.map((grant) => {
              const effective = isServiceAccountGrantEffective(grant, keys)
              const requiredScope = getRequiredScope(grant)
              const canChangeTier =
                grant.editable &&
                !grant.protected &&
                grant.source_type === "DIRECT" &&
                isServiceAccountPermissionTier(grant.model_key)
              return (
                <TableRow key={grant.assignee_id}>
                  <TableCell>
                    <div className="min-w-52">
                      <div className="flex items-center gap-1">
                        <span className="font-medium">
                          {grant.resource_name}
                        </span>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="size-7"
                              aria-label={t(
                                "openApiManagement.grants.copyResource",
                                { name: grant.resource_name },
                              )}
                              onClick={() => void handleCopyResource(grant)}
                            >
                              <ThunmbIcon type="copy" className="size-4" />
                            </Button>
                          </TooltipTrigger>
                          <Portal>
                            <TooltipContent>
                              {t("openApiManagement.actions.copy")}
                            </TooltipContent>
                          </Portal>
                        </Tooltip>
                      </div>
                      {!effective && requiredScope ? (
                        <p className="mt-1 flex items-center gap-1 text-xs text-orange-500">
                          <TipIcon className="size-3.5 shrink-0" />
                          {t("openApiManagement.grants.missingScope", {
                            scope: t(
                              `openApiManagement.grants.scopeCodes.${requiredScope.replace(":", "_")}`,
                            ),
                          })}
                        </p>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell>
                    {t(
                      `openApiManagement.resourceTypes.${grant.resource_type}`,
                    )}
                  </TableCell>
                  <TableCell>
                    {isServiceAccountPermissionTier(grant.model_key) ? (
                      <Select
                        value={grant.model_key}
                        disabled={
                          !canChangeTier ||
                          loading ||
                          updatingGrantId === grant.assignee_id
                        }
                        onValueChange={(value) =>
                          void handleTierChange(grant, value)
                        }
                      >
                        <SelectTrigger
                          className="h-8 w-28 shadow-none"
                          aria-label={t(
                            "openApiManagement.grants.changeTierFor",
                            { name: grant.resource_name },
                          )}
                        >
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {SERVICE_ACCOUNT_PERMISSION_TIERS.map((key) => (
                            <SelectItem key={key} value={key}>
                              {t(`openApiManagement.permissionTiers.${key}`)}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      grant.model_name
                    )}
                  </TableCell>
                  <TableCell>
                    <span
                      className={
                        grant.source_type === "CREATOR_GRANT"
                          ? "inline-flex h-5 items-center rounded bg-primary/10 px-1.5 text-xs text-primary"
                          : "inline-flex h-5 items-center rounded bg-muted px-1.5 text-xs text-muted-foreground"
                      }
                    >
                      {t(`openApiManagement.grantSources.${grant.source_type}`)}
                    </span>
                  </TableCell>
                  <TableCell>
                    <span
                      className={
                        effective
                          ? "inline-flex items-center gap-2 text-success-foreground"
                          : "inline-flex items-center gap-2 text-orange-500"
                      }
                    >
                      <span
                        aria-hidden="true"
                        className={`size-2 rounded-full ${effective ? "bg-success-foreground" : "bg-orange-500"}`}
                      />
                      {t(
                        effective
                          ? "openApiManagement.grants.effectiveActive"
                          : "openApiManagement.grants.ineffective",
                      )}
                    </span>
                  </TableCell>
                  <TableCell>
                    {formatServiceAccountGrantTime(grant.granted_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="size-8"
                          disabled={
                            loading || !grant.editable || grant.protected
                          }
                          aria-label={t(
                            "openApiManagement.grants.revokeResource",
                            { name: grant.resource_name },
                          )}
                          onClick={() => setRevokeGrant(grant)}
                        >
                          <TrashIcon className="size-4" />
                        </Button>
                      </TooltipTrigger>
                      <Portal>
                        <TooltipContent>
                          {t("openApiManagement.actions.revoke")}
                        </TooltipContent>
                      </Portal>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              )
            })}
            {loadingData ? (
              <TableRow>
                <TableCell colSpan={7} className="py-8 text-center">
                  <span role="status" aria-label={t("loading")}>
                    <LoadIcon className="mx-auto size-5" />
                  </span>
                </TableCell>
              </TableRow>
            ) : null}
            {!loadingData && !filteredGrants.length ? (
              <TableRow>
                <TableCell
                  colSpan={7}
                  className="text-center text-muted-foreground"
                >
                  {t("openApiManagement.grants.empty")}
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>

        {!loadingData ? (
          <p className="text-sm text-muted-foreground">
            {t("openApiManagement.grants.total", {
              count: filteredGrants.length,
            })}
          </p>
        ) : null}

        <ResourceGrantDialog
          serviceAccountId={serviceAccountId}
          serviceAccountName={serviceAccountName}
          existingGrants={grants}
          editingGrant={null}
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          onGranted={load}
        />
        <ResourceGrantRevokeDialogs
          grant={revokeGrant}
          directGrants={directGrants}
          automaticGrantCount={automaticGrants.length}
          revokeAllOpen={revokeAllOpen}
          loading={loading}
          onGrantOpenChange={(open) => {
            if (!open) setRevokeGrant(null)
          }}
          onRevokeAllOpenChange={setRevokeAllOpen}
          onConfirmGrant={() => void handleConfirmRevoke()}
          onConfirmAll={() => void handleConfirmRevokeAll()}
        />
      </div>
    </TooltipProvider>
  )
}
