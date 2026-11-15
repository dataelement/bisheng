import { Button, Input, PasswordInput, toast } from '@bisheng/ui';
import { validateAccount, validateNickname, validatePassword } from '@bisheng/identity';
import { isApiError } from '@bisheng/api-client';
import { IdentityRuleHint, updateIdentityInput } from '@/components/bs-comp/identity/identityInput';

import { Dialog,DialogContent,DialogFooter,DialogHeader,DialogTitle } from "@/components/bs-ui/dialog";

import { Label } from "@/components/bs-ui/label";

import { generateUUID } from "@/components/bs-ui/utils";
import { createUserApi } from "@/controllers/API/user";
import { handleUiRequest } from "@/controllers/request";
import { handleEncrypt } from "@/pages/LoginPage/utils";
import { copyText } from "@/utils";
import { Outlined } from "bisheng-icons";

import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import UserRoleItem from "./UserRoleItem";

interface CreateUserProps { open: boolean; onClose: (open: boolean) => void; onSave: () => void; }

export function CreateUser({ open, onClose, onSave }: CreateUserProps) {
    const { t } = useTranslation()

    const initItems = { key: generateUUID(8), groupId: '', roles: [] as string[] }
    const initUser = {
        user_name: '',
        external_id: '',
        password: '',
    }

    const [items, setItems] = useState([initItems])
    const [form, setForm] = useState(initUser)
    const [submitted, setSubmitted] = useState(false)
    const [saving, setSaving] = useState(false)
    const pending = useRef(false)
    const [expandedRule, setExpandedRule] = useState<'account' | 'nickname' | null>(null)
    const [accountConflict, setAccountConflict] = useState(false)
    const errors = { account: validateAccount(form.external_id), nickname: validateNickname(form.user_name), password: validatePassword(form.password) }

    const handleCancel = () => {
        if (pending.current) return
        onClose(false)
        setItems([initItems])
        setForm(initUser)
        setSubmitted(false)
        setAccountConflict(false)
        setExpandedRule(null)
    }
    const handleConfirm = async () => {
        if (pending.current) return
        setSubmitted(true)
        if (Object.values(errors).some(Boolean)) return
        if (items.every(item => item.roles.length === 0)) return toast.show({ type: 'warning', message: t('system.roleRequired') })
        pending.current = true
        setSaving(true)
        try {
        const encryptPwd = await handleEncrypt(form.password)
        const group_roles = items.map(item => ({
            group_id: Number(item.groupId),
            role_ids: item.roles.map(r => Number(r))
        }))
        await createUserApi(form.user_name, encryptPwd, group_roles, form.external_id).then(async () => {
            try { await copyText(`${t('accountIdentity.account')}: ${form.external_id}\n${t('system.initialPassword')}: ${form.password}`) }
            catch { console.warn('Optional credential clipboard copy failed') }
            toast.show({ type: 'success', message: `${t('system.userCreationSuccess')} · ${t('accountIdentity.account')}: ${form.external_id}` })
            onClose(false)
            setItems([initItems])
            setForm(initUser)
            setSubmitted(false)
            setAccountConflict(false)
            setExpandedRule(null)
            onSave()
        })
        } catch (error) {
            if (isApiError(error) && error.status_code === 10613) setAccountConflict(true)
            throw error
        } finally { pending.current = false; setSaving(false) }
    }

    const handleChangeRoleItems = (index: number, groupId: string[], roles: string[]) => {
        setItems(items => items.map((item, i) => {
            return i === index ? { ...item, groupId: groupId[0] ?? '', roles } : item
        }))
    }

    const renderIdentity = (field: 'account' | 'nickname') => {
        const property = field === 'account' ? 'external_id' : 'user_name'
        const value = form[property]
        const error = field === 'account' && accountConflict ? 'accountExists' : value || submitted ? errors[field] : undefined
        const handleValue = (next: string) => {
            setForm(previous => ({ ...previous, [property]: next }));
            if (field === 'account' && next !== value) setAccountConflict(false);
        }
        return <div className="grid gap-1.5">
            <Label htmlFor={`legacy-create-${field}`}>{t(`accountIdentity.${field}`)}</Label>
            <Input id={`legacy-create-${field}`} size="medium" value={value} disabled={saving}
                onChange={event => updateIdentityInput(event.currentTarget, handleValue, (event.nativeEvent as InputEvent).isComposing)}
                onCompositionEnd={event => updateIdentityInput(event.currentTarget, handleValue)}
                placeholder={t(`accountIdentity.${field}Placeholder`)} status={error ? 'error' : 'default'} aria-invalid={Boolean(error)}
                aria-describedby={error ? `legacy-create-${field}-error` : undefined}
                suffix={<IdentityRuleHint field={field} expanded={expandedRule === field} controls={`legacy-create-${field}-rules`}
                    onToggle={() => setExpandedRule(previous => previous === field ? null : field)} />} />
            {error && <p id={`legacy-create-${field}-error`} className="text-caption text-danger">{t(`accountIdentity.errors.${error}`)}</p>}
            {expandedRule === field && <p id={`legacy-create-${field}-rules`} className="text-caption text-text-3">{t(`accountIdentity.${field}Rules`)}</p>}
        </div>
    }

    return <Dialog open={open} onOpenChange={value => { if (!pending.current) onClose(value) }}>
        <DialogContent className="sm:max-w-[625px]">
            <DialogHeader>
                <DialogTitle>{t('system.createUser')}</DialogTitle>
            </DialogHeader>
            <div className="flex flex-col gap-4 mb-4">
                {renderIdentity('account')}
                {renderIdentity('nickname')}
                <div>
                    <Label htmlFor="password" className="bisheng-label">{t('system.initialPassword')}</Label>
                    <PasswordInput id="password" size="medium" value={form.password} placeholder={t('system.passwordPlaceholder')} disabled={saving}
                        onChange={(event) => setForm({ ...form, password: event.target.value })}
                        status={(form.password || submitted) && errors.password ? 'error' : 'default'}
                        revealLabel={t('sharedUi.showPassword')} hideLabel={t('sharedUi.hidePassword')} />
                    <p className={`mt-1 text-caption ${(form.password || submitted) && errors.password ? 'text-danger' : 'text-text-3'}`}>
                        {t((form.password || submitted) && errors.password ? `accountIdentity.errors.${errors.password}` : 'accountIdentity.passwordRules')}
                    </p>
                </div>
                <fieldset disabled={saving} className="flex flex-col gap-2">
                    <Label className="bisheng-label">{t('system.userGroupRoleSelection')}</Label>
                    <div className="max-h-[520px] overflow-y-auto flex flex-col gap-2">
                        {items.map((item, index) => <UserRoleItem key={item.key}
                            groupId={item.groupId + ''}
                            showDel={items.length > 1}
                            selectedRoles={[]}
                            onChange={(groupId, roles) => handleChangeRoleItems(index, groupId, roles)}
                            onDelete={() => setItems(items => items.filter((el, i) => i !== index))}
                        />)}
                    </div>
                    <Button variant="outlined" size="medium" aria-label={t('add')} onClick={() =>
                        setItems(items => [...items, { key: generateUUID(8), groupId: '', roles: [] }])
                    } color="default" iconOnly>
                        <Outlined.Plus size={16} />
                    </Button>
                </fieldset>
            </div>
            <DialogFooter>
                <Button variant="outlined" onClick={handleCancel} color="default" disabled={saving}>{t('cancel')}</Button>
                <Button onClick={handleUiRequest(handleConfirm)} loading={saving} disabled={saving}>{t('confirm')}</Button>
            </DialogFooter>
        </DialogContent>
    </Dialog>
}
