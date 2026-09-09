import { Button } from "@/components/bs-ui/button"
import DepartmentUsersSelect, { type DepartmentUserOption } from "@/components/bs-comp/selectComponent/DepartmentUsersSelect"
import { TreeDepartmentSelect } from "@/components/bs-comp/department/TreeDepartmentSelect"
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
import { message } from "@/components/bs-ui/toast/use-toast"
import { issueServiceAccountKeyApi, updateServiceAccountKeyApi } from "@/controllers/API/serviceAccount"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import type { ApiKeyIssued, ApiKeyItem, DelegateScopeInput, OpenApiScopeItem } from "@/types/api/openApi"
import { copyText } from "@/utils"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { Loader2 } from "lucide-react"

export interface KeyIssueDialogProps {
  serviceAccountId: number
  scopes: OpenApiScopeItem[]
  editingKey: ApiKeyItem | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onIssued: () => void
}

type DelegateDepartment = { id: number; name: string }

export function KeyIssueDialog({
  serviceAccountId,
  scopes,
  editingKey,
  open,
  onOpenChange,
  onIssued,
}: KeyIssueDialogProps) {
  const { t } = useTranslation()
  const [name, setName] = useState("")
  const [expiresAt, setExpiresAt] = useState("")
  const [selectedScopes, setSelectedScopes] = useState<string[]>([])
  const [delegateUsers, setDelegateUsers] = useState<DepartmentUserOption[]>([])
  const [delegateDepartments, setDelegateDepartments] = useState<DelegateDepartment[]>([])
  const [issued, setIssued] = useState<ApiKeyIssued | null>(null)
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(false)
  const delegateInvalid = selectedScopes.includes("delegate")
    && !delegateUsers.length && !delegateDepartments.length

  useEffect(() => {
    if (!open) return
    setIssued(null)
    setSaved(false)
    setName(editingKey?.name || "")
    setExpiresAt(editingKey?.expires_at?.slice(0, 16) || "")
    setSelectedScopes(editingKey ? [...editingKey.scopes] : [])
    setDelegateUsers((editingKey?.delegate_scopes || [])
      .filter((scope) => scope.subject_type === "user")
      .map((scope) => ({
        value: scope.subject_id,
        label: scope.subject_name || `user:${scope.subject_id}`,
      })))
    setDelegateDepartments((editingKey?.delegate_scopes || [])
      .filter((scope) => scope.subject_type === "department")
      .map((scope) => ({
        id: scope.subject_id,
        name: scope.subject_name || `department:${scope.subject_id}`,
      })))
  }, [editingKey, open])

  const toggleScope = (code: string, checked: boolean) => {
    setSelectedScopes((current) => checked ? [...current, code] : current.filter((item) => item !== code))
    if (code === "delegate" && !checked) {
      setDelegateUsers([])
      setDelegateDepartments([])
    }
  }

  const handleIssue = async () => {
    let delegateScopes: DelegateScopeInput[] = []
    if (selectedScopes.includes("delegate")) {
      if (delegateInvalid) return
      delegateScopes = delegateUsers.map((user) => ({
        subject_type: "user" as const,
        subject_id: user.value,
      }))
      delegateScopes.push(...delegateDepartments.map((department) => ({
        subject_type: "department" as const,
        subject_id: department.id,
      })))
    }
    setLoading(true)
    try {
      const payload = {
        name: name.trim(),
        scopes: selectedScopes,
        expires_at: expiresAt || null,
        delegate_scopes: delegateScopes,
      }
      if (editingKey) {
        const updated = await captureAndAlertRequestErrorHoc(
          updateServiceAccountKeyApi(serviceAccountId, editingKey.id, payload),
        )
        if (!updated) return
        message({ description: t("openApiManagement.feedback.keyUpdated") })
        onIssued()
        handleOpenChange(false)
        return
      }
      const result = await captureAndAlertRequestErrorHoc(issueServiceAccountKeyApi(serviceAccountId, payload))
      if (!result) return
      setIssued(result)
      setSaved(false)
      message({ description: t("openApiManagement.feedback.keyIssued") })
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
      setExpiresAt("")
      setSelectedScopes([])
      setDelegateUsers([])
      setDelegateDepartments([])
    }
    onOpenChange(nextOpen)
  }

  const keyExample = issued
    ? `curl -H "Authorization: Bearer ${issued.plaintext}" "${location.origin}/api/v2/auth/whoami"`
    : ""

  const handleCopy = (value: string) => {
    copyText(value)
    message({ description: t("openApiManagement.feedback.copied") })
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t(editingKey ? "openApiManagement.keys.edit" : "openApiManagement.keys.issue")}</DialogTitle>
          <DialogDescription>{t("openApiManagement.keys.issueHint")}</DialogDescription>
        </DialogHeader>
        {issued ? (
          <div className="space-y-4">
            <p className="text-sm">{t("openApiManagement.keys.once")}</p>
            <div className="flex items-center gap-2 rounded-md bg-secondary p-3">
              <code className="min-w-0 flex-1 break-all text-sm">{issued.plaintext}</code>
              <Button variant="outline" onClick={() => handleCopy(issued.plaintext)}>
                {t("openApiManagement.actions.copy")}
              </Button>
            </div>
            <div className="flex items-center gap-2 rounded-md bg-secondary p-3">
              <code className="min-w-0 flex-1 break-all text-sm">{keyExample}</code>
              <Button variant="outline" onClick={() => handleCopy(keyExample)}>
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
            <label className="block space-y-1 text-sm">
              <span>{t("openApiManagement.fields.expiresAt")}</span>
              <Input type="datetime-local" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} />
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
              <div className="space-y-3 text-sm">
                <label className="block space-y-1">
                  <span>{t("openApiManagement.keys.delegateUsers")}</span>
                  <DepartmentUsersSelect
                    value={delegateUsers}
                    onChange={setDelegateUsers}
                    placeholder={t("openApiManagement.keys.delegateUserPlaceholder")}
                    searchPlaceholder={t("openApiManagement.serviceAccount.ownerSearch")}
                  />
                </label>
                <label className="block space-y-1">
                  <span>{t("openApiManagement.keys.delegateDepartment")}</span>
                  <TreeDepartmentSelect
                    value={null}
                    onChange={(id, node) => {
                      if (id === null || !node || delegateDepartments.some((item) => item.id === id)) return
                      setDelegateDepartments((current) => [...current, { id, name: node.name }])
                    }}
                    modal={false}
                    placeholder={t("openApiManagement.keys.delegateDepartmentPlaceholder")}
                  />
                  {delegateDepartments.length ? (
                    <div className="flex flex-wrap gap-2 pt-1">
                      {delegateDepartments.map((department) => (
                        <Button
                          key={department.id}
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => setDelegateDepartments((current) => current.filter((item) => item.id !== department.id))}
                        >
                          {department.name} ×
                        </Button>
                      ))}
                    </div>
                  ) : null}
                </label>
                {delegateInvalid ? <span className="text-xs text-destructive">{t("openApiManagement.keys.delegateRequired")}</span> : null}
              </div>
            ) : null}
          </div>
        )}
        <DialogFooter>
          {issued ? (
            <Button disabled={!saved} onClick={() => handleOpenChange(false)}>{t("confirmButton")}</Button>
          ) : (
            <Button disabled={loading || !name.trim() || delegateInvalid} onClick={handleIssue}>
              {loading ? <Loader2 aria-hidden="true" className="mr-2 size-4 animate-spin" /> : null}
              {t(editingKey ? "save" : "openApiManagement.keys.issue")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
