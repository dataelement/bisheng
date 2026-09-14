import { TreeDepartmentSelect } from "@/components/bs-comp/department/TreeDepartmentSelect"
import DepartmentUsersSelect, {
  type DepartmentUserOption,
} from "@/components/bs-comp/selectComponent/DepartmentUsersSelect"
import { Button } from "@/components/bs-ui/button"
import { DatePicker } from "@/components/bs-ui/calendar/datePicker"
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
import { Label } from "@/components/bs-ui/label"
import { toast } from "@/components/bs-ui/toast/use-toast"
import { QuestionTooltip } from "@/components/bs-ui/tooltip"
import {
  issueServiceAccountKeyApi,
  updateServiceAccountKeyApi,
} from "@/controllers/API/serviceAccount"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import type {
  ApiKeyIssued,
  ApiKeyItem,
  ApiKeyUpdateForm,
  DelegateScopeInput,
  OpenApiScopeItem,
} from "@/types/api/openApi"
import { formatDate } from "@/util/utils"
import { Loader2 } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"

export interface KeyIssueDialogProps {
  serviceAccountId: number
  scopes: OpenApiScopeItem[]
  editingKey: ApiKeyItem | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onIssued: (issued: ApiKeyIssued) => void
  onUpdated: () => void
}

type DelegateDepartment = { id: number; name: string }

function toBackendDateTime(date: Date): string {
  return formatDate(date, "yyyy-MM-ddTHH:mm:ss")
}

function sameStringSet(left: string[], right: string[]): boolean {
  return (
    left.length === right.length && left.every((value) => right.includes(value))
  )
}

function serializeDelegateScopes(scopes: DelegateScopeInput[]): string[] {
  return scopes
    .map((scope) => `${scope.subject_type}:${scope.subject_id}`)
    .sort()
}

