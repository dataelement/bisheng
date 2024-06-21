import { DelIcon } from "@/components/bs-icons";
import { Button } from "@/components/bs-ui/button";
import MultiSelect from "@/components/bs-ui/select/multi";
import { getRolesByGroupApi, getUserGroupsApi } from "@/controllers/API/user";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

export default function UserRoleItem({ showDel, groupId, selectedRoles, onDelete, onChange }:
    { showDel: boolean, groupId: null | string, selectedRoles: any[], onDelete: any, onChange: any }) {
    const { t } = useTranslation()

    // 用户组
    const [groups, setGroups] = useState([])
    const [userGroupSelected, setUserGroupSelected] = useState(groupId ? [groupId] : [])
    useEffect(() => {
        // 用户组option列表
        getUserGroupsApi().then((res: any) => {
            setGroups(res.records.map((ug) => {
                return {
                    label: ug.group_name,
                    value: ug.id.toString()
                }
            }))
        })
    }, [])

    const handleSelectGroup = (values) => {
        onChange(values, [])
        setUserGroupSelected(values);
        setSelected([])
    }

    // 角色
    const [roles, setRoles] = useState<any[]>([])
    const [selected, setSelected] = useState(selectedRoles)
    useEffect(() => {
        // setSelected([])
        // 用户组option列表
        getRolesByGroupApi('', userGroupSelected).then((res: any) => {
            const roleOptions = res.map(role => {
                return {
                    label: role.role_name,
                    value: role.id.toString()
                }
            })
            setRoles(roleOptions);
        })
    }, [userGroupSelected])

    const handleSelectRole = (values) => {
        onChange(userGroupSelected, values)
        setSelected(values)
    }

    return <div className="flex gap-4">
        <MultiSelect
            className="max-w-[600px]"
            value={userGroupSelected}
            options={groups}
            placeholder={t('system.userGroupsSel')}
            onChange={handleSelectGroup}
        >
        </MultiSelect>
        <MultiSelect
            multiple
            className="max-w-[600px]"
            value={selected}
            options={roles}
            placeholder={t('system.roleSelect')}
            onChange={handleSelectRole}
        >
        </MultiSelect>
        {showDel && <Button variant="ghost" size="icon" onClick={onDelete}><DelIcon /></Button>}
    </div>
};
