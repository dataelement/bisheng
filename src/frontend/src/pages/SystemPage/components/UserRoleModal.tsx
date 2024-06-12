import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import MultiSelect from "@/components/bs-ui/select/multi"
import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { Button } from "../../../components/bs-ui/button"
import { getRolesApi, getUserRoles, getUserGroupsApi, updateUserRoles, updateUserGroups } from "../../../controllers/API/user"
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request"
import { ROLE } from "../../../types/api/user"

export default function UserRoleModal({ user, onClose, onChange }) {
    const { t } = useTranslation()

    const [roles, setRoles] = useState<ROLE[]>([])
    const [selected, setSelected] = useState([])

    const [userGroups, setUserGroups] = useState([])
    const [userGroupSelected, setUserGroupSelected] = useState([])
    const [error, setError] = useState(false)

    useEffect(() => {
        if (!user) return
        // get用户组list
        getUserGroupsApi().then(res => {
            setUserGroups([{ id: 0, group_name: '默认用户组' }, ...res.records])
            setUserGroupSelected(user.groups.map(el => el.id.toString()))
        })
        // get角色list
        getRolesApi().then(data => {
            //@ts-ignore
            const roleOptions = data.filter(role => role.id !== 1)
                .map(role => ({ ...role, role_id: role.id }))
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
        setError(false)
    }, [user])

    const handleSave = async () => {
        // if (!selected.length) return setError(true)
        // if (userGroupSelected.length === 0) return setError(true)
        captureAndAlertRequestErrorHoc(updateUserRoles(user.user_id, selected.filter(id => id !== '2')))
        captureAndAlertRequestErrorHoc(updateUserGroups(user.user_id, userGroupSelected.filter(id => id !== '0')))
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
                    value={['0', ...userGroupSelected]}
                    options={groups}
                    lockedValues={["0"]}
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
                    value={['2', ...selected]}
                    options={_roles}
                    lockedValues={["2"]}
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