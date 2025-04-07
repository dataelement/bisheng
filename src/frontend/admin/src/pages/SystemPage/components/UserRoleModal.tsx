import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { generateUUID } from "@/components/bs-ui/utils"
import { updateUserGroups, updateUserRoles } from "@/controllers/API/user"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { Plus } from "lucide-react"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { Button } from "../../../components/bs-ui/button"
import UserRoleItem from "./UserRoleItem"

export default function UserRoleModal({ user, onClose, onChange }) {
    const { t } = useTranslation()

    // 初始化数据
    const [roleItems, setRoleItems] = useState([])
    useEffect(() => {
        if (user) {
            const { groups, roles } = user
            const items = groups.map(item => {

                return {
                    key: generateUUID(8),
                    groupId: item.id,
                    roles: roles.filter(role => role.group_id === item.id)
                        .map(el => el.id.toString())
                }
            })
            setRoleItems(items)
        }
    }, [user])

    const handleChangeRoleItems = (index, groupId, roles) => {
        setRoleItems(items => items.map((el, i) => {
            return (index !== i) ? el : { groupId: groupId[0], roles }
        }))
    }

    const { message } = useToast()
    const handleSave = async () => {
        const map = {}
        const items = roleItems.filter(item => {
            if (map[item.groupId] || !item.groupId) return false
            map[item.groupId] = true
            return true
        })
        if (items.some(item => item.roles.length === 0)) return message({ title: t('prompt'), variant: 'warning', description: t('system.selectRole') })
        if (items.length === 0) return message({ title: t('prompt'), variant: 'warning', description: t('system.selectGroup') })
        captureAndAlertRequestErrorHoc(updateUserRoles(user.user_id, items.reduce((res, item) => [...res, ...item.roles], [])))
        captureAndAlertRequestErrorHoc(updateUserGroups(user.user_id, items.map(item => item.groupId)))
        onChange()
    }

    return <Dialog open={user} onOpenChange={(b) => { !b && setRoleItems([]); onClose(b) }}>
        <DialogContent className="sm:max-w-[625px]">
            <DialogHeader>
                <DialogTitle>{t('system.roleSelect')}</DialogTitle>
            </DialogHeader>
            <div className="max-h-[520px] py-1 overflow-y-auto flex flex-col gap-2">
                {
                    roleItems.map((item, i) => <UserRoleItem key={item.key}
                        groupId={item.groupId + ''}
                        selectedRoles={item.roles}
                        onChange={(g, r) => handleChangeRoleItems(i, g, r)}
                        showDel={roleItems.length > 1}
                        onDelete={() => setRoleItems(roleItems.filter((el, index) => index !== i))}
                    />)
                }
            </div>
            <Button variant="outline" size="icon" onClick={() =>
                setRoleItems(items => [...items, { key: Date.now(), groupId: '', roles: [] }])
            }><Plus className="size-5" /> </Button>
            <DialogFooter>
                <Button variant="outline" className="h-10 w-[120px] px-16" onClick={onClose}>{t('cancel')}</Button>
                <Button className="px-16 h-10 w-[120px]" onClick={handleSave}>{t('save')}</Button>
            </DialogFooter>
        </DialogContent>
    </Dialog>
};