// @ts-strict-ignore
import { Button, Select } from '@bisheng/ui';
import { Outlined } from "bisheng-icons";


import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { getRolesByGroupApi,getUserGroupsApi } from "@/controllers/API/user";
import { useEffect,useState } from "react";
import { useTranslation } from "react-i18next";

export default function UserRoleItem({ showDel, groupId, selectedRoles, onDelete, onChange }:
    { showDel: boolean, groupId: null | string, selectedRoles: any[], onDelete: any, onChange: any }) {
    const { t } = useTranslation()
    const selectLabels = useSelectLabels()

    // 用户组
    const [groups, setGroups] = useState([])
    const [userGroupSelected, setUserGroupSelected] = useState(groupId ? [groupId] : [])
    const loadGroups = () => {
        getUserGroupsApi().then((res: any) => {
            const groups = res.filter((ug) => ug.id != null && ug.id !== '').map((ug) => {
                return {
                    label: ug.group_name,
                    value: ug.id.toString()
                }
            })
            setGroups(groups)
        })
    }
    useEffect(() => {
        // 用户组option列表
        loadGroups()
    }, [])

    const handleSelectGroup = (value) => { //单选之后value要改成数组传出去
        onChange([value], [])
        setUserGroupSelected([value]);
        setSelected([])
    }

    // 角色
    const [roles, setRoles] = useState<any[]>([])
    const [selected, setSelected] = useState(selectedRoles)
    useEffect(() => {
        // setSelected([])
        // 用户组option列表
        getRolesByGroupApi('', userGroupSelected).then((res: any) => {
            const roleOptions = res.filter(role => role.id != null && role.id !== '').map(role => {
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

    return <div className="grid grid-cols-[44%,44%,5%] gap-4">
        <Select
            {...selectLabels}
            showSearch
            aria-label={t('system.userGroupsSel')}
            placeholder={t('system.userGroupsSel')}
            value={userGroupSelected[0] || null}
            options={groups}
            onChange={(value) => { if (value != null) handleSelectGroup(String(value)) }}
        />
        <Select
            {...selectLabels}
            multiple
            showSearch
            aria-label={t('system.roleSelect')}
            value={selected}
            options={roles}
            placeholder={t('system.roleSelect')}
            onChange={(values) => handleSelectRole(values.map(String))}
        />
        {showDel && <Button variant="text" size="medium" onClick={onDelete} color="default" iconOnly><Outlined.Delete size={16} /></Button>}
    </div>
};
