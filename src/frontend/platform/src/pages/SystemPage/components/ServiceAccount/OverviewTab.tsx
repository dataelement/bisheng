import DepartmentUsersSelect, {
  type DepartmentUserOption,
} from "@/components/bs-comp/selectComponent/DepartmentUsersSelect"
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { Input, Textarea } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { toast } from "@/components/bs-ui/toast/use-toast"
import {
  deleteServiceAccountApi,
  listServiceAccountResourceGrantsApi,
  setServiceAccountEnabledApi,
  updateServiceAccountApi,
} from "@/controllers/API/serviceAccount"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import type {
  ServiceAccountForm,
  ServiceAccountItem,
} from "@/types/api/openApi"
import { formatIsoDateTime } from "@/util/utils"
import { Loader2 } from "lucide-react"
import { type ReactNode, useState } from "react"
import { useTranslation } from "react-i18next"

export interface OverviewTabProps {
  detail: ServiceAccountItem
  onChanged: (detail: ServiceAccountItem) => void
  onDeleted: () => void
}

interface FieldProps {
  label: string
  children: ReactNode
  className?: string
}

function Field({ label, children, className = "" }: FieldProps) {
  return (
    <div className={`space-y-1 ${className}`}>
      <Label className="text-muted-foreground">{label}</Label>
      <div className="text-sm">{children}</div>
    </div>
  )
}

