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
    form?: any;
    onUseChange?: (id: any, checked: boolean) => void;
    onManageChange?: (id: any, checked: boolean) => void;
    nameKey?: string;
    creatorKey?: string;
    useChecked?: (id: any) => boolean;
    manageChecked?: (id: any) => boolean;
    isPermissionTable?: boolean;
    role_id?: any;
}

const enum MenuType {
    BUILD = 'build',
    KNOWLEDGE = 'knowledge',
    MODEL = 'model',
    EVALUATION = 'evaluation'
}

const SearchPanne = ({ 
    groupId, 
    title, 
    type, 
    children, 
    role_id,
    form,
    onUseChange,
    onManageChange,
    nameKey,
    creatorKey,
    useChecked,
    manageChecked,
    isPermissionTable
  }: SearchPanneProps) => {
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
                return getGroupResourcesApi({ ...param, resource_type: 4 });
            case 'assistant':
                return getGroupResourcesApi({ ...param, resource_type: 3 });
            default:
                return getGroupResourcesApi({ ...param, resource_type: 1 });
        }
    })

    const renderPermissionTable = () => {
        if (!isPermissionTable) return children?.(data) || null;
        
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

const usePermissionSwitchLogic = (form, setForm) => {
    // 基础权限变更：处理ID类型转换+数组更新
    const switchDataChange = (id, key, checked) => {
        const numberFields = ['useLibs', 'manageLibs', 'useTools', 'manageTools'];
        const convertedId = numberFields.includes(key) ? Number(id) : String(id);
        
        const index = form[key].findIndex(el => el === convertedId);
        if (checked && index === -1) {
            form[key].push(convertedId);
        } else if (!checked && index !== -1) {
            form[key].splice(index, 1);
        }
        setForm({ ...form, [key]: [...form[key]] });
    };

    // 通用管理权限：勾选时自动联动勾选使用权限
    const switchManage = (id, keyManage, keyUse, checked) => {
        switchDataChange(id, keyManage, checked);
        if (checked) switchDataChange(id, keyUse, checked);
    };

    // 各权限类型专属开关（含“管理权限开启时，无法关闭使用权限”规则）
    return {
        switchDataChange,
        // 知识库
        switchLibManage: (id, checked) => switchManage(id, 'manageLibs', 'useLibs', checked),
        switchUseLib: (id, checked) => {
            if (!checked && form.manageLibs.includes(Number(id))) return;
            switchDataChange(id, 'useLibs', checked);
        },
        // 助手
        switchAssistantManage: (id, checked) => switchManage(id, 'manageAssistants', 'useAssistant', checked),
        switchUseAssistant: (id, checked) => {
            if (!checked && form.manageAssistants.includes(String(id))) return;
            switchDataChange(id, 'useAssistant', checked);
        },
        // 技能
        switchSkillManage: (id, checked) => switchManage(id, 'manageSkills', 'useSkills', checked),
        switchUseSkill: (id, checked) => {
            if (!checked && form.manageSkills.includes(String(id))) return;
            switchDataChange(id, 'useSkills', checked);
        },
        // 工作流
        switchFlowManage: (id, checked) => switchManage(id, 'manageFlows', 'useFlows', checked),
        switchUseFlow: (id, checked) => {
            if (!checked && form.manageFlows.includes(String(id))) return;
            switchDataChange(id, 'useFlows', checked);
        },
        // 工具
        switchToolManage: (id, checked) => switchManage(id, 'manageTools', 'useTools', checked),
        switchUseTool: (id, checked) => {
            if (!checked && form.manageTools.includes(Number(id))) return;
            switchDataChange(id, 'useTools', checked);
        },
        // 菜单
        switchMenu: (id, checked) => switchDataChange(id, 'useMenu', checked)
    };
};

/**
 * 权限初始化逻辑（处理详情接口返回数据）
 * @param resData - 接口返回的权限列表
 * @returns 格式化后的权限初始数据
 */
const initPermissionData = (resData) => {
    const initData = {
        useSkills: [], useLibs: [], useAssistant: [], useFlows: [], useTools: [], useMenu: [],
        manageLibs: [], manageAssistants: [], manageSkills: [], manageFlows: [], manageTools: []
    };

    resData.forEach(item => {
        switch (item.type) {
            case 1: initData.useLibs.push(Number(item.third_id)); break;
            case 2: initData.useSkills.push(String(item.third_id)); break;
            case 3: initData.manageLibs.push(Number(item.third_id)); break;
            case 4: initData.manageSkills.push(String(item.third_id)); break;
            case 5: initData.useAssistant.push(String(item.third_id)); break;
            case 6: initData.manageAssistants.push(String(item.third_id)); break;
            case 7: initData.useTools.push(Number(item.third_id)); break;
            case 8: initData.manageTools.push(Number(item.third_id)); break;
            case 9: initData.useFlows.push(String(item.third_id)); break;
            case 10: initData.manageFlows.push(String(item.third_id)); break;
            case 99: initData.useMenu.push(String(item.third_id)); break;
        }
    });

    return initData;
};

/**
 * SearchPanne配置生成（统一表格参数）
 * @param type - 权限类型（assistant/skill/flow/lib/tool）
 * @param form - 表单状态
 * @param switches - 开关函数集合
 * @param t - 国际化函数
 * @param groupId - 分组ID
 * @param roleId - 角色ID
 * @returns SearchPanne组件所需的完整配置
 */
const getSearchPanneConfig = (type, form, switches, t, groupId, roleId) => {
    const configMap = {
        assistant: {
            title: t('system.assistantAuthorization'),
            nameKey: 'system.assistantName',
            useChecked: (id) => form.useAssistant.includes(String(id)),
            manageChecked: (id) => form.manageAssistants.includes(String(id)),
            onUseChange: switches.switchUseAssistant,
            onManageChange: switches.switchAssistantManage
        },
        skill: {
            title: t('system.skillAuthorization'),
            nameKey: 'system.skillName',
            useChecked: (id) => form.useSkills.includes(String(id)),
            manageChecked: (id) => form.manageSkills.includes(String(id)),
            onUseChange: switches.switchUseSkill,
            onManageChange: switches.switchSkillManage
        },
        flow: {
            title: t('system.flowAuthorization'),
            nameKey: 'system.flowName',
            useChecked: (id) => form.useFlows.includes(String(id)),
            manageChecked: (id) => form.manageFlows.includes(String(id)),
            onUseChange: switches.switchUseFlow,
            onManageChange: switches.switchFlowManage
        },
        lib: {
            title: t('system.knowledgeAuthorization'),
            nameKey: 'system.libraryName',
            useChecked: (id) => form.useLibs.includes(Number(id)),
            manageChecked: (id) => form.manageLibs.includes(Number(id)),
            onUseChange: switches.switchUseLib,
            onManageChange: switches.switchLibManage
        },
        tool: {
            title: t('system.toolAuthorization'),
            nameKey: 'tools.toolName',
            useChecked: (id) => form.useTools.includes(Number(id)),
            manageChecked: (id) => form.manageTools.includes(Number(id)),
            onUseChange: switches.switchUseTool,
            onManageChange: switches.switchToolManage
        }
    };

    const config = configMap[type];
    return {
        title: config.title,
        groupId,
        role_id: roleId,
        type,
        isPermissionTable: true,
        nameKey: config.nameKey,
        creatorKey: 'system.creator',
        useChecked: config.useChecked,
        manageChecked: config.manageChecked,
        onUseChange: config.onUseChange,
        onManageChange: config.onManageChange,
        form
    };
};

//主组件：EditRole
export default function EditRole({ id, name, groupId, onChange, onBeforeChange }) {
    const { setErrorData, setSuccessData } = useContext(alertContext);
    const { t } = useTranslation();

    // 表单初始状态
    const [form, setForm] = useState({
        name,
        useSkills: [], useLibs: [], useAssistant: [], useFlows: [], useTools: [], useMenu: [MenuType.BUILD, MenuType.KNOWLEDGE],
        manageLibs: [], manageAssistants: [], manageSkills: [], manageFlows: [], manageTools: []
    });

    // 引入封装的开关逻辑
    const switches = usePermissionSwitchLogic(form, setForm);

    // 权限初始化（编辑场景：从接口获取数据）
    useEffect(() => {
        if (id !== -1) {
            getRolePermissionsApi(id).then(res => {
                const initData = initPermissionData(res.data);
                setForm(prev => ({ ...prev, ...initData }));
            });
        }
    }, [id]);

    // 角色ID处理（新增时用0，编辑时用真实ID）
    const roleId = id === -1 ? 0 : id;

    // 生成SearchPanne配置并渲染
    const panneTypes = ['assistant', 'skill', 'flow', 'lib', 'tool'];
    const renderPermissionPanne = (type) => {
        const config = getSearchPanneConfig(type, form, switches, t, groupId, roleId);
        return <SearchPanne key={type} {...config} />;
    };

    // 保存逻辑（保持原有功能不变）
    const handleSave = async () => {
        const sanitizeIds = (arr: any[]) => (arr || []).filter(Boolean);
        // 角色名校验
        if (!form.name.length || form.name.length > 50) {
            return setErrorData({
                title: t('prompt'),
                list: [t('system.roleNameRequired'), t('system.roleNamePrompt')],
            });
        }
        // 重名校验
        if (onBeforeChange(form.name)) {
            return setErrorData({
                title: t('prompt'),
                list: [t('system.roleNameExists')]
            });
        }

        // 新增/编辑角色基础信息
        let roleId = id;
        if (id === -1) {
            const res = await captureAndAlertRequestErrorHoc(createRole(groupId, form.name));
            roleId = res.id;
        } else {
            await captureAndAlertRequestErrorHoc(updateRoleNameApi(roleId, form.name));
        }

        // 批量更新角色权限
        await Promise.all([
            updateRolePermissionsApi({ role_id: roleId, access_id: form.useSkills as any, type: 2 as any }),
            updateRolePermissionsApi({ role_id: roleId, access_id: form.useLibs as any, type: 1 as any }),
            updateRolePermissionsApi({ role_id: roleId, access_id: form.useFlows as any, type: 9 as any }),
            updateRolePermissionsApi({ role_id: roleId, access_id: form.useTools as any, type: 7 as any }),
            updateRolePermissionsApi({ role_id: roleId, access_id: form.useAssistant as any, type: 5 as any }),
            updateRolePermissionsApi({ role_id: roleId, access_id: form.manageLibs as any, type: 3 as any }),
            updateRolePermissionsApi({ role_id: roleId, access_id: sanitizeIds(form.manageAssistants) as any, type: 6 as any }),
            updateRolePermissionsApi({ role_id: roleId, access_id: sanitizeIds(form.manageSkills) as any, type: 4 as any }),
            updateRolePermissionsApi({ role_id: roleId, access_id: sanitizeIds(form.manageFlows) as any, type: 10 as any }),
            updateRolePermissionsApi({ role_id: roleId, access_id: sanitizeIds(form.manageTools) as any, type: 8 as any }),
            updateRolePermissionsApi({ role_id: roleId, access_id: sanitizeIds(form.useMenu) as any, type: 99 as any }),
        ]);

        setSuccessData({ title: t('saved') });
        onChange(true);
    };

    return (
        <div className="max-w-[600px] mx-auto pt-4 h-[calc(100vh-128px)] overflow-y-auto pb-40 scrollbar-hide">
            {/* 角色名称输入 */}
            <div className="font-bold mt-4">
                <p className="text-xl mb-4">{t('system.roleName')}</p>
                <Input 
                    placeholder={t('system.roleName')} 
                    value={form.name} 
                    onChange={(e) => setForm(prev => ({ ...prev, name: e.target.value }))} 
                    maxLength={60} 
                    showCount
                />
            </div>

            {/* 菜单授权 */}
            <div className="mt-10">
                <div className="flex justify-between items-center relative">
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
                                    <Switch 
                                        checked={form.useMenu.includes(MenuType.BUILD)} 
                                        onCheckedChange={(bln) => switches.switchMenu(MenuType.BUILD, bln)} 
                                    />
                                </TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell className="font-medium">{t('menu.knowledge')}</TableCell>
                                <TableCell className="text-center">
                                    <Switch 
                                        checked={form.useMenu.includes(MenuType.KNOWLEDGE)} 
                                        onCheckedChange={(bln) => switches.switchMenu(MenuType.KNOWLEDGE, bln)} 
                                    />
                                </TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell className="font-medium">{t('menu.models')}</TableCell>
                                <TableCell className="text-center">
                                    <Switch 
                                        checked={form.useMenu.includes(MenuType.MODEL)} 
                                        onCheckedChange={(bln) => switches.switchMenu(MenuType.MODEL, bln)} 
                                    />
                                </TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell className="font-medium">{t('menu.evaluation')}</TableCell>
                                <TableCell className="text-center">
                                    <Switch 
                                        checked={form.useMenu.includes(MenuType.EVALUATION)} 
                                        onCheckedChange={(bln) => switches.switchMenu(MenuType.EVALUATION, bln)} 
                                    />
                                </TableCell>
                            </TableRow>
                        </TableBody>
                    </Table>
                </div>
            </div>

            {/* 各类型权限表格 */}
            <div className="mt-10 space-y-10">
                {panneTypes.map(type => renderPermissionPanne(type))}
            </div>

            {/* 保存/取消按钮 */}
            <div className="flex justify-center items-center absolute bottom-0 w-[600px] h-[8vh] gap-4 mt-[100px] bg-background-login z-10">
                <Button variant="outline" className="px-16" onClick={() => onChange()}>{t('cancel')}</Button>
                <Button className="px-16" onClick={handleSave}>{t('save')}</Button>
            </div>
        </div>
    );
}