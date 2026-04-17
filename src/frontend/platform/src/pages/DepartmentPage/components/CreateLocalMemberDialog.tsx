import { Button } from "@/components/bs-ui/button"
import { Checkbox } from "@/components/bs-ui/checkBox"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Input, PasswordInput } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { toast } from "@/components/bs-ui/toast/use-toast"
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

  const toggleRole = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleSubmit = async () => {
    if (!userName.trim()) {
      toast({ title: t("prompt"), description: t("bs:department.localUserNameRequired"), variant: "error" })
      return
    }
    if (!personId.trim()) {
      toast({ title: t("prompt"), description: t("bs:department.personIdRequired"), variant: "error" })
      return
    }
    if (!PWD_RULE.test(password)) {
      toast({ title: t("prompt"), description: t("system.passwordRequirements"), variant: "error" })
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
        toast({ title: t("bs:department.createLocalUser"), description: tip, variant: "success" })
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
            <Input value={userName} onChange={(e) => setUserName(e.target.value)} className="mt-1" />
          </div>
          <div>
            <Label>{t("bs:department.personId")}</Label>
            <Input value={personId} onChange={(e) => setPersonId(e.target.value)} className="mt-1" />
          </div>
          <div>
            <Label>{t("system.initialPassword")}</Label>
            <PasswordInput value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1" />
          </div>
          <div>
            <Label>{t("bs:department.primaryDeptFixed")}</Label>
            <Input value={deptName} readOnly className="mt-1 bg-muted" />
          </div>
          <div>
            <Label>{t("bs:department.assignRoles")}</Label>
            <p className="mt-1 text-xs text-muted-foreground">
              {t("bs:department.assignRolesOptionalHint")}
            </p>
            <div className="mt-2 max-h-48 space-y-2 overflow-y-auto rounded border p-2">
              {roles.length === 0 ? (
                <div className="space-y-2">
                  <p className="text-sm text-muted-foreground">{t("build.empty")}</p>
                  <p className="text-xs text-muted-foreground">
                    {t("bs:department.assignRolesEmptyHint")}
                  </p>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7"
                    onClick={loadRoles}
                  >
                    {t("bs:department.refreshRoles")}
                  </Button>
                </div>
              ) : (
                roles.map((r) => (
                  <label key={r.id} className="flex cursor-pointer items-center gap-2 text-sm">
                    <Checkbox checked={selected.has(r.id)} onCheckedChange={() => toggleRole(r.id)} />
                    <span>{r.role_name}</span>
                  </label>
                ))
              )}
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
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
