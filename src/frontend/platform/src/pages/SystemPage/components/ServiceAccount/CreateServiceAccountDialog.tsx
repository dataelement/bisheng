import { Button, Input, Textarea, notification } from '@bisheng/ui';
import DepartmentUsersSelect,{
type DepartmentUserOption,
} from "@/components/bs-comp/selectComponent/DepartmentUsersSelect";

import {
Dialog,
DialogContent,
DialogDescription,
DialogFooter,
DialogHeader,
DialogTitle,
} from "@/components/bs-ui/dialog";

import { Label } from "@/components/bs-ui/label";

import { createServiceAccountApi } from "@/controllers/API/serviceAccount";
import { showApiError } from "@/controllers/request";
import { Outlined } from "bisheng-icons";
import { useContext, useState } from "react";
import { useTranslation } from "react-i18next";

import { locationContext } from "@/contexts/locationContext";

export interface CreateServiceAccountDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: (id: number) => void
}

export function CreateServiceAccountDialog({
  open,
  onOpenChange,
  onCreated,
}: CreateServiceAccountDialogProps) {
  const { t } = useTranslation()
  const { appConfig } = useContext(locationContext)
  // Single-tenant deployments have no "current tenant" to scope the owner
  // picker to; the hint keeps its substance (pick an active user) and drops
  // the tenant qualifier.
  const createHintKey = appConfig?.multiTenantEnabled
    ? "openApiManagement.serviceAccount.createHint"
    : "openApiManagement.serviceAccount.createHintSingle"
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [owners, setOwners] = useState<DepartmentUserOption[]>([])
  const [loading, setLoading] = useState(false)

  const handleCreate = async () => {
        if ((String((name) ?? '').length > 128) || (String((description) ?? '').length > 512)) return;

    setLoading(true)
    try {
      const account = await createServiceAccountApi({
          name: name.trim(),
          description: description.trim() || null,
          resource_owner_user_id: owners[0].value,
        })
      if (!account) return
      setName("")
      setDescription("")
      setOwners([])
      onOpenChange(false)
      notification.open({ type: "success", title: String(t("openApiManagement.serviceAccount.create") ?? ''), description: String(t("openApiManagement.feedback.created") ?? '') })
      onCreated(account.id)
    } catch (error) {
      showApiError(error)
    } finally {
      setLoading(false)
    }
  }

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen && loading) return
    if (!nextOpen) {
      setName("")
      setDescription("")
      setOwners([])
    }
    onOpenChange(nextOpen)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>
            {t("openApiManagement.serviceAccount.create")}
          </DialogTitle>
          <DialogDescription>{t(createHintKey)}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label>{t("openApiManagement.fields.name")} *</Label>
            <Input value={name} maxLength={128} placeholder={t(
                "openApiManagement.serviceAccount.namePlaceholder",
              )} onChange={(event) => setName(event.target.value)} showCount />
          </div>
          <div className="space-y-2">
            <Label>{t("openApiManagement.fields.description")}</Label>
            <Textarea value={description} maxLength={512} rows={3} placeholder={t(
                "openApiManagement.serviceAccount.descriptionPlaceholder",
              )} onChange={(event) => setDescription(event.target.value)} showCount />
          </div>
          <div className="space-y-2">
            <Label>{t("openApiManagement.fields.owner")} *</Label>
            <DepartmentUsersSelect
              value={owners}
              onChange={setOwners}
              multiple={false}
              placeholder={t(
                "openApiManagement.serviceAccount.ownerPlaceholder",
              )}
              searchPlaceholder={t(
                "openApiManagement.serviceAccount.ownerSearch",
              )}
            />
            <p className="text-sm text-muted-foreground">
              {t("openApiManagement.serviceAccount.ownerTip")}
            </p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outlined" disabled={loading} onClick={() => handleOpenChange(false)} color="default">
            {t("cancel")}
          </Button>
          <Button disabled={((String((name) ?? '').length > 128) || (String((description) ?? '').length > 512)) || (loading || !name.trim() || owners.length !== 1)} onClick={handleCreate}>
            {loading ? (
              <Outlined.Loading
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
