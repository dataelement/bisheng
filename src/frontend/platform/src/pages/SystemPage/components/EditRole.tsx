import { LoadingIcon } from "@/components/bs-icons/loading";
import { Tabs, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/bs-ui/button";
import { Input, SearchInput } from "../../../components/bs-ui/input";
import AutoPagination from "../../../components/bs-ui/pagination/autoPagination";
import { Switch } from "../../../components/bs-ui/switch";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../../components/bs-ui/table";
import { alertContext } from "../../../contexts/alertContext";
import { createRole, getGroupResourcesApi, getRoleDetailApi, getRolePermissionsApi, updateRoleNameApi, updateRolePermissionsApi } from "../../../controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { useTable } from "../../../util/hook";
import SelectUserByGroup from "./SelectUserByGroup";

const SearchPanne = ({ groupId, placeholder = '', title, type, children }) => {
    const { page, pageSize, data, total, loading, setPage, search } = useTable({ pageSize: 10 }, (params) => {
        const { page, pageSize, keyword } = params
        const param = {
            name: keyword,
            group_id: groupId,
            page_num: page,
            page_size: pageSize
        }

        switch (type) {
            case 'flow':
                return getGroupResourcesApi({ ...param, resource_type: 5 });
            case 'skill':
                return getGroupResourcesApi({ ...param, resource_type: 2 });
            case 'tool':
                // TODO 追加mcp工具
                return getGroupResourcesApi({ ...param, resource_type: 4 });
            case 'assistant':
                return getGroupResourcesApi({ ...param, resource_type: 3 });
            default:
                return getGroupResourcesApi({ ...param, resource_type: 1 });
        }
    })

    return <>
        <div className="mt-10 flex justify-between items-center relative">
            <p className="text-xl font-bold">{title}</p>
            <SearchInput placeholder={placeholder} onChange={(e) => search(e.target.value)}></SearchInput>
        </div>
        <div className="mt-4">
            {loading ?
                <div className="w-full h-[468px] flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                    <LoadingIcon />
                </div>
                : children(data)}
        </div>
        <AutoPagination className="m-0 mt-4 w-auto justify-end" page={page} pageSize={pageSize} total={total} onChange={setPage}></AutoPagination>
    </>
}


const enum MenuType {
    BUILD = 'build',
    KNOWLEDGE = 'knowledge',
    MODEL = 'model',
    EVALUATION = 'evaluation'
}
// -1 id表示新增
export default function EditRole({ id, name, groupId, onChange, onBeforeChange }) {
    const { setErrorData, setSuccessData } = useContext(alertContext);
    const { t } = useTranslation()
    const [tab, setTab] = useState('tab1')

    // 使用的权限
    const [form, setForm] = useState({
        name,
        useSkills: [],
        useLibs: [],
        useAssistant: [],
        useFlows: [],
        manageLibs: [],
        useTools: [],
        useMenu: [MenuType.BUILD, MenuType.KNOWLEDGE],
        bingAll: false,
        selectGroupKey: {},
        users: []
    })
    console.log('form :>> ', form);
    useEffect(() => {
        if (id !== -1) {
            // 获取权限详情，初始化选中数据
            getRolePermissionsApi(id).then(res => {
                const useSkills = [], useLibs = [], manageLibs = [], useAssistant = [], useFlows = [], useTools = [],
                    useMenu = []
                res.data.forEach(item => {
                    switch (item.type) {
                        case 1: useLibs.push(Number(item.third_id)); break;
                        case 2: useSkills.push(item.third_id); break;
                        case 9: useFlows.push(item.third_id); break;
                        case 3: manageLibs.push(Number(item.third_id)); break;
                        case 7: useTools.push(Number(item.third_id)); break;
                        case 5: useAssistant.push(item.third_id); break;
                        case 99: useMenu.push(item.third_id); break;
                    }
                })
                setForm(form => ({
                    ...form,
                    name, useSkills, useLibs, useAssistant, useFlows, manageLibs, useTools, useMenu
                }))
            })
            // 详情
            getRoleDetailApi(id).then(res => {
                setForm(form => ({ ...form, users: res.user_ids || [], bingAll: res.is_bind_all, selectGroupKey: res.extra || {} }))
            })
        }
    }, [id])

    const switchDataChange = (id, key, checked) => {
        const index = form[key].findIndex(el => el === id)
        checked && index === -1 && form[key].push(id)
        !checked && index !== -1 && form[key].splice(index, 1)
        setForm({ ...form, [key]: form[key] })
    }

    // 知识库管理权限switch
    const switchLibManage = (id, checked) => {
        switchDataChange(id, 'manageLibs', checked)
        if (checked) switchDataChange(id, 'useLibs', checked)
    }
    // 知识库使用权限switch
    const switchUseLib = (id, checked) => {
        if (!checked && form.manageLibs.includes(id)) return
        switchDataChange(id, 'useLibs', checked)
    }
    /**
     * 保存权限信息逻辑
     * 1.验证重名
     * 2.新增时先保存基本信息 创建 ID
     * 3.修改时先更新基本信息
     * 4.再批量 保存各个种类权限信息（助手、技能、知识库等）
     * @returns 
     */
    const handleSave = async () => {
        if (!form.name.length || form.name.length > 50) {
            return setErrorData({
                title: t('prompt'),
                list: [t('system.roleNameRequired'), t('system.roleNamePrompt')],
            });
        }
        if (onBeforeChange(form.name)) {
            return setErrorData({
                title: t('prompt'),
                list: [t('system.roleNameExists')]
            })
        }
        // 没有id时需要走创建流程，否则修改
        let roleId = id
        if (id === -1) {
            const res = await captureAndAlertRequestErrorHoc(createRole({
                role_name: form.name,
                group_id: groupId,
                is_bind_all: form.bingAll,
                user_ids: form.users.map(el => el.user_id)
            }))
            roleId = res.id
        } else {
            // 更新基本信息
            captureAndAlertRequestErrorHoc(updateRoleNameApi(roleId, {
                role_name: form.name,
                extra: "",
                is_bind_all: form.bingAll,
                user_ids: form.users.map(el => el.user_id)
            }))
        }
        // 更新角色权限
        const res = await Promise.all([
            updateRolePermissionsApi({ role_id: roleId, access_id: form.useSkills, type: 2 }),
            updateRolePermissionsApi({ role_id: roleId, access_id: form.useLibs, type: 1 }),
            updateRolePermissionsApi({ role_id: roleId, access_id: form.useFlows, type: 9 }),
            updateRolePermissionsApi({ role_id: roleId, access_id: form.manageLibs, type: 3 }),
            updateRolePermissionsApi({ role_id: roleId, access_id: form.useTools, type: 7 }),
            updateRolePermissionsApi({ role_id: roleId, access_id: form.useAssistant, type: 5 }),
            updateRolePermissionsApi({ role_id: roleId, access_id: form.useMenu, type: 99 }),
        ])

        console.log('form :>> ', form, res);
        setSuccessData({ title: t('saved') })
        onChange(true)
    }

    const roleId = id === -1 ? 0 : id

    return <div className="max-w-[600px] mx-auto pt-4 h-[calc(100vh-128px)] overflow-y-auto pb-40 scrollbar-hide">
        <div className="font-bold mt-4">
            <p className="text-xl mb-4">{t('system.roleName')}</p>
            <Input placeholder={t('system.roleName')} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} maxLength={60} showCount></Input>
        </div>
        <div className="font-bold mt-4">
            <p className="text-xl mb-4">人员范围</p>
            <div className="mb-4">
                <Switch checked={form.bingAll} onCheckedChange={(b) => setForm({ ...form, bingAll: b })} />
                <span className="ml-2 bisheng-label">对本组以及所有子用户组中的用户赋予角色</span>
            </div>
            {!form.bingAll && <SelectUserByGroup value={form.users} groupId={groupId} onChange={(users) => setForm({ ...form, users })} />}
        </div>
        <div>
            <div className="mt-20 flex justify-between items-center relative">
                <p className="text-xl font-bold">授权管理</p>
            </div>
            <Tabs value={tab} onValueChange={setTab} className="mt-4">
                <TabsList className="grid w-full grid-cols-6">
                    <TabsTrigger value="tab1">菜单</TabsTrigger>
                    <TabsTrigger value="tab2">助手</TabsTrigger>
                    <TabsTrigger value="tab3">技能</TabsTrigger>
                    <TabsTrigger value="tab4">工作流</TabsTrigger>
                    <TabsTrigger value="tab5">工具</TabsTrigger>
                    <TabsTrigger value="tab6">知识库</TabsTrigger>
                </TabsList>
            </Tabs>
        </div>
        {/* 菜单授权 */}
        <div className={tab === 'tab1' ? 'block' : 'hidden'}>
            {/* <div className="mt-20 flex justify-between items-center relative">
                <p className="text-xl font-bold">{t('system.menuAuthorization')}</p>
            </div> */}
            <div className="mt-4 w-full">
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>{t('system.primaryMenu')}</TableHead>
                            <TableHead className="text-right w-[75px]">{t('system.viewPermission')}</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        <TableRow>
                            <TableCell className="font-medium">{t('menu.skills')}</TableCell>
                            <TableCell className="text-center">
                                <Switch checked={form.useMenu.includes(MenuType.BUILD)} onCheckedChange={(bln) => switchDataChange(MenuType.BUILD, 'useMenu', bln)} />
                            </TableCell>
                        </TableRow>
                        <TableRow>
                            <TableCell className="font-medium">{t('menu.knowledge')}</TableCell>
                            <TableCell className="text-center">
                                <Switch checked={form.useMenu.includes(MenuType.KNOWLEDGE)} onCheckedChange={(bln) => switchDataChange(MenuType.KNOWLEDGE, 'useMenu', bln)} />
                            </TableCell>
                        </TableRow>
                        <TableRow>
                            <TableCell className="font-medium">{t('menu.models')}</TableCell>
                            <TableCell className="text-center">
                                <Switch checked={form.useMenu.includes(MenuType.MODEL)} onCheckedChange={(bln) => switchDataChange(MenuType.MODEL, 'useMenu', bln)} />
                            </TableCell>
                        </TableRow>
                        <TableRow>
                            <TableCell className="font-medium">{t('menu.evaluation')}</TableCell>
                            <TableCell className="text-center">
                                <Switch checked={form.useMenu.includes(MenuType.EVALUATION)} onCheckedChange={(bln) => switchDataChange(MenuType.EVALUATION, 'useMenu', bln)} />
                            </TableCell>
                        </TableRow>
                    </TableBody>
                </Table>
            </div>
        </div>
        {/* 助手 */}
        <div className={tab === 'tab2' ? 'block' : 'hidden'}>
            <SearchPanne
                // title={t('system.assistantAuthorization')} 
                placeholder={'助手名称'}
                groupId={groupId}
                role_id={roleId}
                type={'assistant'}>
                {(data) => (
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>{t('system.assistantName')}</TableHead>
                                <TableHead>{t('system.creator')}</TableHead>
                                <TableHead className="text-right w-[75px]">{t('system.usePermission')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {data.map((el) => (
                                <TableRow key={el.id}>
                                    <TableCell className="font-medium">{el.name}</TableCell>
                                    <TableCell>{el.user_name}</TableCell>
                                    <TableCell className="text-center">
                                        <Switch checked={form.useAssistant.includes(el.id)} onCheckedChange={(bln) => switchDataChange(el.id, 'useAssistant', bln)} />
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                )}
            </SearchPanne>
        </div>
        {/* 技能 */}
        <div className={tab === 'tab3' ? 'block' : 'hidden'}>
            <SearchPanne
                // title={t('system.skillAuthorization')}
                placeholder={'技能名称'}
                groupId={groupId}
                role_id={roleId}
                type={'skill'}>
                {(data) => (
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>{t('system.skillName')}</TableHead>
                                <TableHead>{t('system.creator')}</TableHead>
                                <TableHead className="text-right w-[75px]">{t('system.usePermission')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {data.map((el) => (
                                <TableRow key={el.id}>
                                    <TableCell className="font-medium">{el.name}</TableCell>
                                    <TableCell>{el.user_name}</TableCell>
                                    <TableCell className="text-center">
                                        <Switch checked={form.useSkills.includes(el.id)} onCheckedChange={(bln) => switchDataChange(el.id, 'useSkills', bln)} />
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                )}
            </SearchPanne>
        </div>
        {/* 工作流 */}
        <div className={tab === 'tab4' ? 'block' : 'hidden'}>
            <SearchPanne
                // title={'工作流授权'}
                placeholder={'工作流名称'}
                groupId={groupId}
                role_id={roleId}
                type={'flow'}>
                {(data) => (
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>工作流名称</TableHead>
                                <TableHead>{t('system.creator')}</TableHead>
                                <TableHead className="text-right w-[75px]">{t('system.usePermission')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {data.map((el) => (
                                <TableRow key={el.id}>
                                    <TableCell className="font-medium">{el.name}</TableCell>
                                    <TableCell>{el.user_name}</TableCell>
                                    <TableCell className="text-center">
                                        <Switch checked={form.useFlows.includes(el.id)} onCheckedChange={(bln) => switchDataChange(el.id, 'useFlows', bln)} />
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                )}
            </SearchPanne>
        </div>
        {/* 知识库 */}
        <div className={tab === 'tab6' ? 'block' : 'hidden'}>
            <SearchPanne
                // title={t('system.knowledgeAuthorization')}
                groupId={groupId}
                role_id={roleId}
                type={'lib'}>
                {(data) => (
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>{t('lib.libraryName')}</TableHead>
                                <TableHead>{t('system.creator')}</TableHead>
                                <TableHead>{t('system.usePermission')}</TableHead>
                                <TableHead className="text-right w-[75px]">{t('system.managePermission')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {data.map((el) => (
                                <TableRow key={el.id}>
                                    <TableCell className="font-medium">{el.name}</TableCell>
                                    <TableCell>{el.user_name}</TableCell>
                                    <TableCell className="text-left">
                                        <Switch checked={form.useLibs.includes(el.id)} onCheckedChange={(bln) => switchUseLib(el.id, bln)} />
                                    </TableCell>
                                    <TableCell className="text-center">
                                        <Switch checked={form.manageLibs.includes(el.id)} onCheckedChange={(bln) => switchLibManage(el.id, bln)} />
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                )}
            </SearchPanne>
        </div>
        {/* 工具 */}
        <div className={tab === 'tab5' ? 'block' : 'hidden'}>
            <SearchPanne
                // title={t('system.toolAuthorization')}
                placeholder={'工具名称'}
                groupId={groupId}
                role_id={roleId}
                type={'tool'}>
                {(data) => (
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>{t('tools.toolName')}</TableHead>
                                <TableHead>{t('system.creator')}</TableHead>
                                <TableHead className="text-right w-[75px]">{t('system.usePermission')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {data.map((el) => (
                                <TableRow key={el.id}>
                                    <TableCell className="font-medium">{el.name}</TableCell>
                                    <TableCell>{el.user_name}</TableCell>
                                    <TableCell className="text-center">
                                        <Switch
                                            checked={form.useTools.includes(el.id)}
                                            onCheckedChange={(bln) => switchDataChange(el.id, 'useTools', bln)}
                                        />
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                )}
            </SearchPanne>
        </div>
        <div className="flex justify-center items-center absolute bottom-0 w-[600px] h-[8vh] gap-4 mt-[100px] bg-background-login z-10">
            <Button variant="outline" className="px-16" onClick={() => onChange()}>{t('cancel')}</Button>
            <Button className="px-16" onClick={handleSave}>{t('save')}</Button>
        </div>
    </div>
}