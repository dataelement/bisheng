import { Button } from "@/components/bs-ui/button"
import { Checkbox } from "@/components/bs-ui/checkBox"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"
import { toast } from "@/components/bs-ui/toast/use-toast"
import { copyText } from "@/utils"
import { Copy } from "lucide-react"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"

export interface KeyRevealDialogProps {
  plaintext: string | null
  onClose: () => void
}

export function KeyRevealDialog({ plaintext, onClose }: KeyRevealDialogProps) {
  const { t } = useTranslation()
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (plaintext) setSaved(false)
  }, [plaintext])

  const keyExample = plaintext
    ? `curl -H "Authorization: Bearer ${plaintext}" "${location.origin}/api/v2/auth/whoami"`
    : ""

  const handleCopy = (value: string) => {
    copyText(value)
    toast({
      title: t("openApiManagement.keys.revealTitle"),
      description: t("openApiManagement.feedback.copied"),
      variant: "success",
    })
  }

  const handleClose = () => {
    if (!saved) return
    onClose()
  }

  return (
    <Dialog
      open={!!plaintext}
      onOpenChange={(nextOpen) => !nextOpen && handleClose()}
    >
      <DialogContent className="sm:max-w-[600px] [&>button]:hidden">
        <DialogHeader>
          <DialogTitle>{t("openApiManagement.keys.revealTitle")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <p className="text-sm text-destructive">
            {t("openApiManagement.keys.once")}
          </p>
          <div className="flex items-center gap-2 rounded-md border bg-muted/40 p-3">
            <code className="min-w-0 flex-1 break-all text-sm">
              {plaintext}
            </code>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => handleCopy(plaintext || "")}
            >
              <Copy aria-hidden="true" className="mr-1 size-3.5" />
              {t("openApiManagement.actions.copy")}
            </Button>
          </div>
          <div className="flex items-center gap-2 rounded-md border bg-muted/40 p-3">
            <code className="min-w-0 flex-1 break-all text-sm">
              {keyExample}
            </code>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => handleCopy(keyExample)}
            >
              <Copy aria-hidden="true" className="mr-1 size-3.5" />
              {t("openApiManagement.actions.copy")}
            </Button>
          </div>
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <Checkbox
              checked={saved}
              onCheckedChange={(checked) => setSaved(checked === true)}
            />
            {t("openApiManagement.keys.saved")}
          </label>
        </div>
        <DialogFooter>
          <Button disabled={!saved} onClick={handleClose}>
            {t("confirmButton")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
