import React, { useEffect, useRef, useState, useCallback, useReducer } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/bs-ui/button";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../../components/bs-ui/table";
import { delRoleApi, getRolesApi, getRolesByGroupApi, getUserGroupsApi } from "../../../controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { ROLE } from "../../../types/api/user";
import EditRole from "./EditRole";
import { SearchInput } from "../../../components/bs-ui/input";
import { PlusIcon } from "@/components/bs-icons/plus";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { Label } from "@/components/bs-ui/label";

interface State {
    roles: ROLE[];
    role: Partial<ROLE> | null;
    searchWord: string;
    group: string;
    groups: { label: string; value: string }[];
}

const initialState: State = {
    roles: [],
    role: null,
    searchWord: '',
    group: '1',
    groups: []
};

type Action =
    | { type: 'SET_ROLES'; payload: ROLE[] }
    | { type: 'SET_ROLE'; payload: Partial<ROLE> | null }
    | { type: 'SET_SEARCH_WORD'; payload: string }
    | { type: 'SET_GROUP'; payload: string }
    | { type: 'SET_GROUPS'; payload: any };

function reducer(state: State, action: Action): State {
    switch (action.type) {
        case 'SET_ROLES':
            return { ...state, roles: action.payload };
        case 'SET_ROLE':
            return { ...state, role: action.payload };
        case 'SET_SEARCH_WORD':
            return { ...state, searchWord: action.payload };
        case 'SET_GROUP':
            return { ...state, group: action.payload };
        case 'SET_GROUPS':
            return { ...state, groups: action.payload };
        default:
            return state;
    }
}

export default function Roles() {
    const { t } = useTranslation();
    const [state, dispatch] = useReducer(reducer, initialState);
    const allRolesRef = useRef<ROLE[]>([]);

    const loadData = useCallback(async () => {
        const inputDom = document.getElementById('role-input') as HTMLInputElement;
        if (inputDom) {
            inputDom.value = '';
        }
        try {
            const data = await getRolesByGroupApi('', state.group);
            dispatch({ type: 'SET_ROLES', payload: data });
            allRolesRef.current = data;
        } catch (error) {
            console.error(error);
        }
    }, [state.group]);

    useEffect(() => {
        getUserGroupsApi().then(res => {
            const groups = res.records.map(ug => ({ label: ug.group_name, value: ug.id }))
            // 获取最近修改用户组
            dispatch({ type: 'SET_GROUP', payload: groups[0].value });
            dispatch({ type: 'SET_GROUPS', payload: groups });
        })
    }, []);

    const handleDelete = async (item: ROLE) => {
        bsConfirm({
            desc: `${t('system.confirmText')} 【${item.role_name}】 ?`,
            okTxt: t('delete'),
            onOk: async (next) => {
                try {
                    await captureAndAlertRequestErrorHoc(delRoleApi(item.id));
                    await loadData();
                    next();
                } catch (error) {
                    console.error(error);
                }
            }
        });
    };

    const checkSameName = useCallback((name: string) => {
        return state.roles.find(_role => _role.role_name === name && state.role?.id !== _role.id);
    }, [state.roles, state.role]);

    const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
        const word = e.target.value;
        dispatch({ type: 'SET_SEARCH_WORD', payload: word });
        dispatch({ type: 'SET_ROLES', payload: allRolesRef.current.filter(item => item.role_name.toUpperCase().includes(word.toUpperCase())) });
    };
    useEffect(() => {
        loadData()
    }, [state.group])


    if (state.role) {
        return <EditRole
            id={state.role.id || -1}
            name={state.role.role_name || ''}
            groupId={state.group}
            onBeforeChange={checkSameName}
            onChange={() => {
                dispatch({ type: 'SET_ROLE', payload: null })
                loadData()
            }}
        />;
    }

    return (
        <div className="relative">
            <div className="h-[calc(100vh-136px)] overflow-y-auto pt-2 pb-10">
                <div className="flex justify-between">
                    <div>
                        <Label>当前用户组</Label>
                        <Select value={state.group} onValueChange={(value) => dispatch({ type: 'SET_GROUP', payload: value })}>
                            <SelectTrigger className="w-[180px] inline-flex ml-2">
                                <SelectValue placeholder="默认用户组" />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectGroup>
                                    {state.groups.map(el => (
                                        <SelectItem key={el.value} value={el.value}>{el.label}</SelectItem>
                                    ))}
                                </SelectGroup>
                            </SelectContent>
                        </Select>
                    </div>
                    <div className="flex gap-6 items-center justify-between">
                        <div className="w-[180px] relative">
                            <SearchInput id="role-input" placeholder={t('system.roleName')} onChange={handleSearch} />
                        </div>
                        <Button className="flex justify-around" onClick={() => dispatch({ type: 'SET_ROLE', payload: {} })}>
                            <PlusIcon className="text-primary" />
                            <span className="text-[#fff] mx-4">{t('create')}</span>
                        </Button>
                    </div>
                </div>
                <Table className="mb-10">
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[200px]">{t('system.roleName')}</TableHead>
                            <TableHead>{t('createTime')}</TableHead>
                            <TableHead className="text-right">{t('operations')}</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {state.roles.map(el => (
                            <TableRow key={el.id}>
                                <TableCell className="font-medium">{el.role_name}</TableCell>
                                <TableCell>{el.create_time.replace('T', ' ')}</TableCell>
                                <TableCell className="text-right">
                                    <Button variant="link" onClick={() => dispatch({ type: 'SET_ROLE', payload: el })} className="px-0 pl-6">{t('edit')}</Button>
                                    <Button variant="link" disabled={[1, 2].includes(el.id)} onClick={() => handleDelete(el)} className="text-red-500 px-0 pl-6">{t('delete')}</Button>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>
            <div className="bisheng-table-footer">
                <p className="desc">{t('system.roleList')}.</p>
            </div>
        </div>
    );
}