export function OverviewTab({
  detail,
  onChanged,
  onDeleted,
}: OverviewTabProps) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(detail.name)
  const [description, setDescription] = useState(detail.description || "")
  const [owner, setOwner] = useState<DepartmentUserOption[]>([])
  const [loading, setLoading] = useState<"save" | "toggle" | "delete" | null>(
    null,
  )

  const startEdit = () => {
    setName(detail.name)
    setDescription(detail.description || "")
    setOwner([
      {
        value: detail.resource_owner.user_id,
        label:
          detail.resource_owner.user_name ||
          String(detail.resource_owner.user_id),
      },
    ])
    setEditing(true)
  }

  const handleSave = async () => {
    if (!name.trim() || owner.length !== 1) return
    const payload: Partial<ServiceAccountForm> = {}
    if (name.trim() !== detail.name) payload.name = name.trim()
    if (description.trim() !== (detail.description || "")) {
      payload.description = description.trim() || null
    }
    if (owner[0].value !== detail.resource_owner.user_id) {
      payload.resource_owner_user_id = owner[0].value
    }
    if (!Object.keys(payload).length) {
      setEditing(false)
      return
    }
    setLoading("save")
    try {
      const updated = await captureAndAlertRequestErrorHoc(
        updateServiceAccountApi(detail.id, payload),
      )
      if (!updated) return
      toast({
        title: t("openApiManagement.serviceAccount.title"),
        description: t("openApiManagement.feedback.updated"),
        variant: "success",
      })
      setEditing(false)
      onChanged(updated)
    } finally {
      setLoading(null)
    }
  }

  const handleToggle = () => {
    const enabled = detail.status !== "enabled"
    setLoading("toggle")
    void captureAndAlertRequestErrorHoc(
      setServiceAccountEnabledApi(detail.id, enabled),
    )
      .then((updated) => {
        if (!updated) return
        toast({
          title: t("openApiManagement.serviceAccount.title"),
          description: t(
            enabled
              ? "openApiManagement.feedback.enabled"
              : "openApiManagement.feedback.disabled",
          ),
          variant: "success",
        })
        onChanged(updated)
      })
      .finally(() => setLoading(null))
  }

  const handleDelete = async () => {
    setLoading("delete")
    const grants = await captureAndAlertRequestErrorHoc(
      listServiceAccountResourceGrantsApi(detail.id),
    ).finally(() => setLoading(null))
    if (!grants) return
    bsConfirm({
      title: t("openApiManagement.serviceAccount.deleteConfirmTitle"),
      desc: (
        <div className="space-y-2 text-left">
          <p>
            {t("openApiManagement.serviceAccount.deleteConfirm", {
              count: grants.length,
            })}
          </p>
          {grants.length ? (
            <div>
              <p className="font-medium">
                {t("openApiManagement.serviceAccount.deleteGrantListTitle")}
              </p>
              <ul className="mt-1 max-h-40 list-disc overflow-y-auto pl-5">
                {grants.map((grant) => (
                  <li key={grant.assignee_id}>
                    {grant.resource_name} · {grant.model_name}
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-muted-foreground">
              {t("openApiManagement.serviceAccount.deleteNoGrants")}
            </p>
          )}
        </div>
      ),
      onOk: (close) => {
        close()
        setLoading("delete")
        void captureAndAlertRequestErrorHoc(deleteServiceAccountApi(detail.id))
          .then((result) => {
            if (!result) return
            toast({
              title: t("openApiManagement.serviceAccount.title"),
              description: t("openApiManagement.feedback.deleted"),
              variant: "success",
            })
            onDeleted()
          })
          .finally(() => setLoading(null))
      },
    })
  }

  return (
    <div className="max-w-[720px] space-y-6 py-4">
      <div className="grid grid-cols-2 gap-4">
        <Field label={t("openApiManagement.fields.name")}>
          {editing ? (
            <Input
              value={name}
              maxLength={128}
              onChange={(event) => setName(event.target.value)}
            />
          ) : (
            detail.name
          )}
        </Field>
        <Field label={t("openApiManagement.fields.status")}>
          {t(`openApiManagement.status.${detail.status}`)}
        </Field>
        <Field label={t("openApiManagement.fields.tenant")}>
          {detail.tenant_id}
        </Field>
        <Field
          label={t("openApiManagement.fields.description")}
          className="col-span-2"
        >
          {editing ? (
            <Textarea
              value={description}
              maxLength={512}
              rows={3}
              onChange={(event) => setDescription(event.target.value)}
            />
          ) : (
            detail.description || "-"
          )}
        </Field>
        <Field
          label={t("openApiManagement.fields.owner")}
          className="col-span-2"
        >
          {editing ? (
            <div className="space-y-2">
              <DepartmentUsersSelect
                multiple={false}
                value={owner}
                onChange={setOwner}
                placeholder={t(
                  "openApiManagement.serviceAccount.ownerPlaceholder",
                )}
                searchPlaceholder={t(
                  "openApiManagement.serviceAccount.ownerSearch",
                )}
              />
              <p className="text-xs text-muted-foreground">
                {t("openApiManagement.serviceAccount.ownerNotRetroactive")}
              </p>
            </div>
          ) : (
            <span
              className={
                detail.resource_owner.disabled ? "text-destructive" : ""
              }
            >
              {detail.resource_owner.user_name || detail.resource_owner.user_id}
              {detail.resource_owner.disabled
                ? ` (${t("openApiManagement.status.disabled")})`
                : ""}
            </span>
          )}
        </Field>
        <Field label={t("openApiManagement.fields.creator")}>
          {detail.creator_name || detail.created_by || "-"}
        </Field>
        <Field label={t("openApiManagement.fields.createdAt")}>
          {formatIsoDateTime(detail.create_time)}
        </Field>
      </div>

      <div className="flex flex-wrap gap-3">
        {editing ? (
          <>
            <Button
              disabled={loading !== null || !name.trim() || owner.length !== 1}
              onClick={handleSave}
            >
              {loading === "save" ? (
                <Loader2
                  aria-hidden="true"
                  className="mr-2 size-4 animate-spin"
                />
              ) : null}
              {t("save")}
            </Button>
            <Button
              variant="outline"
              disabled={loading !== null}
              onClick={() => setEditing(false)}
            >
              {t("cancel")}
            </Button>
          </>
        ) : (
          <>
            <Button
              variant="outline"
              disabled={loading !== null}
              onClick={startEdit}
            >
              {t("edit")}
            </Button>
            <Button
              variant="outline"
              disabled={loading !== null}
              onClick={handleToggle}
            >
              {loading === "toggle" ? (
                <Loader2
                  aria-hidden="true"
                  className="mr-2 size-4 animate-spin"
                />
              ) : null}
              {t(
                detail.status === "enabled"
                  ? "openApiManagement.actions.disable"
                  : "openApiManagement.actions.enable",
              )}
            </Button>
            <Button
              variant="destructive"
              disabled={loading !== null}
              onClick={handleDelete}
            >
              {loading === "delete" ? (
                <Loader2
                  aria-hidden="true"
                  className="mr-2 size-4 animate-spin"
                />
              ) : null}
              {t("delete")}
            </Button>
          </>
        )}
      </div>
    </div>
  )
}
