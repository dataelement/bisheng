import { Button, Input, PasswordInput, Select, notification } from '@bisheng/ui';
import { validateAccount, validateNickname, validatePassword } from '@bisheng/identity';
import { isApiError } from '@bisheng/api-client';
import { IdentityRuleHint, updateIdentityInput } from '@/components/bs-comp/identity/identityInput';

import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels"

import { Label } from "@/components/bs-ui/label"

import {
  createDepartmentLocalMemberApi,
  getDepartmentAssignableRolesApi,
} from "@/controllers/API/department"
import { showApiError } from "@/controllers/request"
import { handleEncrypt } from "@/pages/LoginPage/utils"
import { copyText } from "@/utils"
import { useCallback, useEffect, useRef, useState } from "react"
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
  const submittingRef = useRef(false)
  const [submitted, setSubmitted] = useState(false)
  const [touched, setTouched] = useState<Record<string, boolean>>({})
  const [expandedRule, setExpandedRule] = useState<'account' | 'nickname' | null>(null)
  const [accountConflict, setAccountConflict] = useState(false)
  const errors = { account: validateAccount(personId), nickname: validateNickname(userName), password: validatePassword(password) }
  const fieldValues = { account: personId, nickname: userName, password }
  const visibleError = (field: keyof typeof errors) => field === 'account' && accountConflict ? 'accountExists' :
    fieldValues[field] || touched[field] || submitted ? errors[field] : undefined

  const loadRoles = useCallback(() => {
    getDepartmentAssignableRolesApi(deptId).then((list) => {
      if (list && list.length > 0) {
        setRoles(list.map((r) => ({ id: r.id, role_name: r.role_name })))
      } else {
        setRoles([])
      }
    }).catch(showApiError)
  }, [deptId])

  useEffect(() => {
    setSelected(new Set())
    loadRoles()
  }, [loadRoles])

  const handleSubmit = async () => {
    if (submittingRef.current) return
    setSubmitted(true)
    if (Object.values(errors).some(Boolean)) return
    submittingRef.current = true
    setSubmitting(true)
    try {
      const enc = await handleEncrypt(password)
      const res = await createDepartmentLocalMemberApi(deptId, {
          user_name: userName,
          person_id: personId,
          password: enc,
          role_ids: Array.from(selected),
        })
      if (res) {
        const tip = t("bs:department.localUserCreatedTip", {
          name: res.user_name,
          person: res.person_id,
        })
        try {
          await copyText(`${t("accountIdentity.account")}: ${res.person_id}\n${t("system.initialPassword")}: ${password}`)
        } catch (error) {
          // Clipboard access is optional; the user has already been created.
          console.warn('Could not copy the newly created account credentials', error)
        }
        notification.open({ type: "success", title: String(t("bs:department.createLocalUser") ?? ''), description: String(tip ?? '') })
        onCreated()
        onClose()
      }
    } catch (error) {
      if (isApiError(error) && error.status_code === 10613) setAccountConflict(true)
      showApiError(error)
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  const renderIdentity = (field: 'account' | 'nickname') => {
    const error = visibleError(field)
    const handleValue = (value: string) => {
      if (field === 'account') { setPersonId(value); if (value !== personId) setAccountConflict(false) } else setUserName(value)
    }
    return <div className="grid gap-1.5">
      <Label htmlFor={`create-local-${field}`}>{t(`accountIdentity.${field}`)}</Label>
      <Input id={`create-local-${field}`} size="medium" value={fieldValues[field]} disabled={submitting}
        onChange={event => updateIdentityInput(event.currentTarget, handleValue, (event.nativeEvent as InputEvent).isComposing)}
        onCompositionEnd={event => updateIdentityInput(event.currentTarget, handleValue)}
        onBlur={() => setTouched(previous => ({ ...previous, [field]: true }))}
        placeholder={t(`accountIdentity.${field}Placeholder`)} autoCapitalize="none" autoCorrect="off" spellCheck={false}
        status={error ? 'error' : 'default'} aria-invalid={Boolean(error)}
        aria-describedby={error ? `create-local-${field}-error` : expandedRule === field ? `create-local-${field}-rules` : undefined}
        suffix={<IdentityRuleHint field={field} expanded={expandedRule === field} controls={`create-local-${field}-rules`}
          onToggle={() => setExpandedRule(previous => previous === field ? null : field)} />} />
      {error && <p id={`create-local-${field}-error`} className="text-caption text-danger" aria-live="polite">{t(`accountIdentity.errors.${error}`)}</p>}
      {expandedRule === field && <p id={`create-local-${field}-rules`} className="text-caption text-text-3">{t(`accountIdentity.${field}Rules`)}</p>}
    </div>
  }

  return (
    <Dialog open onOpenChange={() => { if (!submittingRef.current) onClose() }}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("bs:department.createLocalUser")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          {renderIdentity('account')}
          {renderIdentity('nickname')}
          <div>
            <Label htmlFor="create-local-password">{t("system.initialPassword")}</Label>
            <PasswordInput id="create-local-password" size="medium" value={password} disabled={submitting}
              onChange={(event) => setPassword(event.target.value)} onBlur={() => setTouched(previous => ({ ...previous, password: true }))}
              placeholder={t("bs:department.createLocalPasswordPlaceholder")} className="mt-1"
              status={visibleError('password') ? 'error' : 'default'} aria-invalid={Boolean(visibleError('password'))}
              aria-describedby="create-local-password-rule"
              revealLabel={t('sharedUi.showPassword')} hideLabel={t('sharedUi.hidePassword')} />
            <p id="create-local-password-rule" className={`mt-1 text-caption ${visibleError('password') ? 'text-danger' : 'text-text-3'}`}>
              {t(visibleError('password') ? `accountIdentity.errors.${visibleError('password')}` : 'accountIdentity.passwordRules')}
            </p>
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
                disabled={submitting}
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
          <Button variant="outlined" onClick={onClose} color="default" disabled={submitting}>
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
