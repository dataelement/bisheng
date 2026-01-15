import { useCallback, useContext, useEffect, useState } from "react";
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
import {
  createRole,
  getGroupResourcesApi,
  getRolePermissionsApi,
  updateRoleNameApi,
  updateRolePermissionsApi
} from "../../../controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { useTable } from "../../../util/hook";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { locationContext } from "@/contexts/locationContext";
import { message } from "@/components/bs-ui/toast/use-toast";

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
  showTab?: boolean;
}

const enum MenuType {
  BUILD = 'build',
  KNOWLEDGE = 'knowledge',
  MODEL = 'model',
  EVALUATION = 'evaluation',
  BOARD = 'board',

  FRONTEND = 'frontend',
  BACKEND = 'backend',
  CREATE_DASHBOARD = 'create_dashboard',
}


const MENU_LIST = [
  { id: MenuType.BOARD, name: 'menu.board', user_name: '-' },
  { id: MenuType.BUILD, name: 'menu.skills', user_name: '-' },
  { id: MenuType.KNOWLEDGE, name: 'menu.knowledge', user_name: '-' },
  { id: MenuType.MODEL, name: 'menu.models', user_name: '-' },
  { id: MenuType.EVALUATION, name: 'menu.evaluation', user_name: '-' },
];

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
  isPermissionTable,
  placeholderKey,
  allowCreateBoard,
  onAllowCreateBoardChange,
}: SearchPanneProps) => {
  const { t } = useTranslation();
  const { appConfig } = useContext(locationContext)

  const { page, pageSize, data, total, loading, setPage, search } = useTable(
    { pageSize: 10 },
    (params) => {
      if (type === 'menu') {
        return Promise.resolve({
          data: MENU_LIST,
          total: MENU_LIST.length
        });
      }

      const { page, pageSize, keyword } = params;
      const param = {
        name: keyword,
        group_id: groupId,
        page_num: page,
        page_size: pageSize
      };

      switch (type) {
        case 'flow':
          return getGroupResourcesApi({ ...param, resource_type: 5 });
        case 'skill':
          return getGroupResourcesApi({ ...param, resource_type: 2 });
        case 'tool':
          return getGroupResourcesApi({ ...param, resource_type: 4 });
        case 'assistant':
          return getGroupResourcesApi({ ...param, resource_type: 3 });
        case 'board':
          return getGroupResourcesApi({ ...param, resource_type: 6 });
        default:
          return getGroupResourcesApi({ ...param, resource_type: 1 });
      }
    }
  );

  const renderPermissionTable = () => {
    if (!isPermissionTable) return children?.(data) || null;
    const isMenuOrBoard = type === 'menu' || type === 'board';
    return (
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t(nameKey)}</TableHead>
            {type === 'board' && <TableHead>{t('system.creator')}</TableHead>}
            <TableHead className="text-center w-[175px]">
              {!isMenuOrBoard ? t('system.usePermission') : t('system.viewPermission')}
            </TableHead>
            {isPermissionTable && type !== 'menu' && !appConfig.isPro && (
              <TableHead className="text-right w-[75px]">{t('system.managePermission')}</TableHead>
            )}
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.map((el: any) => (
            <TableRow key={el.id}>
              <TableCell className="font-medium">{t(el.name)}</TableCell>
              {type === 'board' && <TableCell>{el.user_name}</TableCell>}
              <TableCell className="text-center">
                <Switch
                  checked={useChecked(el.id)}
                  onCheckedChange={(bln) => onUseChange(el.id, bln)}
                />
              </TableCell>
              {type !== 'menu' && !appConfig.isPro && (
                <TableCell className="text-center">
                  <Switch
                    checked={manageChecked(el.id)}
                    onCheckedChange={(bln) => onManageChange(el.id, bln)}
                  />
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    );
  };

  return <>
    <div className="mt-6 flex flex-col items-start relative gap-3">
      {type === 'board' && !appConfig.isPro && (
        <div className="flex flex-col gap-4 w-full">
          {/* 允许创建看板开关 */}
          <div className="flex items-center gap-2">
            <Switch
              checked={!!allowCreateBoard}
              disabled={!appConfig.isPro}
              onCheckedChange={(val) => onAllowCreateBoardChange?.(val)}
            />
            <div className="flex flex-col items-start gap-1">
              <span className="font-medium">{t('system.allowCreateBoard')}</span>
              <p className="text-sm text-muted-foreground ml-0">
                {t('system.allowCreateBoardDesc')}
              </p>
            </div>
          </div>
        </div>
      )}


      {type !== 'menu' && <SearchInput
        onChange={(e) => search(e.target.value)}
        placeholder={placeholderKey ? t(placeholderKey) : ''}
        className="mt-0"
      />}
    </div>
    <div className="mt-4">
      {loading ?
        <div className="w-full h-[468px] flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
          <LoadingIcon />
        </div>
        : renderPermissionTable()}
    </div>
    {type !== 'menu' && <AutoPagination className="m-0 mt-4 w-auto justify-end" page={page} pageSize={pageSize} total={total} onChange={setPage} />}
  </>
};

const usePermissionSwitchLogic = (form, setForm) => {
  const switchDataChange = (id, key, checked) => {
    setForm(prev => {
      const array = prev[key] || [];
      const numberFields = ['useLibs', 'manageLibs', 'useTools', 'manageTools', 'useBoards', 'manageBoards'];
      const convertedId = numberFields.includes(key) ? Number(id) : String(id);
      const index = array.findIndex(el => el === convertedId);

      let newArray;
      if (checked && index === -1) {
        newArray = [...array, convertedId];
      } else if (!checked && index !== -1) {
        newArray = [...array];
        newArray.splice(index, 1);
      } else {
        newArray = array;
      }

      return { ...prev, [key]: newArray };
    });
  };


  const switchManage = (id, keyManage, keyUse, checked) => {
    switchDataChange(id, keyManage, checked);
    if (checked) switchDataChange(id, keyUse, checked);
  };

  return {
    switchDataChange,
    switchLibManage: (id, checked) => switchManage(id, 'manageLibs', 'useLibs', checked),
    switchUseLib: (id, checked) => {
      if (!checked && (form.manageLibs || []).includes(Number(id))) return;
      switchDataChange(id, 'useLibs', checked);
    },
    switchAssistantManage: (id, checked) => switchManage(id, 'manageAssistants', 'useAssistant', checked),
    switchUseAssistant: (id, checked) => {
      if (!checked && (form.manageAssistants || []).includes(String(id))) return;
      switchDataChange(id, 'useAssistant', checked);
    },
    switchSkillManage: (id, checked) => switchManage(id, 'manageSkills', 'useSkills', checked),
    switchUseSkill: (id, checked) => {
      if (!checked && (form.manageSkills || []).includes(String(id))) return;
      switchDataChange(id, 'useSkills', checked);
    },
    switchFlowManage: (id, checked) => switchManage(id, 'manageFlows', 'useFlows', checked),
    switchUseFlow: (id, checked) => {
      if (!checked && (form.manageFlows || []).includes(String(id))) return;
      switchDataChange(id, 'useFlows', checked);
    },
    switchToolManage: (id, checked) => switchManage(id, 'manageTools', 'useTools', checked),
    switchUseTool: (id, checked) => {
      if (!checked && (form.manageTools || []).includes(Number(id))) return;
      switchDataChange(id, 'useTools', checked);
    },
    switchMenu: (id, checked) => switchDataChange(id, 'useMenu', checked),
    switchBoardManage: (id, checked) => switchManage(id, 'manageBoards', 'useBoards', checked),
    switchUseBoard: (id, checked) => {
      const numId = Number(id);
      if (!checked && (form.manageBoards || []).includes(numId)) return;
      switchDataChange(numId, 'useBoards', checked);
    }
  };
};

const initPermissionData = (resData) => {
  const initData = {
    useSkills: [], useLibs: [], useAssistant: [], useFlows: [], useTools: [], useMenu: [],
    manageLibs: [], manageAssistants: [], manageSkills: [], manageFlows: [], manageTools: [],
    useBoards: [], manageBoards: []
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
      case 11:
        initData.useBoards.push(Number(item.third_id));
        break;
      case 12:
        initData.manageBoards.push(Number(item.third_id));
        break;

      case 99: initData.useMenu.push(String(item.third_id)); break;
    }
  });
  return initData;
};

const getSearchPanneConfig = (type, form, switches, t, groupId, roleId, handleAllowCreateBoardChange) => {
  const placeholderMap = {
    assistant: 'system.searchAssistant',
    skill: 'system.searchSkill',
    flow: 'system.searchFlow',
    knowledge: 'system.searchKnowledge',
    tool: 'system.searchTool',
    menu: '',
    board: 'system.searchBoard',
  };

  const configMap = {
    assistant: { title: t('system.assistantAuthorization'), nameKey: 'system.assistantName', useChecked: (id) => form.useAssistant.includes(String(id)), manageChecked: (id) => form.manageAssistants.includes(String(id)), onUseChange: switches.switchUseAssistant, onManageChange: switches.switchAssistantManage, placeholderKey: placeholderMap.assistant },
    skill: { title: t('system.skillAuthorization'), nameKey: 'system.skillName', useChecked: (id) => form.useSkills.includes(String(id)), manageChecked: (id) => form.manageSkills.includes(String(id)), onUseChange: switches.switchUseSkill, onManageChange: switches.switchSkillManage, placeholderKey: placeholderMap.skill },
    flow: { title: t('system.flowAuthorization'), nameKey: 'system.flowName', useChecked: (id) => form.useFlows.includes(String(id)), manageChecked: (id) => form.manageFlows.includes(String(id)), onUseChange: switches.switchUseFlow, onManageChange: switches.switchFlowManage, placeholderKey: placeholderMap.flow },
    knowledge: { title: t('system.knowledgeAuthorization'), nameKey: 'system.libraryName', useChecked: (id) => form.useLibs.includes(Number(id)), manageChecked: (id) => form.manageLibs.includes(Number(id)), onUseChange: switches.switchUseLib, onManageChange: switches.switchLibManage, placeholderKey: placeholderMap.knowledge },
    tool: { title: t('system.toolAuthorization'), nameKey: 'tools.toolName', useChecked: (id) => form.useTools.includes(Number(id)), manageChecked: (id) => form.manageTools.includes(Number(id)), onUseChange: switches.switchUseTool, onManageChange: switches.switchToolManage, placeholderKey: placeholderMap.tool },
    menu: { title: t('system.menuAuthorization'), nameKey: 'system.primaryMenu', useChecked: (id) => form.useMenu.includes(String(id)), manageChecked: () => false, onUseChange: switches.switchMenu, onManageChange: () => { }, placeholderKey: placeholderMap.menu },
    board: {
      title: t('system.boardAuthorization'),
      nameKey: 'system.boardName',
      useChecked: (id) => form.useBoards?.includes(Number(id)),
      manageChecked: (id) => form.manageBoards?.includes(Number(id)),
      onUseChange: switches.switchUseBoard,
      onManageChange: switches.switchBoardManage,
      placeholderKey: placeholderMap.board,
      allowCreateBoard: form.allowCreateBoard,
      onAllowCreateBoardChange: handleAllowCreateBoardChange,
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
    form,
    placeholderKey: config.placeholderKey,
    allowCreateBoard: config.allowCreateBoard,
    onAllowCreateBoardChange: config.onAllowCreateBoardChange,
  };
};

export default function EditRole({ id, name, groupId, onChange, onBeforeChange }) {
  const { setErrorData, setSuccessData } = useContext(alertContext);
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<'menu' | 'assistant' | 'skill' | 'flow' | 'knowledge' | 'tool' | 'board'>('menu');

  const [form, setForm] = useState({
    name,
    useSkills: [], useLibs: [], useAssistant: [], useFlows: [], useTools: [], useMenu: [MenuType.BUILD, MenuType.KNOWLEDGE],
    manageLibs: [], manageAssistants: [], manageSkills: [], manageFlows: [], manageTools: [], useBoards: [], manageBoards: [],
    allowCreateBoard: false,
  });

  const [spacePermissions, setSpacePermissions] = useState({
    workspace: true,
    admin: true,
  });

  const handleAllowCreateBoardChange = (checked: boolean) => {
    setForm(prev => {
      const menuSet = new Set(prev.useMenu);

      checked
        ? menuSet.add(MenuType.CREATE_DASHBOARD)
        : menuSet.delete(MenuType.CREATE_DASHBOARD);

      return {
        ...prev,
        allowCreateBoard: checked,
        useMenu: Array.from(menuSet),
      };
    });
    if (!checked && activeTab === 'board') {
      setActiveTab('menu');
    }
  };


  const switches = usePermissionSwitchLogic(form, setForm);
  useEffect(() => {
    if (id !== -1) {
      getRolePermissionsApi(id).then(res => {
        const initData = initPermissionData(res.data);

        const hasAdminSpace = initData.useMenu.includes(MenuType.BACKEND);
        const hasCreateBoard = initData.useMenu.includes(MenuType.CREATE_DASHBOARD);

        setForm(prev => ({
          ...prev,
          ...initData,
          allowCreateBoard: hasCreateBoard,
        }));

        setSpacePermissions({
          workspace: initData.useMenu.includes(MenuType.FRONTEND),
          admin: hasAdminSpace,
        });

        if (!hasAdminSpace) {
          setActiveTab('assistant');
        } else {
          setActiveTab('menu');
        }
      });
    }
  }, [id]);


  const roleId = id === -1 ? 0 : id;

  const getPermissionTabs = useCallback(() => {
    const tabs = ['assistant', 'flow', 'skill', 'knowledge', 'tool'];

    if (spacePermissions.admin) {
      tabs.unshift('menu');
      const hasBoardMenuPermission = form.useMenu.includes(MenuType.BOARD);
      const canShowBoardTab = hasBoardMenuPermission;
      if (canShowBoardTab) {
        tabs.push('board');
      }
    }

    return tabs;
  }, [spacePermissions.admin, form.allowCreateBoard, form.useMenu]);

  const renderPermissionPanne = (type) => {
    const config = getSearchPanneConfig(type, form, switches, t, groupId, roleId, handleAllowCreateBoardChange);
    return <SearchPanne key={type} {...config} />;
  };
  const syncSpaceToMenu = (next: { workspace: boolean; admin: boolean }) => {
    setForm(prev => {
      const menuSet = new Set(prev.useMenu);

      next.workspace
        ? menuSet.add(MenuType.FRONTEND)
        : menuSet.delete(MenuType.FRONTEND);

      next.admin
        ? menuSet.add(MenuType.BACKEND)
        : menuSet.delete(MenuType.BACKEND);

      return {
        ...prev,
        useMenu: Array.from(menuSet),
      };
    });
  };

  const handleSpacePermissionChange = (
    key: 'workspace' | 'admin',
    checked: boolean
  ) => {
    const next = {
      ...spacePermissions,
      [key]: checked,
    };

    if (!next.workspace && !next.admin) {
      setErrorData({
        title: t('prompt'),
        list: [t('system.atLeastOneSpaceRequired')],
      });
      return;
    }

    setSpacePermissions(next);
    syncSpaceToMenu(next);
    if (key === 'admin' && !checked && (activeTab === 'menu' || activeTab === 'board')) {
      setActiveTab('assistant');
    }
  };

  const handleSave = async () => {

    const sanitizeIds = (arr: any[]) => (arr || []).filter(Boolean);
    if (!form.name.length || form.name.length > 50) {
      return setErrorData({ title: t('prompt'), list: [t('system.roleNameRequired'), t('system.roleNamePrompt')] });
    }
    if (onBeforeChange(form.name)) {
      return setErrorData({ title: t('prompt'), list: [t('system.roleNameExists')] });
    }
    const menuSet = new Set(form.useMenu);
    // 检查是否至少有一个空间权限被选中
    if (!spacePermissions.workspace && !spacePermissions.admin) {
      return setErrorData({ title: t('prompt'), list: [t('system.atLeastOneSpaceRequired')] });
    }
    if (spacePermissions.workspace) menuSet.add(MenuType.FRONTEND);
    else menuSet.delete(MenuType.FRONTEND);

    if (spacePermissions.admin) menuSet.add(MenuType.BACKEND);
    else menuSet.delete(MenuType.BACKEND);

    if (form.allowCreateBoard) menuSet.add(MenuType.CREATE_DASHBOARD);
    else menuSet.delete(MenuType.CREATE_DASHBOARD);
    let roleIdLocal = id;
    if (id === -1) {
      const res = await captureAndAlertRequestErrorHoc(createRole(groupId, form.name));
      roleIdLocal = res.id;
    } else {
      await captureAndAlertRequestErrorHoc(updateRoleNameApi(roleIdLocal, form.name));
    }

    const menuPermissionsToSave = Array.from(menuSet);

    await Promise.all([
      updateRolePermissionsApi({ role_id: roleIdLocal, access_id: form.useSkills as any, type: 2 as any }),
      updateRolePermissionsApi({ role_id: roleIdLocal, access_id: form.useLibs as any, type: 1 as any }),
      updateRolePermissionsApi({ role_id: roleIdLocal, access_id: form.useFlows as any, type: 9 as any }),
      updateRolePermissionsApi({ role_id: roleIdLocal, access_id: form.useTools as any, type: 7 as any }),
      updateRolePermissionsApi({ role_id: roleIdLocal, access_id: form.useAssistant as any, type: 5 as any }),
      updateRolePermissionsApi({ role_id: roleIdLocal, access_id: form.manageLibs as any, type: 3 as any }),
      updateRolePermissionsApi({ role_id: roleIdLocal, access_id: sanitizeIds(form.manageAssistants) as any, type: 6 as any }),
      updateRolePermissionsApi({ role_id: roleIdLocal, access_id: sanitizeIds(form.manageSkills) as any, type: 4 as any }),
      updateRolePermissionsApi({ role_id: roleIdLocal, access_id: sanitizeIds(form.manageFlows) as any, type: 10 as any }),
      updateRolePermissionsApi({ role_id: roleIdLocal, access_id: sanitizeIds(form.manageTools) as any, type: 8 as any }),
      updateRolePermissionsApi({ role_id: roleIdLocal, access_id: sanitizeIds(menuPermissionsToSave) as any, type: 99 as any }),
      updateRolePermissionsApi({ role_id: roleIdLocal, access_id: sanitizeIds(form.useBoards) as any, type: 11 as any }),
      updateRolePermissionsApi({ role_id: roleIdLocal, access_id: sanitizeIds(form.manageBoards) as any, type: 12 as any }),

    ]);
    message({
      variant: 'success',
      description: t('saved')
    });
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

      {/* 空间授权 - 完全独立于菜单权限 */}
      <div className="mt-10">
        <div className="items-center relative">
          <p className="text-xl font-bold">{t('system.spaceAuthorization')}</p>
          <p className="text-sm text-[#8F959E]">
            {t('system.spaceAuthorizationDesc')}
          </p>
        </div>

        <div className="w-full">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('system.spaceName')}</TableHead>
                <TableHead className="text-right w-[75px]">
                  {t('system.viewPermission')}
                </TableHead>
              </TableRow>
            </TableHeader>

            <TableBody>
              <TableRow>
                <TableCell className="font-medium">
                  {t('system.workspace')}
                </TableCell>
                <TableCell className="text-center">
                  <Switch
                    checked={spacePermissions.workspace}
                    onCheckedChange={(bln) =>
                      handleSpacePermissionChange('workspace', bln)
                    }
                  />
                </TableCell>
              </TableRow>

              <TableRow>
                <TableCell className="font-medium">
                  {t('system.adminSpace')}
                </TableCell>
                <TableCell className="text-center">
                  <Switch
                    checked={spacePermissions.admin}
                    onCheckedChange={(bln) =>
                      handleSpacePermissionChange('admin', bln)
                    }
                  />
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </div>


      {/* 权限 Tabs */}
      <div className="flex gap-6 border-b mt-10">
        {getPermissionTabs().map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`pb-2 text-sm ${activeTab === tab ? 'border-b-2 border-primary font-semibold' : 'text-muted-foreground'}`}
          >
            {t(`system.${tab}Authorization`)}
          </button>
        ))}
      </div>

      {/* 当前 Tab 内容 */}
      <div className="">{renderPermissionPanne(activeTab)}</div>

      {/* 保存/取消按钮 */}
      <div className="flex justify-center items-center absolute bottom-0 w-[600px] h-[8vh] gap-4 mt-[100px] bg-background-login z-10">
        <Button variant="outline" className="px-16" onClick={() => onChange()}>{t('cancel')}</Button>
        <Button className="px-16" onClick={handleSave}>{t('save')}</Button>
      </div>
    </div>
  );
}
