import { Button } from "@/components/bs-ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"
import type { ServiceAccountResourceGrant } from "@/types/api/openApi"
import { useTranslation } from "react-i18next"
import { isServiceAccountPermissionTier } from "./resourceGrantUtils"

export interface ResourceGrantRevokeDialogsProps {
  grant: ServiceAccountResourceGrant | null
  directGrants: ServiceAccountResourceGrant[]
  automaticGrantCount: number
  revokeAllOpen: boolean
  loading: boolean
  onGrantOpenChange: (open: boolean) => void
  onRevokeAllOpenChange: (open: boolean) => void
  onConfirmGrant: () => void
  onConfirmAll: () => void
}

export function ResourceGrantRevokeDialogs({
  grant,
  directGrants,
  automaticGrantCount,
  revokeAllOpen,
  loading,
  onGrantOpenChange,
  onRevokeAllOpenChange,
  onConfirmGrant,
  onConfirmAll,
}: ResourceGrantRevokeDialogsProps) {
  const { t } = useTranslation()
  const renderPermissionTier = (item: ServiceAccountResourceGrant) =>
    isServiceAccountPermissionTier(item.model_key)
      ? t(`openApiManagement.permissionTiers.${item.model_key}`)
      : item.model_name

  return (
    <>
      <Dialog
        open={!!grant}
        onOpenChange={(open) => {
          if (!loading) onGrantOpenChange(open)
        }}
      >
        <DialogContent className="max-w-3xl">
          {grant ? (
            <>
              <DialogHeader>
                <DialogTitle>
                  {t(
                    grant.source_type === "CREATOR_GRANT"
                      ? "openApiManagement.grants.creatorRevokeTitle"
                      : "openApiManagement.grants.revokeTitle",
                  )}
                </DialogTitle>
                <DialogDescription
                  className={
                    grant.source_type === "CREATOR_GRANT"
                      ? "whitespace-pre-line rounded-md border border-destructive bg-destructive/10 p-3 text-foreground"
                      : "text-muted-foreground"
                  }
                >
                  {t(
                    grant.source_type === "CREATOR_GRANT"
                      ? "openApiManagement.grants.creatorRevokeConfirm"
                      : "openApiManagement.grants.revokeConfirm",
                    { name: grant.resource_name },
                  )}
                </DialogDescription>
              </DialogHeader>
              <dl className="divide-y text-sm">
                <div className="flex justify-between gap-4 py-2">
                  <dt>{t("openApiManagement.grants.resource")}</dt>
                  <dd className="text-right font-medium">
                    {grant.resource_name}
                  </dd>
                </div>
                <div className="flex justify-between gap-4 py-2">
                  <dt>{t("openApiManagement.grants.model")}</dt>
                  <dd className="text-right font-medium">
                    {renderPermissionTier(grant)}
                  </dd>
                </div>
                <div className="flex justify-between gap-4 py-2">
                  <dt>{t("openApiManagement.grants.source")}</dt>
                  <dd className="text-right font-medium">
                    {t(
                      grant.source_type === "CREATOR_GRANT"
                        ? "openApiManagement.grantSources.CREATOR_GRANT"
                        : "openApiManagement.grants.directSourceDetail",
                    )}
                  </dd>
                </div>
              </dl>
              <DialogFooter>
                <Button
                  variant="outline"
                  disabled={loading}
                  onClick={() => onGrantOpenChange(false)}
                >
                  {t("cancel")}
                </Button>
                <Button
                  variant="destructive"
                  disabled={loading}
                  onClick={onConfirmGrant}
                >
                  {t(
                    grant.source_type === "CREATOR_GRANT"
                      ? "openApiManagement.grants.revokeAnyway"
                      : "openApiManagement.actions.revoke",
                  )}
                </Button>
              </DialogFooter>
            </>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog
        open={revokeAllOpen}
        onOpenChange={(open) => {
          if (!loading) onRevokeAllOpenChange(open)
        }}
      >
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>
              {t("openApiManagement.grants.revokeAllTitle")}
            </DialogTitle>
            <DialogDescription>
              {t("openApiManagement.grants.revokeAllConfirm")}
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-56 divide-y overflow-y-auto text-sm">
            {directGrants.map((item) => (
              <div
                key={item.assignee_id}
                className="flex justify-between gap-4 py-2"
              >
                <span className="font-medium">{item.resource_name}</span>
                <span className="text-right text-muted-foreground">
                  {t(`openApiManagement.resourceTypes.${item.resource_type}`)}·{" "}
                  {renderPermissionTier(item)}
                </span>
              </div>
            ))}
          </div>
          {automaticGrantCount ? (
            <div className="rounded-md border border-success-foreground/40 bg-success-background p-3 text-sm">
              <p className="font-medium">
                {t("openApiManagement.grants.revokeAllRetainedTitle", {
                  count: automaticGrantCount,
                })}
              </p>
              <p className="mt-1">
                {t("openApiManagement.grants.revokeAllRetainedHint")}
              </p>
            </div>
          ) : null}
          <DialogFooter>
            <Button
              variant="outline"
              disabled={loading}
              onClick={() => onRevokeAllOpenChange(false)}
            >
              {t("cancel")}
            </Button>
            <Button
              variant="destructive"
              disabled={loading}
              onClick={onConfirmAll}
            >
              {t("openApiManagement.grants.revokeCount", {
                count: directGrants.length,
              })}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
