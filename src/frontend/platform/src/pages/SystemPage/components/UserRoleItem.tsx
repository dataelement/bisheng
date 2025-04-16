import { DelIcon } from "@/components/bs-icons";
import { Button } from "@/components/bs-ui/button";
import MultiSelect from "@/components/bs-ui/select/multi";
import { getRolesByGroupApi, getUserGroupsApi } from "@/controllers/API/user";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import SelectSearch from "@/components/bs-ui/select/select"

export default function UserRoleItem({ showDel, groupId, selectedRoles, onDelete, onChange }:
    { showDel: boolean, groupId: null | string, selectedRoles: any[], onDelete: any, onChange: any }) {
    const { t } = useTranslation()

    // 用户组
    const [groups, setGroups] = useState([])
    const groupsRef = useRef([])
    const [userGroupSelected, setUserGroupSelected] = useState(groupId ? [groupId] : [])
    const loadGroups = () => {
        getUserGroupsApi().then((res: any) => {
            const groups = res.records.map((ug) => {
                return {
                    label: ug.group_name,
                    value: ug.id.toString()
                }
            })
            setGroups(groups)
            groupsRef.current = groups
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
    const handleSearch = (e) => {
        const keyword = e.target.value
        const newGroups = groupsRef.current.filter(g => g.label.toUpperCase().includes(keyword.toUpperCase()) 
        || g.value === userGroupSelected[0])
        setGroups(newGroups)
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

    return <div className="grid grid-cols-[44%,44%,5%] gap-4">
        <SelectSearch contentClass="max-w-[260px] break-all" selectPlaceholder={t('system.userGroupsSel')}
            selectClass="h-[50px]"
            value={userGroupSelected[0]}
            options={groups}
            onOpenChange={() => setGroups(groupsRef.current)}
            onValueChange={handleSelectGroup}
            onChange={handleSearch}
        />
        <MultiSelect
            multiple
            contentClassName="max-w-[260px] break-all"
            value={selected}
            options={roles}
            placeholder={t('system.roleSelect')}
            onChange={handleSelectRole}
        >
        </MultiSelect>
        {showDel && <Button variant="ghost" size="icon" className="mt-2" onClick={onDelete}><DelIcon /></Button>}
    </div>
};
