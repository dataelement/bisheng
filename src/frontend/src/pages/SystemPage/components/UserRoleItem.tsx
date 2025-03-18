import { DelIcon } from "@/components/bs-icons";
import { Button } from "@/components/bs-ui/button";
import MultiSelect from "@/components/bs-ui/select/multi";
import SelectSearch from "@/components/bs-ui/select/select";
import { getRolesByGroupApi, getUserGroupsApi, getUserRolesApi } from "@/controllers/API/user";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export default function UserRoleItem({ isEdit = false, userId, showDel, groupId, selectedRoles, onDelete, onChange }:
    { showDel: boolean, groupId: null | string, selectedRoles: any[], onDelete: any, onChange: any }) {
    const { t } = useTranslation()
    console.log('selectedRoles :>> ', selectedRoles);
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
    const [selected, setSelected] = useState(selectedRoles.map(el => el.id.toString()))
    const [lockedValues, setLockedValues] = useState([])
    // const lockedValues = useMemo(() => selectedRoles.reduce((res, el) => {
    //     el.is_bind_all && res.push(el.id.toString())
    //     return res
    // }, []), [selectedRoles])
    console.log('selected :>> ', selected);
    const rolesRef = useRef([])
    useEffect(() => {
        // setSelected([])
        // 用户组option列表
        getUserRolesApi(userGroupSelected[0], userId).then((res: any) => {
            rolesRef.current = res
            const [options, selectedRoles] = res.reduce(([options, selectedRoles], role) => {
                const item = {
                    label: role.role_name,
                    value: role.id.toString()
                };
                (role.is_bind_all || role.is_belong_user) && selectedRoles.push(role)
                options.push(item)
                return [options, selectedRoles]
            }, [[], []])

            setRoles(options);
            if (!isEdit) {
                const selectedRoleKeys = selectedRoles.map(el => el.id.toString())
                setSelected(selectedRoleKeys)
                setLockedValues(selectedRoleKeys)
                onChange(userGroupSelected, selectedRoles)
            } else {
                const _lockedValues = selectedRoles.reduce((res, el) => el.is_bind_all || userGroupSelected[0] != el.group_id ? [...res, el.id.toString()] : res, [])
                setLockedValues(_lockedValues)
                if (selected.length === 0) {
                    setSelected(_lockedValues)
                    onChange(userGroupSelected, selectedRoles)
                }
            }
        })
    }, [userGroupSelected, isEdit])

    const handleSelectRole = (values) => {
        const _roles = values.map(val =>
            rolesRef.current.find(r => r.id == val)
        )

        onChange(userGroupSelected, _roles)

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
            lockedValues={lockedValues}
            placeholder={t('system.roleSelect')}
            onChange={handleSelectRole}
        >
        </MultiSelect>
        {showDel && <Button variant="ghost" size="icon" className="mt-2" onClick={onDelete}><DelIcon /></Button>}
    </div>
};
