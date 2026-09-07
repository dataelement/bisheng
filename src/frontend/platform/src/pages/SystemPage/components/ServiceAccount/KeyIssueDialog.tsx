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
import { Input } from "@/components/bs-ui/input"
import { issueServiceAccountKeyApi } from "@/controllers/API/serviceAccount"
import type { ApiKeyIssued, DelegateScopeInput, OpenApiScopeItem } from "@/types/api/openApi"
import { copyText } from "@/utils"
import { useState } from "react"
import { useTranslation } from "react-i18next"

export interface KeyIssueDialogProps {
  serviceAccountId: number
  scopes: OpenApiScopeItem[]
  open: boolean
  onOpenChange: (open: boolean) => void
  onIssued: () => void
}

function parseDelegateScopes(value: string): DelegateScopeInput[] | null {
  const items = value.split(",").map((item) => item.trim()).filter(Boolean)
  if (!items.length) return []
  const result: DelegateScopeInput[] = []
  for (const item of items) {
    const match = /^(user|department):([1-9]\d*)$/.exec(item)
    if (!match) return null
    result.push({
      subject_type: match[1] === "user" ? "user" : "department",
      subject_id: Number(match[2]),
    })
  }
  return result
}

export function KeyIssueDialog({
  serviceAccountId,
  scopes,
  open,
  onOpenChange,
  onIssued,
}: KeyIssueDialogProps) {
  const { t } = useTranslation()
  const [name, setName] = useState("")
  const [selectedScopes, setSelectedScopes] = useState<string[]>([])
  const [delegateScopeText, setDelegateScopeText] = useState("")
  const [issued, setIssued] = useState<ApiKeyIssued | null>(null)
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(false)
  const parsedDelegateScopes = parseDelegateScopes(delegateScopeText)
  const delegateInvalid = selectedScopes.includes("delegate")
    && (!parsedDelegateScopes || !parsedDelegateScopes.length)

  const toggleScope = (code: string, checked: boolean) => {
    setSelectedScopes((current) => checked ? [...current, code] : current.filter((item) => item !== code))
    if (code === "delegate" && !checked) setDelegateScopeText("")
  }

  const handleIssue = async () => {
    let delegateScopes: DelegateScopeInput[] = []
    if (selectedScopes.includes("delegate")) {
      if (!parsedDelegateScopes?.length) return
      delegateScopes = parsedDelegateScopes
    }
    setLoading(true)
    try {
      setIssued(await issueServiceAccountKeyApi(serviceAccountId, {
        name: name.trim(),
        scopes: selectedScopes,
        delegate_scopes: delegateScopes,
      }))
      setSaved(false)
      onIssued()
    } finally {
      setLoading(false)
    }
  }

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen && issued && !saved) return
    if (!nextOpen) {
      setIssued(null)
      setSaved(false)
      setName("")
      setSelectedScopes([])
      setDelegateScopeText("")
    }
    onOpenChange(nextOpen)
  }

  const keyExample = issued
    ? `curl -H "Authorization: Bearer ${issued.plaintext}" "${location.origin}/api/v2/auth/whoami"`
    : ""

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("openApiManagement.keys.issue")}</DialogTitle>
          <DialogDescription>{t("openApiManagement.keys.issueHint")}</DialogDescription>
        </DialogHeader>
        {issued ? (
          <div className="space-y-4">
            <p className="text-sm">{t("openApiManagement.keys.once")}</p>
            <div className="flex items-center gap-2 rounded-md bg-secondary p-3">
              <code className="min-w-0 flex-1 break-all text-sm">{issued.plaintext}</code>
              <Button variant="outline" onClick={() => copyText(issued.plaintext)}>
                {t("openApiManagement.actions.copy")}
              </Button>
            </div>
            <div className="flex items-center gap-2 rounded-md bg-secondary p-3">
              <code className="min-w-0 flex-1 break-all text-sm">{keyExample}</code>
              <Button variant="outline" onClick={() => copyText(keyExample)}>
                {t("openApiManagement.actions.copy")}
              </Button>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={saved} onCheckedChange={(checked) => setSaved(checked === true)} />
              {t("openApiManagement.keys.saved")}
            </label>
          </div>
        ) : (
          <div className="space-y-4">
            <label className="block space-y-1 text-sm">
              <span>{t("openApiManagement.fields.name")}</span>
              <Input value={name} maxLength={128} onChange={(event) => setName(event.target.value)} />
            </label>
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">{t("openApiManagement.keys.permissions")}</legend>
              {scopes.map((scope) => (
                <label key={scope.code} className="flex items-start gap-2 text-sm">
                  <Checkbox
                    checked={selectedScopes.includes(scope.code)}
                    onCheckedChange={(checked) => toggleScope(scope.code, checked === true)}
                  />
                  <span><strong>{scope.code}</strong><span className="block text-xs text-muted-foreground">{scope.endpoints.join(", ")}</span></span>
                </label>
              ))}
            </fieldset>
            {selectedScopes.includes("delegate") ? (
              <label className="block space-y-1 text-sm">
                <span>{t("openApiManagement.keys.delegateScopes")}</span>
                <Input
                  value={delegateScopeText}
                  placeholder={t("openApiManagement.keys.delegatePlaceholder")}
                  onChange={(event) => setDelegateScopeText(event.target.value)}
                />
                {delegateInvalid ? <span className="text-xs text-destructive">{t("openApiManagement.keys.delegateRequired")}</span> : null}
              </label>
            ) : null}
          </div>
        )}
        <DialogFooter>
          {issued ? (
            <Button disabled={!saved} onClick={() => handleOpenChange(false)}>{t("confirmButton")}</Button>
          ) : (
            <Button disabled={loading || !name.trim() || !selectedScopes.length || delegateInvalid} onClick={handleIssue}>
              {t("openApiManagement.keys.issue")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
