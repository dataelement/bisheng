import DepartmentUsersSelect, {
  DepartmentUserOption,
} from "@/components/bs-comp/selectComponent/DepartmentUsersSelect"
import { Button } from "@/components/bs-ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"
import { Input, Textarea } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { toast } from "@/components/bs-ui/toast/use-toast"
import { locationContext } from "@/contexts/locationContext"
import { createServiceAccountApi } from "@/controllers/API/serviceAccount"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { useContext, useState } from "react"
import { useTranslation } from "react-i18next"

interface CreateServiceAccountDialogProps {
  open: boolean
  onClose: () => void
  /** Success hands the new id up so the panel can jump straight to key issuing (AC-43). */
  onCreated: (id: number) => void
}

/**
 * Create dialog: name + description + resource owner (AC-23).
 *
 * The tenant is never part of the payload — the backend takes it from the
 * acting admin's scope (the F019 ScopeBar for a super admin), so there is
 * nothing to choose and nothing to change afterwards.
 */
export function CreateServiceAccountDialog({
  open,
  onClose,
  onCreated,
}: CreateServiceAccountDialogProps) {
  const { t } = useTranslation("serviceAccount")
  const { appConfig } = useContext(locationContext)
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [owner, setOwner] = useState<DepartmentUserOption[]>([])
  const [loading, setLoading] = useState(false)

  // Single-tenant deployments have exactly one tenant, so naming it in the
  // picker hint only adds a concept the operator never sees anywhere else.
  const ownerPlaceholder = appConfig.multiTenantEnabled
    ? t("create.resourceOwnerPlaceholderTenant")
    : t("create.resourceOwnerPlaceholder")

  const handleClose = () => {
    if (loading) return
    setName("")
    setDescription("")
    setOwner([])
    onClose()
  }

  const handleSubmit = () => {
    const trimmed = name.trim()
    if (!trimmed) {
      toast({ title: t("create.title"), description: t("create.nameRequired"), variant: "error" })
      return
    }
    if (!owner.length) {
      toast({
        title: t("create.title"),
        description: t("create.resourceOwnerRequired"),
        variant: "error",
      })
      return
    }
    setLoading(true)
    captureAndAlertRequestErrorHoc(
      createServiceAccountApi({
        name: trimmed,
        description: description.trim() || null,
        resource_owner_user_id: Number(owner[0].value),
      })
    ).then((res) => {
      setLoading(false)
      if (!res) return
      toast({ title: t("create.title"), description: t("create.success"), variant: "success" })
      setName("")
      setDescription("")
      setOwner([])
      onCreated(res.id)
    })
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && handleClose()}>
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>{t("create.title")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label>{t("common.name")} *</Label>
            <Input
              value={name}
              maxLength={64}
              placeholder={t("create.namePlaceholder")}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label>{t("common.description")}</Label>
            <Textarea
              value={description}
              maxLength={512}
              rows={3}
              placeholder={t("create.descriptionPlaceholder")}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label>{t("create.resourceOwner")} *</Label>
            <DepartmentUsersSelect
              multiple={false}
              value={owner}
              onChange={setOwner}
              placeholder={ownerPlaceholder}
            />
            <p className="text-sm text-muted-foreground">{t("create.resourceOwnerTip")}</p>
            {/* Extra ownership consequences that only exist once apps can be deployed. */}
            {appConfig.openPlatformEnabled && (
              <p className="text-sm text-muted-foreground">
                {t("create.resourceOwnerOpenPlatformTip")}
              </p>
            )}
          </div>
          {/* The tenant a service account belongs to is only a decision worth
              explaining when more than one tenant exists. */}
          {appConfig.multiTenantEnabled && (
            <p className="text-sm text-muted-foreground">{t("create.tenantFixedTip")}</p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" disabled={loading} onClick={handleClose}>
            {t("common.cancel")}
          </Button>
          <Button disabled={loading} onClick={handleSubmit}>
            {t("create.submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
