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
import { createRole, getGroupResourcesApi, getRolePermissionsApi, updateRoleNameApi, updateRolePermissionsApi } from "../../../controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { useTable } from "../../../util/hook";
import { LoadingIcon } from "@/components/bs-icons/loading";

interface SearchPanneProps {
    groupId: any;
    title: string;
    type: string;
    children?: (data: any[]) => React.ReactNode;
    permissionProps?: {
        form: any;
        onUseChange: (id: any, checked: boolean) => void;
        onManageChange: (id: any, checked: boolean) => void;
        nameKey: string;
        creatorKey: string;
        useChecked: (id: any) => boolean;
        manageChecked: (id: any) => boolean;
    };
    role_id?: any;
}

const SearchPanne = ({ groupId, title, type, children, permissionProps, role_id }: SearchPanneProps) => {
    const { t } = useTranslation();
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

    // 如果传入了权限相关props，则渲染权限表格
    const renderPermissionTable = () => {
        if (!permissionProps) return children(data);
        
        const {  onUseChange, onManageChange, nameKey, creatorKey, useChecked, manageChecked } = permissionProps;
        
        return (
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead>{t(nameKey)}</TableHead>
                        <TableHead>{t(creatorKey)}</TableHead>
                        <TableHead className="text-center w-[175px]">{t('system.usePermission')}</TableHead>
                        <TableHead className="text-right w-[75px]">{t('system.managePermission')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {data.map((el: any) => (
                        <TableRow key={el.id}>
                            <TableCell className="font-medium">{el.name}</TableCell>
                            <TableCell>{el.user_name}</TableCell>
                            <TableCell className="text-center">
                                <Switch 
                                    checked={useChecked(el.id)} 
                                    onCheckedChange={(bln) => onUseChange(el.id, bln)} 
                                />
                            </TableCell>
                            <TableCell className="text-center">
                                <Switch 
                                    checked={manageChecked(el.id)} 
                                    onCheckedChange={(bln) => onManageChange(el.id, bln)} 
                                />
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        );
    };

    return <>
        <div className="mt-20 flex justify-between items-center relative">
            <p className="text-xl font-bold">{title}</p>
            <SearchInput onChange={(e) => search(e.target.value)}></SearchInput>
        </div>
        <div className="mt-4">
            {loading ?
                <div className="w-full h-[468px] flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                    <LoadingIcon />
                </div>
                : renderPermissionTable()}
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

    // 使用的权限
    const [form, setForm] = useState({
        name,
        useSkills: [],
        useLibs: [],
        useAssistant: [],
        useFlows: [],
        manageLibs: [],
        useTools: [],
        manageAssistants: [],
        manageSkills: [],
        manageFlows: [],
        manageTools: [],
        useMenu: [MenuType.BUILD, MenuType.KNOWLEDGE]
    })
    useEffect(() => {
        if (id !== -1) {
            // 获取详情，初始化选中数据
            getRolePermissionsApi(id).then(res => {
                const useSkills = [], useLibs = [], manageLibs = [], useAssistant = [], useFlows = [], useTools = [],
                    useMenu = [], manageAssistants = [], manageSkills = [], manageFlows = [], manageTools = []
                res.data.forEach(item => {
                    switch (item.type) {
                        case 1: useLibs.push(Number(item.third_id)); break;
                        case 2: useSkills.push(String(item.third_id)); break;
                        case 9: useFlows.push(String(item.third_id)); break;
                        case 3: manageLibs.push(Number(item.third_id)); break;
                        case 7: useTools.push(Number(item.third_id)); break;
                        case 5: useAssistant.push(String(item.third_id)); break;
                        case 6: manageAssistants.push(String(item.third_id)); break;
                        case 4: manageSkills.push(String(item.third_id)); break;
                        case 10: manageFlows.push(String(item.third_id)); break;
                        case 8: manageTools.push(Number(item.third_id)); break;
                        case 99: useMenu.push(String(item.third_id)); break;
                    }
                })
                setForm({ name, useSkills, useLibs, useAssistant, useFlows, manageLibs, useTools, useMenu, manageAssistants, manageSkills, manageFlows, manageTools })
            })
        }
    }, [id])

    const switchDataChange = (id, key, checked) => {
        // 根据字段类型决定ID转换方式
        const numberFields = ['useLibs', 'manageLibs', 'useTools', 'manageTools']
        const convertedId = numberFields.includes(key) ? Number(id) : String(id)
        
        const index = form[key].findIndex(el => el === convertedId)
        if (checked && index === -1) {
            form[key].push(convertedId)
        } else if (!checked && index !== -1) {
            form[key].splice(index, 1)
        }
        setForm({ ...form, [key]: [...form[key]] })
    }

    // 通用管理权限switch（联动使用权限）
    const switchManage = (id, keyManage, keyUse, checked) => {
        switchDataChange(id, keyManage, checked)
        if (checked) switchDataChange(id, keyUse, checked)
    }
    // 知识库管理权限switch
    const switchLibManage = (id, checked) => switchManage(id, 'manageLibs', 'useLibs', checked)
    const switchAssistantManage = (id, checked) => switchManage(id, 'manageAssistants', 'useAssistant', checked)
    const switchSkillManage = (id, checked) => switchManage(id, 'manageSkills', 'useSkills', checked)
    const switchFlowManage = (id, checked) => switchManage(id, 'manageFlows', 'useFlows', checked)
    const switchToolManage = (id, checked) => switchManage(id, 'manageTools', 'useTools', checked)
    // 知识库使用权限switch
    const switchUseLib = (id, checked) => {
        if (!checked && form.manageLibs.includes(Number(id))) return
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
        const sanitizeIds = (arr: any[]) => (arr || []).filter(Boolean);
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
            const res = await captureAndAlertRequestErrorHoc(createRole(groupId, form.name))
            roleId = res.id
        } else {
            // 更新基本信息
            captureAndAlertRequestErrorHoc(updateRoleNameApi(roleId, form.name))
        }
        // 更新角色权限
        const res = await Promise.all([
            updateRolePermissionsApi({ role_id: roleId, access_id: form.useSkills as any, type: 2 as any }),
            updateRolePermissionsApi({ role_id: roleId, access_id: form.useLibs as any, type: 1 as any }),
            updateRolePermissionsApi({ role_id: roleId, access_id: form.useFlows as any, type: 9 as any }),
            updateRolePermissionsApi({ role_id: roleId, access_id: form.useTools as any, type: 7 as any }),
            updateRolePermissionsApi({ role_id: roleId, access_id: form.useAssistant as any, type: 5 as any }),
            // 新增管理权限项
            updateRolePermissionsApi({ role_id: roleId, access_id: form.manageLibs as any, type: 3 as any }),
            updateRolePermissionsApi({ role_id: roleId, access_id: sanitizeIds(form.manageAssistants) as any, type: 6 as any }),
            updateRolePermissionsApi({ role_id: roleId, access_id: sanitizeIds(form.manageSkills) as any, type: 4 as any }),
            updateRolePermissionsApi({ role_id: roleId, access_id: sanitizeIds(form.manageFlows) as any, type: 10 as any }),
            updateRolePermissionsApi({ role_id: roleId, access_id: sanitizeIds(form.manageTools) as any, type: 8 as any }),
            updateRolePermissionsApi({ role_id: roleId, access_id: sanitizeIds(form.useMenu) as any, type: 99 as any }),
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
        {/* 菜单授权 */}
        <div>
            <div className="mt-20 flex justify-between items-center relative">
                <p className="text-xl font-bold">{t('system.menuAuthorization')}</p>
            </div>
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
        <div className="">
            <SearchPanne 
                title={t('system.assistantAuthorization')}
                groupId={groupId}
                role_id={roleId}
                type={'assistant'}
                permissionProps={{
                    form,
                    onUseChange: (id, checked) => switchDataChange(id, 'useAssistant', checked),
                    onManageChange: (id, checked) => switchAssistantManage(id, checked),
                    nameKey: 'system.assistantName',
                    creatorKey: 'system.creator',
                    useChecked: (id) => form.useAssistant.includes(String(id)),
                    manageChecked: (id) => form.manageAssistants.includes(String(id))
                }}
            />
        </div>
        {/* 技能 */}
        <div className="">
            <SearchPanne
                title={t('system.skillAuthorization')}
                groupId={groupId}
                role_id={roleId}
                type={'skill'}
                permissionProps={{
                    form,
                    onUseChange: (id, checked) => switchDataChange(id, 'useSkills', checked),
                    onManageChange: (id, checked) => switchSkillManage(id, checked),
                    nameKey: 'system.skillName',
                    creatorKey: 'system.creator',
                    useChecked: (id) => form.useSkills.includes(String(id)),
                    manageChecked: (id) => form.manageSkills.includes(String(id))
                }}
            />
        </div>
        {/* 工作流 */}
        <div className="">
            <SearchPanne
                title={'工作流授权'}
                groupId={groupId}
                role_id={roleId}
                type={'flow'}
                permissionProps={{
                    onUseChange: (id, checked) => switchDataChange(id, 'useFlows', checked),
                    onManageChange: (id, checked) => switchFlowManage(id, checked),
                    nameKey: 'system.flowName',
                    creatorKey: 'system.creator',
                    useChecked: (id) => form.useFlows.includes(String(id)),
                    manageChecked: (id) => form.manageFlows.includes(String(id))
                }}
            />
        </div>
        {/* 知识库 */}
        <div className="mb-20">
            <SearchPanne 
                title={t('system.knowledgeAuthorization')}
                groupId={groupId}
                role_id={roleId}
                type={'lib'}
                permissionProps={{
                    onUseChange: (id, checked) => switchUseLib(id, checked),
                    onManageChange: (id, checked) => switchLibManage(id, checked),
                    nameKey: 'lib.libraryName',
                    creatorKey: 'system.creator',
                    useChecked: (id) => form.useLibs.includes(Number(id)),
                    manageChecked: (id) => form.manageLibs.includes(Number(id))
                }}
            />
        </div>
        {/* 工具 */}
        <div className="">
            <SearchPanne
                title={t('system.toolAuthorization')}
                groupId={groupId}
                role_id={roleId}
                type={'tool'}
                permissionProps={{
                    onUseChange: (id, checked) => switchDataChange(id, 'useTools', checked),
                    onManageChange: (id, checked) => switchToolManage(id, checked),
                    nameKey: 'tools.toolName',
                    creatorKey: 'system.creator',
                    useChecked: (id) => form.useTools.includes(Number(id)),
                    manageChecked: (id) => form.manageTools.includes(Number(id))
                }}
            />
        </div>
        <div className="flex justify-center items-center absolute bottom-0 w-[600px] h-[8vh] gap-4 mt-[100px] bg-background-login z-10">
            <Button variant="outline" className="px-16" onClick={() => onChange()}>{t('cancel')}</Button>
            <Button className="px-16" onClick={handleSave}>{t('save')}</Button>
        </div>
    </div>
}