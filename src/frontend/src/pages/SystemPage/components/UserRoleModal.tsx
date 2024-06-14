import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import MultiSelect from "@/components/bs-ui/select/multi"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { Button } from "../../../components/bs-ui/button"
import { getRolesApi, getUserGroupsApi, updateUserGroups, updateUserRoles } from "../../../controllers/API/user"
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request"
import { ROLE } from "../../../types/api/user"

export default function UserRoleModal({ user, onClose, onChange }) {
    const { t } = useTranslation()

    const [roles, setRoles] = useState<ROLE[]>([])
    const [selected, setSelected] = useState([])

    const [userGroups, setUserGroups] = useState([])
    const [userGroupSelected, setUserGroupSelected] = useState([])

    useEffect(() => {
        if (!user) return
        // get用户组list
        getUserGroupsApi().then(res => {
            setUserGroups(res.records)
            setUserGroupSelected(user.groups.map(el => el.id.toString()))
        })
        // get角色list
        getRolesApi().then(data => {
            //@ts-ignore
            const roleOptions = data.map(role => ({ ...role, role_id: role.id }))
            setRoles(roleOptions);
            setSelected(user.roles.map(el => el.id.toString()))
            // getUserRoles(id).then(userRoles => {
            //     // 默认设置 普通用户
            //     if (!userRoles.find(role => role.role_id === 2)) {
            //         const roleByroles = roleOptions.find(role => role.role_id === 2)
            //         userRoles.unshift({ ...roleByroles })
            //     }
            //     setSelected(userRoles)
            // })
        })
    }, [user])

    const { message } = useToast()
    const handleSave = async () => {
        if (!selected.length) return message({ title: t('prompt'), variant: 'warning', description: '请选择角色' })
        if (userGroupSelected.length === 0) return message({ title: t('prompt'), variant: 'warning', description: '请选择用户组' })
        captureAndAlertRequestErrorHoc(updateUserRoles(user.user_id, selected))
        captureAndAlertRequestErrorHoc(updateUserGroups(user.user_id, userGroupSelected))
        onChange()
    }

    const groups = useMemo(() => userGroups.map((ug) => {
        return {
            label: ug.group_name,
            value: ug.id.toString()
        }
    }), [userGroups])
    const _roles = useMemo(() => roles.map((role) => {
        return {
            label: role.role_name,
            value: role.role_id.toString()
        }
    }), [roles])

    return <Dialog open={user} onOpenChange={onClose}>
        <DialogContent className="sm:max-w-[625px]">
            <DialogHeader>
                <DialogTitle>{t('system.userGroupsSel')}</DialogTitle>
            </DialogHeader>
            <div className="">
                <MultiSelect
                    multiple
                    className="max-w-[600px]"
                    value={userGroupSelected}
                    options={groups}
                    placeholder={t('system.userGroupsSel')}
                    onChange={setUserGroupSelected}
                >
                </MultiSelect>
            </div>
            <DialogHeader>
                <DialogTitle>{t('system.roleSelect')}</DialogTitle>
            </DialogHeader>
            <div className="">
                <MultiSelect
                    multiple
                    className="max-w-[600px]"
                    value={selected}
                    options={_roles}
                    placeholder={t('system.roleSelect')}
                    onChange={setSelected}
                >
                </MultiSelect>
            </div>
            <DialogFooter>
                <Button variant="outline" className="h-10 w-[120px] px-16" onClick={onClose}>{t('cancel')}</Button>
                <Button className="px-16 h-10 w-[120px]" onClick={handleSave}>{t('save')}</Button>
            </DialogFooter>
        </DialogContent>
    </Dialog>
};