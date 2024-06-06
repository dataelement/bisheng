import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import MultiSelect from "@/components/bs-ui/select/multi"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { Button } from "../../../components/bs-ui/button"
import { getRolesApi, getUserRoles, getUserGroupsApi, updateUserRoles, updateUserGroups } from "../../../controllers/API/user"
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request"
import { ROLE } from "../../../types/api/user"

export default function UserRoleModal({ id, onClose, onChange }) {
    const { t } = useTranslation()

    const [roles, setRoles] = useState<ROLE[]>([])
    const [selected, setSelected] = useState([])

    const [userGroups, setUserGroups] = useState([])
    const [userGroupSelected, setUserGroupSelected] = useState([])
    const [error, setError] = useState(false)

    useEffect(() => {
        if (!id) return
        getUserGroupsApi().then(res => {
            setUserGroups(res.data.records)
            const ug = res.data.records.find(ug => ug.id == 2) // 暂时设置
            setUserGroupSelected([ug,...userGroupSelected])
        })
        getRolesApi().then(data => {
            //@ts-ignore
            const roleOptions = data.filter(role => role.id !== 1)
                .map(role => ({ ...role, role_id: role.id }))
            setRoles(roleOptions);

            getUserRoles(id).then(userRoles => {
                // 默认设置 普通用户
                if (!userRoles.find(role => role.role_id === 2)) {
                    const roleByroles = roleOptions.find(role => role.role_id === 2)
                    userRoles.unshift({ ...roleByroles })
                }
                setSelected(userRoles)
            })
        })
        setError(false)
    }, [id])

    function compareDepartments(a, b) {
        return a.role_id === b.role_id
    }

    const handleSave = async () => {
        if (!selected.length) return setError(true)
        if(userGroupSelected.length === 0) return setError(true)
        const res = await captureAndAlertRequestErrorHoc(updateUserRoles(id, selected.map(item => item.role_id)))
        const resUg = await captureAndAlertRequestErrorHoc(updateUserGroups(id, userGroupSelected.map(ug => ug.name)))
        console.log('res :>> ', res);
        onChange()
    }
    return <Dialog open={id} onOpenChange={onClose}>
        <DialogContent className="sm:max-w-[625px]">
            <DialogHeader>
                <DialogTitle>{t('system.userGroupsSel')}</DialogTitle>
            </DialogHeader>
            <div className="">
                <MultiSelect
                    className="max-w-[600px]"
                    value={userGroupSelected.map(ug => {
                        return ug.id.toString()
                    })}
                    options={userGroups.map((ug) => {
                        return {
                            label: ug.groupName,
                            value: ug.id.toString()
                        }
                    })}
                    lockedValues={["2"]}
                    onChange={(values) => {
                        setUserGroupSelected(userGroups.filter(ug => {
                            return values.includes(ug.id.toString())
                        }))
                    }}
                >
                </MultiSelect>
            </div>
            <DialogHeader>
                <DialogTitle>{t('system.roleSelect')}</DialogTitle>
            </DialogHeader>
            <div className="">
                <MultiSelect
                    className="max-w-[600px]"
                    value={selected.map(item => {
                        return item.role_id.toString()
                    })}
                    options={roles.map((item) => {
                        return {
                            label: item.role_name,
                            value: item.role_id.toString()
                        }
                    })}
                    lockedValues={["2"]}
                    onChange={(values) => {
                        setSelected(roles.filter(item => {
                            return values.includes(item.role_id.toString())
                        }))
                    }}
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