export function KeyIssueDialog({
  serviceAccountId,
  scopes,
  editingKey,
  open,
  onOpenChange,
  onIssued,
  onUpdated,
}: KeyIssueDialogProps) {
  const { t } = useTranslation()
  const [name, setName] = useState("")
  const [expiresAt, setExpiresAt] = useState<string | null>(null)
  const [selectedScopes, setSelectedScopes] = useState<string[]>([])
  const [delegateUsers, setDelegateUsers] = useState<DepartmentUserOption[]>([])
  const [delegateDepartments, setDelegateDepartments] = useState<
    DelegateDepartment[]
  >([])
  const [loading, setLoading] = useState(false)

  const delegateInvalid =
    selectedScopes.includes("delegate") &&
    !delegateUsers.length &&
    !delegateDepartments.length

  const groupedScopes = useMemo(() => {
    const groups = new Map<string, OpenApiScopeItem[]>()
    for (const scope of scopes.filter((item) => item.code !== "delegate")) {
      const items = groups.get(scope.group) || []
      items.push(scope)
      groups.set(scope.group, items)
    }
    return Array.from(groups, ([group, items]) => ({ group, items }))
  }, [scopes])

  const delegateScope = scopes.find((scope) => scope.code === "delegate")

  useEffect(() => {
    if (!open) return
    setName(editingKey?.name || "")
    setExpiresAt(editingKey?.expires_at || null)
    setSelectedScopes(editingKey ? [...editingKey.scopes] : [])
    setDelegateUsers(
      (editingKey?.delegate_scopes || [])
        .filter((scope) => scope.subject_type === "user")
        .map((scope) => ({
          value: scope.subject_id,
          label: scope.subject_name || String(scope.subject_id),
        })),
    )
    setDelegateDepartments(
      (editingKey?.delegate_scopes || [])
        .filter((scope) => scope.subject_type === "department")
        .map((scope) => ({
          id: scope.subject_id,
          name: scope.subject_name || String(scope.subject_id),
        })),
    )
  }, [editingKey, open])

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen && loading) return
    onOpenChange(nextOpen)
  }

  const toggleScope = (code: string, checked: boolean) => {
    setSelectedScopes((current) => {
      if (checked) return current.includes(code) ? current : [...current, code]
      return current.filter((item) => item !== code)
    })
    if (code === "delegate" && !checked) {
      setDelegateUsers([])
      setDelegateDepartments([])
    }
  }

  const handleSubmit = async () => {
    if (!name.trim() || delegateInvalid) return
    const delegateScopes: DelegateScopeInput[] = selectedScopes.includes(
      "delegate",
    )
      ? [
          ...delegateUsers.map((user) => ({
            subject_type: "user" as const,
            subject_id: user.value,
          })),
          ...delegateDepartments.map((department) => ({
            subject_type: "department" as const,
            subject_id: department.id,
          })),
        ]
      : []

    setLoading(true)
    try {
      const payload = {
        name: name.trim(),
        scopes: selectedScopes,
        expires_at: expiresAt,
        delegate_scopes: delegateScopes,
      }
      if (editingKey) {
        const updatePayload: ApiKeyUpdateForm = {}
        if (payload.name !== editingKey.name) updatePayload.name = payload.name
        if (!sameStringSet(payload.scopes, editingKey.scopes)) {
          updatePayload.scopes = payload.scopes
        }
        if ((payload.expires_at || null) !== (editingKey.expires_at || null)) {
          updatePayload.expires_at = payload.expires_at
        }
        if (
          !sameStringSet(
            serializeDelegateScopes(payload.delegate_scopes),
            serializeDelegateScopes(editingKey.delegate_scopes),
          )
        ) {
          updatePayload.delegate_scopes = payload.delegate_scopes
        }
        if (!Object.keys(updatePayload).length) {
          onOpenChange(false)
          return
        }
        const updated = await captureAndAlertRequestErrorHoc(
          updateServiceAccountKeyApi(
            serviceAccountId,
            editingKey.id,
            updatePayload,
          ),
        )
        if (!updated) return
        toast({
          title: t("openApiManagement.keys.edit"),
          description: t("openApiManagement.feedback.keyUpdated"),
          variant: "success",
        })
        onUpdated()
        return
      }
      const issued = await captureAndAlertRequestErrorHoc(
        issueServiceAccountKeyApi(serviceAccountId, payload),
      )
      if (!issued) return
      toast({
        title: t("openApiManagement.keys.issue"),
        description: t("openApiManagement.feedback.keyIssued"),
        variant: "success",
      })
      onIssued(issued)
    } finally {
      setLoading(false)
    }
  }

  const renderScope = (scope: OpenApiScopeItem) => {
    const endpointText = scope.endpoints.length
      ? scope.endpoints
          .map((endpoint) => `${endpoint.method} ${endpoint.path}`)
          .join("\n")
      : ""
    return (
      <label key={scope.code} className="flex cursor-pointer items-start gap-2">
        <Checkbox
          className="mt-0.5"
          checked={selectedScopes.includes(scope.code)}
          onCheckedChange={(checked) =>
            toggleScope(scope.code, checked === true)
          }
        />
        <span className="min-w-0 space-y-0.5">
          <span className="flex items-center gap-1 text-sm font-medium">
            {t(scope.label_key)}
            {endpointText ? (
              <QuestionTooltip
                content={
                  <span className="whitespace-pre-line">
                    {t("openApiManagement.keys.endpointsTitle")}\n{endpointText}
                  </span>
                }
              />
            ) : null}
          </span>
          <span className="block text-xs text-muted-foreground">
            {t(scope.desc_key)}
          </span>
          {scope.hint_keys.map((key) => (
            <span
              key={key}
              className="block text-xs font-medium text-orange-500"
            >
              {t(key)}
            </span>
          ))}
        </span>
      </label>
    )
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[640px]">
        <DialogHeader>
          <DialogTitle>
            {t(
              editingKey
                ? "openApiManagement.keys.edit"
                : "openApiManagement.keys.issue",
            )}
          </DialogTitle>
          <DialogDescription>
            {t("openApiManagement.keys.issueHint")}
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] space-y-4 overflow-y-auto py-2 pr-1">
          <div className="space-y-2">
            <Label>{t("openApiManagement.fields.name")} *</Label>
            <Input
              value={name}
              maxLength={128}
              placeholder={t("openApiManagement.keys.namePlaceholder")}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label>{t("openApiManagement.fields.expiresAt")}</Label>
            <div className="flex items-center gap-2">
              <DatePicker
                showTime
                value={expiresAt || undefined}
                placeholder={t("openApiManagement.keys.expiresAtPlaceholder")}
                onChange={(date) => setExpiresAt(toBackendDateTime(date))}
              />
              {expiresAt ? (
                <Button
                  type="button"
                  variant="link"
                  className="shrink-0 px-0"
                  onClick={() => setExpiresAt(null)}
                >
                  {t("openApiManagement.keys.clearExpiry")}
                </Button>
              ) : null}
            </div>
          </div>
          <div className="space-y-3">
            <Label>{t("openApiManagement.keys.permissions")}</Label>
            <p className="text-xs text-muted-foreground">
              {t("openApiManagement.keys.permissionsHint")}
            </p>
            {groupedScopes.map(({ group, items }) => (
              <div key={group} className="space-y-3 rounded-md border p-3">
                <p className="text-sm font-medium">
                  {t(`openApiManagement.scopeGroups.${group}`)}
                </p>
                <div className="space-y-3">{items.map(renderScope)}</div>
              </div>
            ))}
          </div>
          {delegateScope ? (
            <div className="space-y-3 rounded-md border p-3 text-sm">
              <Label>{t("openApiManagement.keys.delegateConfig")}</Label>
              <label className="flex cursor-pointer items-start gap-2">
                <Checkbox
                  className="mt-0.5"
                  checked={selectedScopes.includes("delegate")}
                  onCheckedChange={(checked) =>
                    toggleScope("delegate", checked === true)
                  }
                />
                <span className="min-w-0 space-y-0.5">
                  <span className="block font-medium">
                    {t(delegateScope.label_key)}
                  </span>
                  <span className="block text-xs text-muted-foreground">
                    {t(delegateScope.desc_key)}
                  </span>
                </span>
              </label>
              {selectedScopes.includes("delegate") ? (
                <>
                  {delegateScope.hint_keys.map((key) => (
                    <p
                      key={key}
                      className="text-xs font-medium text-orange-500"
                    >
                      {t(key)}
                    </p>
                  ))}
                  <label className="block space-y-2">
                    <span>{t("openApiManagement.keys.delegateUsers")}</span>
                    <DepartmentUsersSelect
                      value={delegateUsers}
                      onChange={setDelegateUsers}
                      placeholder={t(
                        "openApiManagement.keys.delegateUserPlaceholder",
                      )}
                      searchPlaceholder={t(
                        "openApiManagement.serviceAccount.ownerSearch",
                      )}
                    />
                  </label>
                  <label className="block space-y-2">
                    <span>
                      {t("openApiManagement.keys.delegateDepartment")}
                    </span>
                    <TreeDepartmentSelect
                      value={null}
                      onChange={(id, node) => {
                        if (
                          id === null ||
                          !node ||
                          delegateDepartments.some((item) => item.id === id)
                        )
                          return
                        setDelegateDepartments((current) => [
                          ...current,
                          { id, name: node.name },
                        ])
                      }}
                      modal={false}
                      placeholder={t(
                        "openApiManagement.keys.delegateDepartmentPlaceholder",
                      )}
                    />
                    {delegateDepartments.length ? (
                      <div className="flex flex-wrap gap-2 pt-1">
                        {delegateDepartments.map((department) => (
                          <Button
                            key={department.id}
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() =>
                              setDelegateDepartments((current) =>
                                current.filter(
                                  (item) => item.id !== department.id,
                                ),
                              )
                            }
                          >
                            {department.name} ×
                          </Button>
                        ))}
                      </div>
                    ) : null}
                  </label>
                  {delegateInvalid ? (
                    <span className="text-xs text-destructive">
                      {t("openApiManagement.keys.delegateRequired")}
                    </span>
                  ) : null}
                </>
              ) : null}
            </div>
          ) : null}
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            disabled={loading}
            onClick={() => handleOpenChange(false)}
          >
            {t("cancel")}
          </Button>
          <Button
            disabled={loading || !name.trim() || delegateInvalid}
            onClick={handleSubmit}
          >
            {loading ? (
              <Loader2
                aria-hidden="true"
                className="mr-2 size-4 animate-spin"
              />
            ) : null}
            {t(editingKey ? "save" : "openApiManagement.keys.issue")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
