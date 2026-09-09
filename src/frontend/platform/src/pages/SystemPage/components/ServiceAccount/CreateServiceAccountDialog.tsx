import { Button } from "@/components/bs-ui/button"
import DepartmentUsersSelect, {
  type DepartmentUserOption,
} from "@/components/bs-comp/selectComponent/DepartmentUsersSelect"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"
import { Input, Textarea } from "@/components/bs-ui/input"
import { message } from "@/components/bs-ui/toast/use-toast"
import { createServiceAccountApi } from "@/controllers/API/serviceAccount"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { useState } from "react"
import { useTranslation } from "react-i18next"
import { Loader2 } from "lucide-react"

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
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [owners, setOwners] = useState<DepartmentUserOption[]>([])
  const [loading, setLoading] = useState(false)

  const handleCreate = async () => {
    setLoading(true)
    try {
      const account = await captureAndAlertRequestErrorHoc(createServiceAccountApi({
        name: name.trim(),
        description: description.trim() || null,
        resource_owner_user_id: owners[0].value,
      }))
      if (!account) return
      setName("")
      setDescription("")
      setOwners([])
      onOpenChange(false)
      message({ description: t("openApiManagement.feedback.created") })
      onCreated(account.id)
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
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("openApiManagement.serviceAccount.create")}</DialogTitle>
          <DialogDescription>{t("openApiManagement.serviceAccount.createHint")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <label className="block space-y-1 text-sm">
            <span>{t("openApiManagement.fields.name")}</span>
            <Input value={name} maxLength={128} onChange={(event) => setName(event.target.value)} />
          </label>
          <label className="block space-y-1 text-sm">
            <span>{t("openApiManagement.fields.description")}</span>
            <Textarea
              value={description}
              maxLength={512}
              rows={3}
              onChange={(event) => setDescription(event.target.value)}
            />
          </label>
          <label className="block space-y-1 text-sm">
            <span>{t("openApiManagement.fields.owner")}</span>
            <DepartmentUsersSelect
              value={owners}
              onChange={setOwners}
              multiple={false}
              placeholder={t("openApiManagement.serviceAccount.ownerPlaceholder")}
              searchPlaceholder={t("openApiManagement.serviceAccount.ownerSearch")}
            />
          </label>
        </div>
        <DialogFooter>
          <Button variant="outline" disabled={loading} onClick={() => handleOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button disabled={loading || !name.trim() || owners.length !== 1} onClick={handleCreate}>
            {loading ? <Loader2 aria-hidden="true" className="mr-2 size-4 animate-spin" /> : null}
            {t("confirmButton")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
