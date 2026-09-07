import { Button } from "@/components/bs-ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"
import { Input } from "@/components/bs-ui/input"
import { createServiceAccountApi } from "@/controllers/API/serviceAccount"
import { useState } from "react"
import { useTranslation } from "react-i18next"

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
  const [ownerId, setOwnerId] = useState("")
  const [loading, setLoading] = useState(false)

  const handleCreate = async () => {
    setLoading(true)
    try {
      const account = await createServiceAccountApi({
        name: name.trim(),
        description: description.trim() || null,
        resource_owner_user_id: Number(ownerId),
      })
      setName("")
      setDescription("")
      setOwnerId("")
      onOpenChange(false)
      onCreated(account.id)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
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
            <Input
              value={description}
              maxLength={512}
              onChange={(event) => setDescription(event.target.value)}
            />
          </label>
          <label className="block space-y-1 text-sm">
            <span>{t("openApiManagement.fields.ownerUserId")}</span>
            <Input type="number" min={1} value={ownerId} onChange={(event) => setOwnerId(event.target.value)} />
          </label>
        </div>
        <DialogFooter>
          <Button variant="outline" disabled={loading} onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button disabled={loading || !name.trim() || Number(ownerId) < 1} onClick={handleCreate}>
            {t("confirmButton")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
