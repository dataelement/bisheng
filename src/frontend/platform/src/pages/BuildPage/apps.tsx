// @ts-strict-ignore
import { Button, SearchInput, notification } from '@bisheng/ui';
import CardComponent from "@/components/bs-comp/cardComponent";
import AppAvator from "@/components/bs-comp/cardComponent/avatar";
import LabelShow from "@/components/bs-comp/cardComponent/LabelShow";
import { PermissionDialog } from "@/components/bs-comp/permission/PermissionDialog";
import { hasResourceAction,useResourceActions } from "@/components/bs-comp/permission/useResourceActions";
import AppTempSheet from "@/components/bs-comp/sheets/AppTempSheet";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { Outlined } from "bisheng-icons";


import LoadMore from "@/components/bs-comp/loadMore";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";


import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";

import { userContext } from "@/contexts/userContext";
import { changeAssistantStatusApi,createAssistantsApi,deleteAssistantApi,getAssistantDetailApi,saveAssistanttApi } from "@/controllers/API/assistant";
import { deleteFlowFromDatabase,getAppsApi,getFlowApi } from "@/controllers/API/flow";
import { copyReportTemplate,createWorkflowApi,onlineWorkflow } from "@/controllers/API/workflow";
import { handleUiRequest } from "@/controllers/request";
import { AppNumType,AppType } from "@/types/app";
import { FlowType } from "@/types/flow";
import { useInfiniteCursorTable } from "@/util/hook";
import { generateUUID } from "@/utils";
import { Select, Tag } from "@bisheng/ui";
import { useContext,useEffect,useRef,useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import CardSelectVersion from "./CardSelectVersion";
import CreateApp from "./CreateApp";
import CreateTemp from "./CreateTemp";
import { useCreateTemp,useQueryLabels } from "./hook";

/** 按应用上线(2)/下线(1)状态筛选，与后端 ``/api/v1/workflow/list?status=`` 一致 */
export const SelectAppStatus = ({ defaultValue = 'all', onChange }: { defaultValue?: string; onChange: (v: string) => void }) => {
    const [value, setValue] = useState(defaultValue)
    const { t } = useTranslation()
    const selectLabels = useSelectLabels()

    const options = [
        { value: 'all', label: t('build.allAppStatus') },
        { value: '2', label: t('build.online') },
        { value: '1', label: t('build.offline') },
    ]

    return (
        <Select
            {...selectLabels}
            aria-label={t('tenant.statusFilter')}
            className="max-w-36 min-w-[9rem]"
            placeholder={t('build.allAppStatus')}
            options={options}
            value={value}
            onChange={(v) => {
                if (v == null || String(v) === value) return
                onChange(String(v))
                setValue(String(v))
            }}
        />
    )
}

export const SelectType = ({ all = false, defaultValue = 'all', onChange }) => {
    const [value, setValue] = useState<string>(defaultValue)
    const { t } = useTranslation();
    const selectLabels = useSelectLabels()

    const options: { label: string; value: string }[] = [
        { label: t('build.workflow'), value: AppType.FLOW },
        { label: t('build.assistant'), value: AppType.ASSISTANT },
    ];

    if (all) {
        options.unshift({ label: t('build.allAppTypes'), value: 'all' });
    }


    return <Select
        {...selectLabels}
        aria-label={t('build.appTypeFilter')}
        className="max-w-32"
        placeholder={t('build.allAppTypes')}
        options={options}
        value={value}
        onChange={(v) => {
            if (v == null || String(v) === value) return
            onChange(String(v))
            setValue(String(v))
        }}
    />
}

interface LabelFilterSelectProps {
    options: { label: string; value: number | string | null }[]
    value: number | string | null
    onChange: (value: number | string) => void
}

/** Tag filter of the app list; -1 is the "all tags" row added by useQueryLabels. */
function LabelFilterSelect({ options, value, onChange }: LabelFilterSelectProps) {
    const { t } = useTranslation()
    const selectLabels = useSelectLabels()

    return <Select
        {...selectLabels}
        aria-label={t('chat.filterLabel')}
        className="w-52"
        showSearch
        placeholder={t('chat.allLabels')}
        options={options
            .filter(o => o.value != null && o.value !== '')
            .map(o => ({ value: o.value as number | string, label: o.label }))}
        value={value || null}
        onChange={(v) => { if (v != null) onChange(v) }}
    />
}

const TypeNames = {
    5: AppType.ASSISTANT,
    10: AppType.FLOW
}

const APP_ACTIONS = [
    'visible',
    'edit',
    'publish',
    'unpublish',
    'delete',
    'manage_permission',
]

export default function apps() {
    const { t, i18n } = useTranslation()
    // useErrorPrompt();

    useEffect(() => {
        i18n.loadNamespaces('flow');
    }, [i18n]);
    const { user } = useContext(userContext);

    const navigate = useNavigate()

    // Build page lists apps the user can manage. Backend treats managed=true
    // as "filter by edit" (admins still see everything via the admin
    // short-circuit).
    // F027: cursor-based infinite scroll; `total` / `page` / `setPage` are gone.
    // `managed: true` is seeded via initial param so it flows through every
    // request automatically; `filterData({tag_id|type|status: ...})` then
    // mutates paramsRef and triggers a fresh first-page load.
    const { data: dataSource, loading, hasMore, search, reload, loadMore, filterData, refreshData } = useInfiniteCursorTable<FlowType>(
        { pageSize: 14, cancelLoadingWhenReload: true, managed: true },
        (param) => getAppsApi({
            cursor: param.cursor,
            pageSize: param.pageSize,
            keyword: param.keyword,
            tag_id: param.tag_id,
            type: param.type,
            status: param.status,
            managed: param.managed,
        }),
    )

    // Permission management state
    const [permDialogOpen, setPermDialogOpen] = useState(false);
    const [permTarget, setPermTarget] = useState<{ id: string; name: string; type: string } | null>(null);
    const workflowResourceIds = dataSource
        .filter((item: any) => item.flow_type !== AppNumType.ASSISTANT)
        .map((item: any) => String(item.id));
    const assistantResourceIds = dataSource
        .filter((item: any) => item.flow_type === AppNumType.ASSISTANT)
        .map((item: any) => String(item.id));
    const { actions: workflowActions } = useResourceActions('workflow', workflowResourceIds, APP_ACTIONS);
    const { actions: assistantActions } = useResourceActions('assistant', assistantResourceIds, APP_ACTIONS);
    const resourceActions = { ...workflowActions, ...assistantActions };
    const listedAppIds = new Set(dataSource.map((item: any) => String(item.id)));
    const canRead = (id: string | number) =>
        user.role === 'admin' ||
        hasResourceAction(resourceActions, id, 'visible') ||
        listedAppIds.has(String(id));
    const canEdit = (id: string | number) => hasResourceAction(resourceActions, id, 'edit');
    const canPublish = (id: string | number) => hasResourceAction(resourceActions, id, 'publish');
    const canUnpublish = (id: string | number) => hasResourceAction(resourceActions, id, 'unpublish');
    const canManage = (id: string | number) => hasResourceAction(resourceActions, id, 'manage_permission');
    const canDelete = (id: string | number) => hasResourceAction(resourceActions, id, 'delete');
    const visibleApps = dataSource;

    // `create_app` controls the create and template-management entries.
    // Only global super admins bypass the role menu permission.
    const canCreateApp =
        user.role === 'admin' ||
        (user.web_menu || []).includes('create_app');

    const [copyingId, setCopyingId] = useState<string | number | null>(null);

    const handleCopyApp = async (item: any) => {
        if (!canCreateApp || !canRead(item.id) || copyingId) return;
        setCopyingId(item.id);
        try {
            if (item.flow_type === AppNumType.ASSISTANT) {
                const detail = await getAssistantDetailApi(String(item.id), 'v1');
                if (!detail) return;
                const newName = `${detail.name}-${generateUUID(5)}`;
                const created = await createAssistantsApi(newName, detail.prompt || '', detail.logo || '');
                if (!created?.id) return;
                await saveAssistanttApi({
                        ...detail,
                        id: created.id,
                        name: newName,
                        flow_list: (detail.flow_list || []).map((f: { id: string }) => f.id),
                        tool_list: (detail.tool_list || []).map((tool: { id: number }) => tool.id),
                        knowledge_list: (detail.knowledge_list || []).map((k: { id: number }) => k.id),
                        guide_question: (detail.guide_question || []).filter(Boolean),
                        logo: detail.logo || '',
                    });
                reload();
                return;
            }
            const flow = await getFlowApi(String(item.id));
            if (!flow) return;
            if (item.flow_type === AppNumType.FLOW) {
                const payload = JSON.parse(JSON.stringify(flow)) as typeof flow;
                payload.name = `${flow.name}-${generateUUID(5)}`;
                if (payload.data?.source) delete payload.data.source;
                if (payload.data?.nodes?.length) {
                    for (const node of payload.data.nodes) {
                        await copyReportTemplate(node.data);
                    }
                }
                delete (payload as any).id;
                const res = await createWorkflowApi(payload.name, payload.description || '', payload.logo || '', payload);
                if (res?.id) {
                    reload();
                    navigate(`/flow/${res.id}`);
                }
                return;
            }
        } finally {
            setCopyingId(null);
        }
    };

    const handleOpenPermission = (item: any) => {
        const typeMap = { 5: 'assistant', 10: 'workflow' };
        setPermTarget({ id: String(item.id), name: item.name, type: typeMap[item.flow_type] || 'workflow' });
        setPermDialogOpen(true);
    };

    const { open: tempOpen, tempType, flowRef, toggleTempModal } = useCreateTemp()

    // on/off line
    const handleCheckedChange = (checked, data) => {
        if (checked && !canPublish(data.id)) return;
        if (!checked && !canUnpublish(data.id)) return;
        if (data.flow_type === 5) {
            return changeAssistantStatusApi(data.id, checked ? 2 : 1).then(res => {
                if (res === null) {
                    refreshData((item) => item.id === data.id, { status: checked ? 2 : 1 })
                }
                return res
            })
        } else if (data.flow_type === 10) {
            return onlineWorkflow(data, checked ? 2 : 1).then(res => {
                if (res) {
                    refreshData((item) => item.id === data.id, { status: checked ? 2 : 1 })
                }
                return res
            })
        }
    }

    const typeCnNames = {
        5: t('build.assistant'),
        10: t('build.workflow')
    }

    const handleDelete = (data) => {
        const descMap = {
            1: t('build.confirmDeleteSkill'),
            10: t('build.confirmDeleteFlow'),
            5: t('build.confirmDeleteAssistant')
        }
        bsConfirm({
            desc: descMap[data.flow_type],
            okTxt: t('delete'),
            onOk(next) {
                const promise = data.flow_type == 5 ? deleteAssistantApi(data.id) : deleteFlowFromDatabase(data.id)
                return promise.then(() => { reload(); next() });
            }
        })
    }


    const handleSetting = (data) => {
        if (!data.write) {
            return notification.open({ type: 'warning', description: String(t('build.editPermissionRequired')) })
        }
        if (data.flow_type === 5) {
            navigate(`/assistant/${data.id}`, { state: { flow: data } })
        } else {
            navigate(`/flow/${data.id}`, { state: { flow: data } })
        }
    }

    const createAppModalRef = useRef(null)
    const handleCreateApp = async (type, tempId = 0, item?: any) => {
        createAppModalRef.current.open(type, tempId);
    }

    const { selectLabel, setSelectLabel, filteredOptions, allOptions, refetchLabels } = useQueryLabels(t)
    const handleLabelSearch = (id) => {
        setSelectLabel(allOptions.find(l => l.value === id))
        filterData({ tag_id: id })
    }

    const tempTypeRef = useRef(null)
    return <div className="h-full relative">
        <div className="px-10 py-10 h-full overflow-y-scroll scrollbar-hide relative bg-background-main border-t">
            <div className="flex gap-4">
                <SearchInput placeholder={t('build.searchApp')} onChange={(e) => search(e.target.value)} className={"w-64"}></SearchInput>
                <SelectType all onChange={(v) => {
                    tempTypeRef.current = v
                    filterData({ type: v })
                }} />
                <SelectAppStatus
                    onChange={(v) => {
                        filterData({ status: v === 'all' ? undefined : Number(v) })
                    }}
                />
                <LabelFilterSelect
                    options={allOptions}
                    value={selectLabel.value}
                    onChange={handleLabelSearch}
                />
                {canCreateApp && (
                    <Button variant="text" className="hover:bg-gray-50 flex gap-2 dark:hover:bg-[#34353A] ml-auto" onClick={() => navigate(`/build/temps/${tempTypeRef.current && tempTypeRef.current !== AppType.ALL ? tempTypeRef.current : AppType.FLOW}`)} color="default"><Outlined.MoveToFolder className="dark:text-slate-50" />{t('build.manageAppTemplates')}</Button>
                )}
            </div>
            {/* list */}
            {
                loading
                    ? <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                        <LoadingIcon />
                    </div>
                    : <div className="mt-6 flex gap-2 flex-wrap pb-20">
                        {canCreateApp && (
                            <AppTempSheet onSelect={handleCreateApp} onCustomCreate={handleCreateApp}>
                                <CardComponent<FlowType>
                                    data={null}
                                    type='assist'
                                    title={t('log.createBuild')}
                                    description={(<>
                                        <p><p>{t('build.provideSceneTemplates')}</p></p>
                                    </>)}
                                ></CardComponent>
                            </AppTempSheet>
                        )}
                        {
                            visibleApps.map((item: any, i) => (
                                <CardComponent<FlowType>
                                    key={item.id}
                                    data={item}
                                    id={item.id}
                                    logo={<AppAvator id={item.name} flowType={item.flow_type} url={item.logo} />}
                                    type={TypeNames[item.flow_type]}
                                    edit={canEdit(item.id)}
                                    // edit={item.write}
                                    title={item.name}
                                    isAdmin={user.role === 'admin'}
                                    description={item.description}
                                    checked={item.status === 2}
                                    user={item.user_name}
                                    currentUser={user}
                                    onClick={() => canEdit(item.id) && handleSetting(item)}
                                    // onSwitchClick={() => {
                                    //     !item.write && item.status !== 2 && message({
                                    //         description: t('build.noPermissionToPublish', { type: typeCnNames[item.flow_type] }),
                                    //         variant: 'warning'
                                    //     })
                                    // }}
                                    onAddTemp={toggleTempModal}
                                    onCheckedChange={handleCheckedChange}
                                    onDelete={canDelete(item.id) ? handleDelete : undefined}
                                    onSetting={(item) => handleSetting(item)}
                                    onPermission={canManage(item.id) ? handleOpenPermission : undefined}
                                    showSwitch={item.status === 2 ? canUnpublish(item.id) : canPublish(item.id)}
                                    canSwitch={item.status === 2 ? canUnpublish(item.id) : canPublish(item.id)}
                                    showCopy={canCreateApp && canRead(item.id)}
                                    onCopy={canCreateApp && canRead(item.id) ? handleUiRequest(handleCopyApp) : undefined}
                                    headSelecter={(
                                        item.version_list?.length ? <CardSelectVersion
                                            showPop={item.status !== 2}
                                            data={item}
                                        /> : null)}
                                    labelPannel={
                                        <LabelShow
                                            data={item}
                                            user={user}
                                            type={item.flow_type}
                                            all={filteredOptions}
                                            onChange={refetchLabels}>
                                        </LabelShow>
                                    }
                                    footer={
                                        <span className="absolute bottom-0 right-0"><Tag size="small" color={item.flow_type === AppNumType.ASSISTANT ? "warning" : "brand"}>
                                            {typeCnNames[item.flow_type]}
                                        </Tag></span>
                                    }
                                ></CardComponent>
                            ))
                        }
                    </div>
            }
            {/* F027: infinite-scroll trigger lives INSIDE the scroll container
                (the `overflow-y-scroll` div above). Placing it outside the
                scroll parent makes IntersectionObserver miss in-container
                scroll events and the cursor pagination stalls after page 2. */}
            {hasMore && <LoadMore onScrollLoad={loadMore} />}
        </div>
        {/* add template */}
        <CreateTemp flow={flowRef.current} type={tempType} open={tempOpen} setOpen={() => toggleTempModal()} onCreated={() => { }} ></CreateTemp>
        {/* footer */}
        <div className="flex justify-between absolute bottom-0 left-0 w-full bg-background-main h-16 items-center px-10 z-20">
            <div className="flex items-center gap-2">
                <p className="text-sm text-muted-foreground break-keep">{t('build.manageYourApplications')}</p>
            </div>
            {/* F027: legacy AutoPagination slot — infinite scroll trigger
                moved INSIDE the scroll container above; this bar now only
                holds the "manage your applications" caption. */}
        </div>
        {/* create flow&assistant */}
        <CreateApp ref={createAppModalRef} />
        {/* Permission management dialog */}
        {permTarget && (
            <PermissionDialog
                open={permDialogOpen}
                onOpenChange={setPermDialogOpen}
                resourceType={permTarget.type as any}
                resourceId={permTarget.id}
                resourceName={permTarget.name}
            />
        )}
    </div>
};
