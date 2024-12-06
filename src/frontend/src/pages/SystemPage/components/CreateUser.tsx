import { Button } from "@/components/bs-ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Input, PasswordInput } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { generateUUID } from "@/components/bs-ui/utils"
import { createUserApi } from "@/controllers/API/user"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { handleEncrypt, PWD_RULE } from "@/pages/LoginPage/utils"
import { copyText } from "@/utils"
import { Plus } from "lucide-react"
import { useState } from "react"
import { useTranslation } from "react-i18next"
import UserRoleItem from "./UserRoleItem"

export default function CreateUser({ open, onClose, onSave }) {
    const { t } = useTranslation()
    const { message } = useToast()
    const initItems = { key: generateUUID(8), groupId: '', roles: [] }
    const initUser = {
        user_name: '',
        password: '',
    }

    const [items, setItems] = useState([initItems])
    const [form, setForm] = useState(initUser)

    const handleCancel = () => {
        onClose(false)
        setItems([initItems])
        setForm(initUser)
    }
    const errors = []
    const handleConfirm = async () => {
        if (form.user_name === '') errors.push(t('system.usernameRequired'))
        if (form.user_name.length > 30) errors.push(t('system.usernameMaxLength'))
        if (!PWD_RULE.test(form.password)) errors.push(t('system.passwordRequirements'))
        if (items.every(item => item.roles.length === 0)) errors.push(t('system.roleRequired'))
        if (errors.length > 0) return message({ title: t('prompt'), description: errors, variant: 'warning' })

        const encryptPwd = await handleEncrypt(form.password)
        const group_roles = items.map(item => ({
            group_id: Number(item.groupId),
            role_ids: item.roles.map(r => Number(r))
        }))
        captureAndAlertRequestErrorHoc(createUserApi(form.user_name, encryptPwd, group_roles).then(() => {
            copyText(`${t('system.username')}: ${form.user_name}，${t('system.initialPassword')}: ${form.password}`).then(() =>
                message({ title: t('prompt'), description: t('system.userCreationSuccess'), variant: 'success' }))
            onClose(false)
            setItems([initItems])
            setForm(initUser)
            onSave()
        }))
    }

    const handleChangeRoleItems = (index, groupId, roles) => {
        setItems(items => items.map((item, i) => {
            return i === index ? { ...item, groupId: groupId[0], roles } : item
        }))
    }

    return <Dialog open={open} onOpenChange={b => onClose(b)}>
        <DialogContent className="sm:max-w-[625px]">
            <DialogHeader>
                <DialogTitle>{t('system.createUser')}</DialogTitle>
            </DialogHeader>
            <div className="flex flex-col gap-4 mb-4">
                <div>
                    <Label htmlFor="user" className="bisheng-label">{t('system.username')}</Label>
                    <Input id="user" value={form.user_name} onChange={(e) => setForm({ ...form, user_name: e.target.value })}
                        placeholder={t('system.usernamePlaceholder')} className="h-[48px]" />
                </div>
                <div>
                    <Label htmlFor="password" className="bisheng-label">{t('system.initialPassword')}</Label>
                    <PasswordInput id="password" value={form.password} placeholder={t('system.passwordPlaceholder')}
                        onChange={(e) => setForm({ ...form, password: e.target.value })} inputClassName="h-[48px]" />
                </div>
                <div className="flex flex-col gap-2">
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
                    <Button variant="outline" size="icon" onClick={() =>
                        setItems(items => [...items, { key: generateUUID(8), groupId: '', roles: [] }])
                    }>
                        <Plus />
                    </Button>
                </div>
            </div>
            <DialogFooter>
                <Button variant="outline" className="h-10 w-[120px] px-16" onClick={handleCancel}>{t('cancel')}</Button>
                <Button className="px-16 h-10 w-[120px]" onClick={handleConfirm}>{t('confirm')}</Button>
            </DialogFooter>
        </DialogContent>
    </Dialog>
}
