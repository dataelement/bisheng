import { Listbox } from "@headlessui/react"
import MultiSelect from "@/components/bs-ui/select/multi"
import { CheckIcon, ChevronsUpDown } from "lucide-react"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { Button } from "../../../components/bs-ui/button"
import { getRolesApi, getUserRoles, updateUserRoles } from "../../../controllers/API/user"
import { ROLE } from "../../../types/api/user"
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"

export default function UserRoleModal({ id, onClose, onChange }) {
    const { t } = useTranslation()

    const [roles, setRoles] = useState<ROLE[]>([])
    const [selected, setSelected] = useState([])
    const [error, setError] = useState(false)

    useEffect(() => {
        if (!id) return
        getRolesApi().then(data => {
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
            // console.log(roles)
        })
        setError(false)
    }, [id])

    function compareDepartments(a, b) {
        return a.role_id === b.role_id
    }

    const handleSave = async () => {
        if (!selected.length) return setError(true)
        const res = await captureAndAlertRequestErrorHoc(updateUserRoles(id, selected.map(item => item.role_id)))
        console.log('res :>> ', res);
        onChange()
    }
    return <Dialog open={id} onOpenChange={onClose}>
        <DialogContent className="sm:max-w-[625px]">
            <DialogHeader>
                <DialogTitle>{t('system.roleSelect')}</DialogTitle>
            </DialogHeader>
            <div className="">
                <MultiSelect
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