import DepartmentUsersSelect, {
  DepartmentUserOption,
} from "@/components/bs-comp/selectComponent/DepartmentUsersSelect"
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { Input, Textarea } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { toast } from "@/components/bs-ui/toast/use-toast"
import { locationContext } from "@/contexts/locationContext"
import {
  deleteServiceAccountApi,
  disableServiceAccountApi,
  enableServiceAccountApi,
  updateServiceAccountApi,
} from "@/controllers/API/serviceAccount"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import {
  ServiceAccountDetail as ServiceAccountDetailData,
  ServiceAccountUpdateForm,
} from "@/types/api/serviceAccount"
import { formatIsoDateTime } from "@/util/utils"
import { useContext, useState } from "react"
import { useTranslation } from "react-i18next"

interface OverviewTabProps {
  detail: ServiceAccountDetailData
  /** Reload the detail after a mutation */
  onChanged: () => void
  /** Deletion returns to the list */
  onDeleted: () => void
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <Label className="text-muted-foreground">{label}</Label>
      <div className="text-sm">{children}</div>
    </div>
  )
}

/**
 * Overview tab: identity + creation info, the editable resource owner, and the
 * enable / disable / delete lifecycle actions (AC-41 / AC-47 / AC-48).
 */
export function OverviewTab({ detail, onChanged, onDeleted }: OverviewTabProps) {
  const { t } = useTranslation("serviceAccount")
  const { appConfig } = useContext(locationContext)
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(detail.name)
  const [description, setDescription] = useState(detail.description || "")
  const [owner, setOwner] = useState<DepartmentUserOption[]>([])
  const [saving, setSaving] = useState(false)

  // Mirrors the create dialog: the tenant is only named where more than one exists.
  const ownerPlaceholder = appConfig.multiTenantEnabled
    ? t("create.resourceOwnerPlaceholderTenant")
    : t("create.resourceOwnerPlaceholder")

  const startEdit = () => {
    setName(detail.name)
    setDescription(detail.description || "")
    setOwner(
      detail.resource_owner
        ? [
            {
              label: detail.resource_owner.user_name || String(detail.resource_owner.user_id),
              value: detail.resource_owner.user_id,
            },
          ]
        : []
    )
    setEditing(true)
  }

  // PATCH carries changed fields only — an absent field means "unchanged".
  const handleSave = () => {
    const trimmed = name.trim()
    if (!trimmed) {
      toast({ title: t("title"), description: t("create.nameRequired"), variant: "error" })
      return
    }
    if (!owner.length) {
      toast({ title: t("title"), description: t("create.resourceOwnerRequired"), variant: "error" })
      return
    }
    const payload: ServiceAccountUpdateForm = {}
    if (trimmed !== detail.name) payload.name = trimmed
    if (description.trim() !== (detail.description || "")) payload.description = description.trim()
    const ownerId = Number(owner[0].value)
    if (ownerId !== detail.resource_owner?.user_id) payload.resource_owner_user_id = ownerId
    if (!Object.keys(payload).length) {
      setEditing(false)
      return
    }
    setSaving(true)
    captureAndAlertRequestErrorHoc(updateServiceAccountApi(detail.id, payload)).then((res) => {
      setSaving(false)
      if (!res) return
      toast({ title: t("title"), description: t("common.saved"), variant: "success" })
      setEditing(false)
      onChanged()
    })
  }

  const handleDisable = () => {
    bsConfirm({
      title: t("overview.disableConfirmTitle"),
      desc: t("overview.disableConfirmDesc"),
      okTxt: t("overview.disable"),
      onOk(next) {
        captureAndAlertRequestErrorHoc(disableServiceAccountApi(detail.id)).then((res) => {
          if (!res) return
          toast({
            title: t("title"),
            description: t("overview.disableSuccess"),
            variant: "success",
          })
          onChanged()
        })
        next()
      },
    })
  }

  const handleEnable = () => {
    bsConfirm({
      title: t("overview.enableConfirmTitle"),
      desc: t("overview.enableConfirmDesc"),
      okTxt: t("overview.enable"),
      onOk(next) {
        captureAndAlertRequestErrorHoc(enableServiceAccountApi(detail.id)).then((res) => {
          if (!res) return
          toast({ title: t("title"), description: t("overview.enableSuccess"), variant: "success" })
          onChanged()
        })
        next()
      },
    })
  }

  // Deletion is never blocked (AC-48): the dialog states what it takes down and
  // then deletes on confirm. The grant list is structurally empty until the
  // subject-side reverse lookup ships (T065 / T067).
  const handleDelete = () => {
    bsConfirm({
      title: t("overview.deleteConfirmTitle"),
      desc: (
        <div className="space-y-2 text-left">
          <p>{t("overview.deleteGrantsEmpty")}</p>
          <p>{t("overview.deleteConfirmDesc")}</p>
        </div>
      ),
      okTxt: t("overview.delete"),
      onOk(next) {
        captureAndAlertRequestErrorHoc(deleteServiceAccountApi(detail.id)).then((res) => {
          if (!res) return
          toast({ title: t("title"), description: t("overview.deleteSuccess"), variant: "success" })
          onDeleted()
        })
        next()
      },
    })
  }

  const ownerDisabled = detail.owner_disabled || !!detail.resource_owner?.disabled

  return (
    <div className="max-w-[720px] space-y-6 py-4">
      <div className="grid grid-cols-2 gap-4">
        <Field label={t("common.name")}>
          {editing ? (
            <Input value={name} maxLength={64} onChange={(e) => setName(e.target.value)} />
          ) : (
            detail.name
          )}
        </Field>
        <Field label={t("common.status")}>{t(`status.${detail.status}`)}</Field>
        <div className="col-span-2">
          <Field label={t("common.description")}>
            {editing ? (
              <Textarea
                value={description}
                maxLength={512}
                rows={3}
                onChange={(e) => setDescription(e.target.value)}
              />
            ) : (
              detail.description || "-"
            )}
          </Field>
        </div>
        {appConfig.multiTenantEnabled && (
          <Field label={t("overview.tenant")}>{detail.tenant_id}</Field>
        )}
        <Field label={t("overview.createdBy")}>
          {detail.creator_name || t("list.unknownUser")}
        </Field>
        <Field label={t("overview.createTime")}>{formatIsoDateTime(detail.create_time)}</Field>
        <div className="col-span-2">
          <Field label={t("overview.resourceOwner")}>
            {editing ? (
              <div className="space-y-2">
                <DepartmentUsersSelect
                  multiple={false}
                  value={owner}
                  onChange={setOwner}
                  placeholder={ownerPlaceholder}
                />
                <p className="text-sm text-muted-foreground">
                  {t("overview.ownerNotRetroactive")}
                </p>
                {appConfig.openPlatformEnabled && (
                  <p className="text-sm text-muted-foreground">
                    {t("create.resourceOwnerOpenPlatformTip")}
                  </p>
                )}
              </div>
            ) : (
              <span className={ownerDisabled ? "text-red-500" : ""}>
                {detail.resource_owner?.user_name || t("list.unknownUser")}
                {ownerDisabled ? ` (${t("status.disabled")})` : ""}
              </span>
            )}
          </Field>
        </div>
      </div>

      <div className="flex flex-wrap gap-3">
        {editing ? (
          <>
            <Button disabled={saving} onClick={handleSave}>
              {t("common.save")}
            </Button>
            <Button variant="outline" disabled={saving} onClick={() => setEditing(false)}>
              {t("common.cancel")}
            </Button>
          </>
        ) : (
          <>
            <Button variant="outline" onClick={startEdit}>
              {t("common.edit")}
            </Button>
            {detail.status === "enabled" ? (
              <Button variant="outline" onClick={handleDisable}>
                {t("overview.disable")}
              </Button>
            ) : (
              <Button variant="outline" onClick={handleEnable}>
                {t("overview.enable")}
              </Button>
            )}
            <Button variant="destructive" onClick={handleDelete}>
              {t("overview.delete")}
            </Button>
          </>
        )}
      </div>
    </div>
  )
}
