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
import type { ApiKeyIssued } from "@/types/api/openApi"
import { copyText } from "@/utils"
import { ChevronRight, Copy } from "lucide-react"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"

export interface KeyRevealDialogProps {
  issuedKey: ApiKeyIssued | null
  onClose: () => void
}

const USER_ID_PLACEHOLDER = "<USER_ID>"

// A delegated key is rejected unless the request names the user it acts for,
// so the self-check command has to carry that header too.
function buildVerifyCommand(issuedKey: ApiKeyIssued): string {
  const lines = [
    `curl "${location.origin}/api/v2/auth/whoami"`,
    `  -H "Authorization: Bearer ${issuedKey.plaintext}"`,
  ]
  if (issuedKey.scopes.includes("delegate")) {
    const firstUser = issuedKey.delegate_scopes.find(
      (scope) => scope.subject_type === "user",
    )
    lines.push(
      `  -H "X-On-Behalf-Of: ${firstUser ? firstUser.subject_id : USER_ID_PLACEHOLDER}"`,
    )
  }
  return lines.join(" \\\n")
}

export function KeyRevealDialog({ issuedKey, onClose }: KeyRevealDialogProps) {
  const { t } = useTranslation()
  const [saved, setSaved] = useState(false)
  const [verifyOpen, setVerifyOpen] = useState(false)

  useEffect(() => {
    if (issuedKey) {
      setSaved(false)
      setVerifyOpen(false)
    }
  }, [issuedKey])

  const plaintext = issuedKey?.plaintext || ""
  const delegated = !!issuedKey?.scopes.includes("delegate")
  const verifyCommand = issuedKey ? buildVerifyCommand(issuedKey) : ""

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
      open={!!issuedKey}
      onOpenChange={(nextOpen) => !nextOpen && handleClose()}
    >
      <DialogContent className="sm:max-w-[600px] [&>button]:hidden">
        <DialogHeader>
          <DialogTitle>{t("openApiManagement.keys.revealTitle")}</DialogTitle>
        </DialogHeader>
        <div className="min-w-0 space-y-4 py-2">
          <p className="text-sm text-destructive">
            {t("openApiManagement.keys.once")}
          </p>
          <div className="flex items-center gap-2 rounded-md border bg-muted/40 p-3">
            <code className="min-w-0 flex-1 break-all font-mono text-sm">
              {plaintext}
            </code>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => handleCopy(plaintext)}
            >
              <Copy aria-hidden="true" className="mr-1 size-3.5" />
              {t("openApiManagement.actions.copy")}
            </Button>
          </div>
          <div>
            <button
              type="button"
              aria-expanded={verifyOpen}
              className="flex items-center gap-1 rounded-sm text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => setVerifyOpen((current) => !current)}
            >
              <ChevronRight
                aria-hidden="true"
                className={`size-4 transition-transform ${verifyOpen ? "rotate-90" : ""}`}
              />
              {t("openApiManagement.keys.verifyTitle")}
            </button>
            {verifyOpen ? (
              <div className="mt-2 space-y-2 pl-5">
                <p className="text-xs text-muted-foreground">
                  {t("openApiManagement.keys.verifyHint")}
                </p>
                {delegated ? (
                  <p className="text-xs text-muted-foreground">
                    {t("openApiManagement.keys.verifyDelegateHint")}
                  </p>
                ) : null}
                <div className="relative rounded-md border bg-muted/40">
                  <pre className="whitespace-pre-wrap break-all p-3 pr-12 font-mono text-xs leading-5">
                    {verifyCommand}
                  </pre>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="absolute right-1.5 top-1.5 size-7"
                    aria-label={t("openApiManagement.actions.copy")}
                    onClick={() => handleCopy(verifyCommand)}
                  >
                    <Copy aria-hidden="true" className="size-3.5" />
                  </Button>
                </div>
              </div>
            ) : null}
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
