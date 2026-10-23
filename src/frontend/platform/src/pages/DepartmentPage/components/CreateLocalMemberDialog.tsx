import { Button, Input, PasswordInput, Select, notification } from '@bisheng/ui';

import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels"

import { Label } from "@/components/bs-ui/label"

import {
  createDepartmentLocalMemberApi,
  getDepartmentAssignableRolesApi,
} from "@/controllers/API/department"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { handleEncrypt, PWD_RULE } from "@/pages/LoginPage/utils"
import { copyText } from "@/utils"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"

interface CreateLocalMemberDialogProps {
  deptId: string
  deptName: string
  onClose: () => void
  onCreated: () => void
}

export function CreateLocalMemberDialog({
  deptId,
  deptName,
  onClose,
  onCreated,
}: CreateLocalMemberDialogProps) {
  const { t } = useTranslation()
  const selectLabels = useSelectLabels()
  const [userName, setUserName] = useState("")
  const [personId, setPersonId] = useState("")
  const [password, setPassword] = useState("")
  const [roles, setRoles] = useState<{ id: number; role_name: string }[]>([])
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [submitting, setSubmitting] = useState(false)

  const loadRoles = useCallback(() => {
    captureAndAlertRequestErrorHoc(getDepartmentAssignableRolesApi(deptId)).then((list) => {
      if (list && list.length > 0) {
        setRoles(list.map((r) => ({ id: r.id, role_name: r.role_name })))
      } else {
        setRoles([])
      }
    })
  }, [deptId])

  useEffect(() => {
    setSelected(new Set())
    loadRoles()
  }, [loadRoles])

  const handleSubmit = async () => {
    if (!userName.trim()) {
      notification.open({ type: "error", title: String(t("prompt") ?? ''), description: String(t("bs:department.localUserNameRequired") ?? '') })
      return
    }
    if (!personId.trim()) {
      notification.open({ type: "error", title: String(t("prompt") ?? ''), description: String(t("bs:department.personIdRequired") ?? '') })
      return
    }
    if (!PWD_RULE.test(password)) {
      notification.open({ type: "error", title: String(t("prompt") ?? ''), description: String(t("system.passwordRequirements") ?? '') })
      return
    }
    setSubmitting(true)
    try {
      const enc = await handleEncrypt(password)
      const res = await captureAndAlertRequestErrorHoc(
        createDepartmentLocalMemberApi(deptId, {
          user_name: userName.trim(),
          person_id: personId.trim(),
          password: enc,
          role_ids: Array.from(selected),
        })
      )
      if (res) {
        const tip = t("bs:department.localUserCreatedTip", {
          name: res.user_name,
          person: res.person_id,
        })
        await copyText(`${t("bs:department.personId")}: ${res.person_id}\n${t("system.initialPassword")}: ${password}`)
        notification.open({ type: "success", title: String(t("bs:department.createLocalUser") ?? ''), description: String(tip ?? '') })
        onCreated()
        onClose()
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open onOpenChange={() => onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("bs:department.createLocalUser")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div>
            <Label>{t("system.username")}</Label>
            <Input value={userName} onChange={(e) => setUserName(e.target.value)} placeholder={t("bs:department.createLocalUserNamePlaceholder")} className={"mt-1"} />
          </div>
          <div>
            <Label>{t("bs:department.personId")}</Label>
            <Input value={personId} onChange={(e) => setPersonId(e.target.value)} placeholder={t("bs:department.createLocalPersonIdPlaceholder")} className={"mt-1"} />
          </div>
          <div>
            <Label>{t("system.initialPassword")}</Label>
            <PasswordInput value={password} onChange={(e) => setPassword(e.target.value)} placeholder={t("bs:department.createLocalPasswordPlaceholder")} className={"mt-1"} revealLabel={t('sharedUi.showPassword')} hideLabel={t('sharedUi.hidePassword')} />
          </div>
          <div>
            <Label>{t("bs:department.primaryDeptFixed")}</Label>
            <Input value={deptName} readOnly className={"mt-1 bg-muted"} />
          </div>
          <div>
            <Label>{t("bs:department.assignRoles")}</Label>
            <p className="mt-1 text-xs text-muted-foreground">
              {t("bs:department.assignRolesOptionalHint")}
            </p>
            {roles.length === 0 ? (
              <div className="mt-2 space-y-2">
                <p className="text-sm text-muted-foreground">{t("build.empty")}</p>
                <p className="text-xs text-muted-foreground">
                  {t("bs:department.assignRolesEmptyHint")}
                </p>
                <Button size="small" variant="outlined" onClick={loadRoles} color="default">
                  {t("bs:department.refreshRoles")}
                </Button>
              </div>
            ) : (
              <Select
                {...selectLabels}
                multiple
                showSearch
                className="mt-2"
                aria-label={t("bs:department.assignRoles")}
                options={roles
                  .filter((r) => r.id != null)
                  .map((r) => ({ label: r.role_name, value: String(r.id) }))}
                value={Array.from(selected).map(String)}
                onChange={(vals) => setSelected(new Set(vals.map((id) => Number(id))))}
                placeholder={t("bs:department.multiSelectRolesPlaceholder")}
              />
            )}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outlined" onClick={onClose} color="default">
            {t("cancel")}
          </Button>
          <Button disabled={submitting} onClick={handleSubmit}>
            {t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
