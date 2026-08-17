import { Checkbox } from "@/components/bs-ui/checkBox"
import { Button } from "@/components/bs-ui/button"
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
import { useState } from "react"
import { useTranslation } from "react-i18next"

interface KeyRevealDialogProps {
  /** The one and only copy of the plaintext; null keeps the dialog closed */
  plaintext: string | null
  onClose: () => void
}

/**
 * One-shot plaintext display (AC-02 / AC-45).
 *
 * The dialog cannot be dismissed — no close button, no escape, no overlay
 * click — until "I have saved it" is ticked, because after this the key exists
 * nowhere: the backend stores only its hash and every other surface shows the
 * mask.
 */
export function KeyRevealDialog({ plaintext, onClose }: KeyRevealDialogProps) {
  const { t } = useTranslation("serviceAccount")
  const [saved, setSaved] = useState(false)

  const handleClose = () => {
    if (!saved) return
    setSaved(false)
    onClose()
  }

  const handleCopy = () => {
    if (!plaintext) return
    copyText(plaintext)
    toast({ title: t("reveal.title"), description: t("reveal.copied"), variant: "success" })
  }

  return (
    <Dialog open={!!plaintext} onOpenChange={(next) => !next && handleClose()}>
      <DialogContent close={false} className="sm:max-w-[600px]">
        <DialogHeader>
          <DialogTitle>{t("reveal.title")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="flex items-center gap-2 rounded-md border bg-muted/40 p-3">
            <code className="flex-1 break-all text-sm">{plaintext}</code>
            <Button variant="outline" size="sm" onClick={handleCopy}>
              <Copy className="mr-1 size-3.5" />
              {t("reveal.copy")}
            </Button>
          </div>
          <p className="text-sm text-red-500">{t("reveal.onceOnlyTip")}</p>
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <Checkbox checked={saved} onCheckedChange={(v) => setSaved(v === true)} />
            {t("reveal.savedCheckbox")}
          </label>
        </div>
        <DialogFooter>
          <Button disabled={!saved} title={saved ? "" : t("reveal.closeBlockedTip")} onClick={handleClose}>
            {t("common.close")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
