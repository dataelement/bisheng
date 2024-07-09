import { Button } from "@/components/bs-ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Input } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { generateUUID } from "@/components/bs-ui/utils"
import { createUserApi } from "@/controllers/API/user"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { handleEncrypt, PWD_RULE } from "@/pages/LoginPage/utils"
import { copyText } from "@/utils"
import { EyeNoneIcon, EyeOpenIcon, PlusIcon } from "@radix-ui/react-icons"
import { useState } from "react"
import { useTranslation } from "react-i18next"
import UserRoleItem from "./UserRoleItem"

enum inputType {
    PASSWORD = 'password',
    TEXT = 'text'
}
const EyeIconStyle = 'absolute right-7 cursor-pointer'

export default function CreateUser({open, onClose, onSave}) {
    const { t } = useTranslation()
    const { message } = useToast()
    const initItems = { key:generateUUID(8), groupId:'', roles:[] }
    const initUser = { 
        user_name:'', 
        password:'',
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
        if(form.user_name === '') errors.push('用户名不可为空')
        if(form.user_name.length > 30) errors.push('用户名最长 30 个字符')
        if(!PWD_RULE.test(form.password)) errors.push('初始密码至少 8 个字符，必须包含大写字母、小写字母、数字和符号的组合')
        if(items.every(item => item.roles.length === 0)) errors.push('至少选择一个角色')
        if(errors.length > 0) return message({title:t('prompt'), description:errors, variant:'warning'})

        const encryptPwd = await handleEncrypt(form.password)
        const group_roles = items.map(item => ({
            group_id: Number(item.groupId), 
            role_ids: item.roles.map(r => Number(r))
        }))
        captureAndAlertRequestErrorHoc(createUserApi(form.user_name, encryptPwd, group_roles).then(() => {
            copyText(`用户名：${form.user_name}，初始密码：${form.password}`).then(() => 
                message({title:t('prompt'), description:'创建用户成功！已复制用户名和初始密码到剪贴板', variant:'success'}))
            onClose(false)
            setItems([initItems])
            setForm(initUser)
            onSave()
        }))
    }

    const handleChangeRoleItems = (index, groupId, roles) => {
        setItems(items => items.map((item, i) => {
            return i === index ? {...item, groupId:groupId[0], roles} : item
        }))
    }

    const [type, setType] = useState(inputType.PASSWORD)
    const handleShowPwd = () => {
        type === inputType.PASSWORD ? setType(inputType.TEXT) : setType(inputType.PASSWORD)
    }

    return <Dialog open={open} onOpenChange={b => onClose(b)}>
        <DialogContent className="sm:max-w-[625px]">
            <DialogHeader>
                <DialogTitle>创建用户</DialogTitle>
            </DialogHeader>
            <div className="flex flex-col gap-4 mb-4">
                <div>
                    <Label htmlFor="user" className="bisheng-label">{t('log.username')}</Label>
                    <Input id="user" value={form.user_name} onChange={(e) => setForm({...form, user_name:e.target.value})}
                    placeholder="后续使用此用户名进行登录，用户名不可修改" className="h-[50px]"/>
                </div>
                <div>
                    <Label htmlFor="password" className="bisheng-label">初始密码</Label>
                    <div className="flex place-items-center">
                        <Input type={type} id="password" value={form.password} placeholder="至少 8 个字符，必须包含大写字母、小写字母、数字和符号的组合"
                        onChange={(e) => setForm({...form, password:e.target.value})} className="h-[50px]"/>
                        {type === inputType.PASSWORD ? <EyeNoneIcon onClick={handleShowPwd} className={EyeIconStyle}/>
                        : <EyeOpenIcon onClick={handleShowPwd} className={EyeIconStyle}/>}
                    </div>
                </div>
                <div className="flex flex-col gap-2">
                    <Label className="bisheng-label">用户组/角色选择</Label>
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
                        setItems(items => [...items, { key:generateUUID(8), groupId:'', roles:[] }])
                        }>
                        <PlusIcon></PlusIcon>
                    </Button>
                </div>
            </div>
            <DialogFooter>
                <Button variant="outline" className="h-10 w-[120px] px-16" onClick={handleCancel}>{t('cancel')}</Button>
                <Button className="px-16 h-10 w-[120px]" onClick={handleConfirm}>{t('system.confirm')}</Button>
            </DialogFooter>
        </DialogContent>
    </Dialog>
}