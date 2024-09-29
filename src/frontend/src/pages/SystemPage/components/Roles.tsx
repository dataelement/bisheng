import { PlusIcon } from "@/components/bs-icons/plus";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Label } from "@/components/bs-ui/label";
import React, { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/bs-ui/button";
import { SearchInput } from "../../../components/bs-ui/input";
import {
    Table,
    TableBody,
    TableCell,
    TableFooter,
    TableHead,
    TableHeader,
    TableRow
} from "../../../components/bs-ui/table";
import { delRoleApi, getRolesByGroupApi, getUserGroupsApi } from "../../../controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { ROLE } from "../../../types/api/user";
import EditRole from "./EditRole";
import SelectSearch from "@/components/bs-ui/select/select"

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
    group: '',
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
            const data:any = await getRolesByGroupApi('', [state.group]);
            dispatch({ type: 'SET_ROLES', payload: data });
            allRolesRef.current = data;
        } catch (error) {
            console.error(error);
        }
    }, [state.group]);

    useEffect(() => {
        getUserGroupsApi().then((res:any) => {
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

    const [keyWord, setKeyWord] = useState('')
    const options = useMemo(() => {
        if (!keyWord || !state.group) return state.groups
        return state.groups.filter(group => group.label.toUpperCase().includes(keyWord.toUpperCase()) || group.value === state.group)
    }, [keyWord, state.group])

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
            <div className="h-[calc(100vh-128px)] overflow-y-auto pt-2 pb-10">
                <div className="flex justify-between">
                    <div className="flex items-center">
                        <Label>{t('system.currentGroup')}</Label>
                        <SelectSearch value={state.group} options={options} selectPlaceholder={t('system.defaultGroup')} 
                        inputPlaceholder={t('log.selectUserGroup')}
                        selectClass="w-[180px] inline-flex ml-2" contentClass="max-w-[180px] break-all"
                        onOpenChange={(open) => {
                            !open && setKeyWord('')
                        }}
                        onValueChange={(value) => {
                            dispatch({ type: 'SET_GROUP', payload: value})
                        }}
                        onChange={e => setKeyWord(e.target.value)}
                        />
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
                    <TableFooter>
                        {!state.roles.length && <TableRow>
                            <TableCell colSpan={5} className="text-center text-gray-400">{t('build.empty')}</TableCell>
                        </TableRow>}
                    </TableFooter>
                </Table>
            </div>
            <div className="bisheng-table-footer bg-background-login">
                <p className="desc">{t('system.roleList')}.</p>
            </div>
        </div>
    );
}
