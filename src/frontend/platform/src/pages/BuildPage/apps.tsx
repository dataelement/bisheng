// @ts-strict-ignore
import CardComponent from "@/components/bs-comp/cardComponent";
import AppAvator from "@/components/bs-comp/cardComponent/avatar";
import LabelShow from "@/components/bs-comp/cardComponent/LabelShow";
import { PermissionDialog } from "@/components/bs-comp/permission/PermissionDialog";
import { hasResourceAction, useResourceActions } from "@/components/bs-comp/permission/useResourceActions";
import AppTempSheet from "@/components/bs-comp/sheets/AppTempSheet";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { MoveOneIcon } from "@/components/bs-icons/moveOne";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Badge } from "@/components/bs-ui/badge";
import { Button } from "@/components/bs-ui/button";
import { SearchInput } from "@/components/bs-ui/input";
import LoadMore from "@/components/bs-comp/loadMore";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import SelectSearch from "@/components/bs-ui/select/select";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { userContext } from "@/contexts/userContext";
import { changeAssistantStatusApi, deleteAssistantApi } from "@/controllers/API/assistant";
import { createAssistantsApi, getAssistantDetailApi, saveAssistanttApi } from "@/controllers/API/assistant";
import { deleteFlowFromDatabase, getAppsApi, getFlowApi } from "@/controllers/API/flow";
import { copyReportTemplate, createWorkflowApi, onlineWorkflow } from "@/controllers/API/workflow";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { AppNumType, AppType } from "@/types/app";
import { locationContext } from "@/contexts/locationContext";
import { HostedAppCard } from "./HostedAppCard";
import { HOSTED_APP_STATES, stateI18nKey } from "./hostedApp/types";
import { FlowType } from "@/types/flow";
import { useInfiniteCursorTable } from "@/util/hook";
import { generateUUID } from "@/utils";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import CreateApp from "./CreateApp";
import { useCreateTemp, useErrorPrompt, useQueryLabels } from "./hook";
import CardSelectVersion from "./CardSelectVersion";
import CreateTemp from "./CreateTemp";

/**
 * 按应用上线(2)/下线(1)状态筛选，与后端 ``/api/v1/workflow/list?status=`` 一致。
 *
 * F054: with `hosted`, the options become the five hosted-application states
 * instead. They deliberately do NOT ride on `status` — that column is projected
 * 2/1 for the shared switch and the backend only honours those two values — so
 * the caller forwards the chosen value as the separate `app_state` parameter.
 */
export const SelectAppStatus = ({ defaultValue = 'all', hosted = false, onChange }: { defaultValue?: string; hosted?: boolean; onChange: (v: string) => void }) => {
    const [value, setValue] = useState(defaultValue)
    const { t } = useTranslation()

    return (
        <Select value={value} onValueChange={(v) => { onChange(v); setValue(v) }}>
            <SelectTrigger className="max-w-36 min-w-[9rem]">
                <SelectValue placeholder={t('build.allAppStatus')} />
            </SelectTrigger>
            <SelectContent>
                <SelectGroup>
                    <SelectItem value="all">{t('build.allAppStatus')}</SelectItem>
                    {hosted
                        ? HOSTED_APP_STATES.map((state) => (
                            <SelectItem key={state} value={state}>{t(stateI18nKey(state))}</SelectItem>
                        ))
                        : <>
                            <SelectItem value="2">{t('build.online')}</SelectItem>
                            <SelectItem value="1">{t('build.offline')}</SelectItem>
                        </>}
                </SelectGroup>
            </SelectContent>
        </Select>
    )
}

/**
 * `includeHosted` is opt-in on purpose: this component is also the template
 * manager's type picker (`appTemps.tsx`), and templates have no hosted-app
 * flavour — an unconditional third option would navigate that page to a 404.
 */
export const SelectType = ({ all = false, includeHosted = false, defaultValue = 'all', onChange }) => {
    const [value, setValue] = useState<string>(defaultValue)
    const { t } = useTranslation();

    const options: any = [
        { label: t('build.workflow'), value: AppType.FLOW },
        { label: t('build.assistant'), value: AppType.ASSISTANT },
    ];

    if (includeHosted) {
        options.push({ label: t('hostedApp.typeName'), value: AppType.HOSTED_APP });
    }

    if (all) {
        options.unshift({ label: t('build.allAppTypes'), value: 'all' });
    }


    return <Select value={value} onValueChange={(v) => { onChange(v); setValue(v) }}>
        <SelectTrigger className="max-w-32">
            <SelectValue placeholder={t('build.allAppTypes')} />
        </SelectTrigger>
        <SelectContent>
            <SelectGroup>
                {options.map(el => (
                    <SelectItem key={el.value} value={el.value}>{el.label}</SelectItem>
                ))}
            </SelectGroup>
        </SelectContent>
    </Select>
}

const TypeNames = {
    5: AppType.ASSISTANT,
    10: AppType.FLOW,
    35: AppType.HOSTED_APP
}

/**
 * A row of the app list. The endpoint projects all three application types onto
 * one column set, so `flow_type` (and, for hosted apps, `app_state`) is what
 * tells them apart.
 */
type AppListRow = FlowType & {
    flow_type?: number
    /** F054 only — the five-state application state. */
    app_state?: string
    version_list?: { id: string | number }[]
}

const APP_ACTIONS = [
    'visible',
    'edit',
    'publish',
    'unpublish',
    'delete',
    'manage_permission',
]

export default function Apps() {
    const { t, i18n } = useTranslation()
    // useErrorPrompt();

    useEffect(() => {
        i18n.loadNamespaces('flow');
    }, [i18n]);
    const { user } = useContext(userContext);
    const { appConfig } = useContext(locationContext);
    const { message } = useToast()
    const navigate = useNavigate()
    // F054: the third type only exists where the app-factory runtime layer is
    // deployed. Deployment-level flag, read from /api/v1/env.
    const hostedAppEnabled = !!appConfig.appRuntimeEnabled
    const [typeFilter, setTypeFilter] = useState<string>(AppType.ALL)
    const hostedSelected = hostedAppEnabled && typeFilter === AppType.HOSTED_APP

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
    // Three buckets, one per resource type. A hosted app that fell into the
    // workflow bucket would be checked against the wrong type and come back
    // with no actions at all — a card you can see but cannot touch.
    const appRows = dataSource as AppListRow[];
    const workflowResourceIds = appRows
        .filter((item) => item.flow_type !== AppNumType.ASSISTANT && item.flow_type !== AppNumType.HOSTED_APP)
        .map((item) => String(item.id));
    const assistantResourceIds = appRows
        .filter((item) => item.flow_type === AppNumType.ASSISTANT)
        .map((item) => String(item.id));
    const hostedAppResourceIds = appRows
        .filter((item) => item.flow_type === AppNumType.HOSTED_APP)
        .map((item) => String(item.id));
    const { actions: workflowActions } = useResourceActions('workflow', workflowResourceIds, APP_ACTIONS);
    const { actions: assistantActions } = useResourceActions('assistant', assistantResourceIds, APP_ACTIONS);
    const { actions: hostedAppActions } = useResourceActions('app', hostedAppResourceIds, APP_ACTIONS);
    const resourceActions = { ...workflowActions, ...assistantActions, ...hostedAppActions };
    const listedAppIds = new Set(appRows.map((item) => String(item.id)));
    const canRead = (id: string | number) =>
        user.role === 'admin' ||
        hasResourceAction(resourceActions, id, 'visible') ||
        listedAppIds.has(String(id));
    const canEdit = (id: string | number) => hasResourceAction(resourceActions, id, 'edit');
    const canPublish = (id: string | number) => hasResourceAction(resourceActions, id, 'publish');
    const canUnpublish = (id: string | number) => hasResourceAction(resourceActions, id, 'unpublish');
    const canManage = (id: string | number) => hasResourceAction(resourceActions, id, 'manage_permission');
    const canDelete = (id: string | number) => hasResourceAction(resourceActions, id, 'delete');
    const visibleApps = appRows;

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
                const detail = await captureAndAlertRequestErrorHoc(getAssistantDetailApi(String(item.id), 'v1'));
                if (!detail) return;
                const newName = `${detail.name}-${generateUUID(5)}`;
                const created = await captureAndAlertRequestErrorHoc(
                    createAssistantsApi(newName, detail.prompt || '', detail.logo || '')
                );
                if (!created?.id) return;
                await captureAndAlertRequestErrorHoc(
                    saveAssistanttApi({
                        ...detail,
                        id: created.id,
                        name: newName,
                        flow_list: (detail.flow_list || []).map((f: { id: string }) => f.id),
                        tool_list: (detail.tool_list || []).map((tool: { id: number }) => tool.id),
                        knowledge_list: (detail.knowledge_list || []).map((k: { id: number }) => k.id),
                        guide_question: (detail.guide_question || []).filter(Boolean),
                        logo: detail.logo || '',
                    })
                );
                reload();
                return;
            }
            const flow = await captureAndAlertRequestErrorHoc(getFlowApi(String(item.id)));
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
                const res = await captureAndAlertRequestErrorHoc(
                    createWorkflowApi(payload.name, payload.description || '', payload.logo || '', payload)
                );
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
        // A missing entry falls back to 'workflow', which opens the dialog
        // against the wrong resource type and paints it red with 19003.
        const typeMap = { 5: 'assistant', 10: 'workflow', 35: 'app' };
        setPermTarget({ id: String(item.id), name: item.name, type: typeMap[item.flow_type] || 'workflow' });
        setPermDialogOpen(true);
    };

    const { open: tempOpen, tempType, flowRef, toggleTempModal } = useCreateTemp()

    // on/off line
    const handleCheckedChange = (checked, data) => {
        if (checked && !canPublish(data.id)) return;
        if (!checked && !canUnpublish(data.id)) return;
        if (data.flow_type === 5) {
            return captureAndAlertRequestErrorHoc(changeAssistantStatusApi(data.id, checked ? 2 : 1)).then(res => {
                if (res === null) {
                    refreshData((item) => item.id === data.id, { status: checked ? 2 : 1 })
                }
                return res
            })
        } else if (data.flow_type === 10) {
            return captureAndAlertRequestErrorHoc(onlineWorkflow(data, checked ? 2 : 1)).then(res => {
                if (res) {
                    refreshData((item) => item.id === data.id, { status: checked ? 2 : 1 })
                }
                return res
            })
        }
    }

    const typeCnNames = {
        5: t('build.assistant'),
        10: t('build.workflow'),
        35: t('hostedApp.typeName')
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
                captureAndAlertRequestErrorHoc(promise.then(reload));
                next()
            }
        })
    }

    const { toast } = useToast()
    const handleSetting = (data) => {
        if (data.flow_type === AppNumType.HOSTED_APP) {
            return navigate(`/build/apps/${data.id}`)
        }
        if (!data.write) {
            return toast({ variant: 'warning', description: t('build.noEditPermission') })
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

    const { selectLabel, setSelectLabel, setSearchKey, filteredOptions, allOptions, refetchLabels } = useQueryLabels(t)
    const handleLabelSearch = (id) => {
        setSelectLabel(allOptions.find(l => l.value === id))
        filterData({ tag_id: id })
    }

    const tempTypeRef = useRef(null)
    return <div className="h-full relative">
        <div className="px-10 py-10 h-full overflow-y-scroll scrollbar-hide relative bg-background-main border-t">
            <div className="flex gap-4">
                <SearchInput className="w-64" placeholder={t('build.searchApp')} onChange={(e) => search(e.target.value)}></SearchInput>
                <SelectType all includeHosted={hostedAppEnabled} onChange={(v) => {
                    tempTypeRef.current = v
                    setTypeFilter(v)
                    // Switching type resets the state filter: `status` and
                    // `app_state` are two different columns and leaving the
                    // previous one set would silently narrow the new list.
                    filterData({ type: v, status: undefined, app_state: undefined })
                }} />
                <SelectAppStatus
                    key={hostedSelected ? 'hosted' : 'default'}
                    hosted={hostedSelected}
                    onChange={(v) => {
                        filterData(hostedSelected
                            ? { app_state: v === 'all' ? undefined : v, status: undefined }
                            : { status: v === 'all' ? undefined : Number(v), app_state: undefined })
                    }}
                />
                <SelectSearch
                    value={!selectLabel.value ? '' : selectLabel.value}
                    options={allOptions}
                    selectPlaceholder={t('chat.allLabels')}
                    inputPlaceholder={t('chat.searchLabels')}
                    selectClass="w-52"
                    onOpenChange={() => setSearchKey('')}
                    onChange={(e) => setSearchKey(e.target.value)}
                    onValueChange={handleLabelSearch}>
                </SelectSearch>
                {canCreateApp && (
                    <Button
                        variant="ghost"
                        className="hover:bg-gray-50 flex gap-2 dark:hover:bg-[#34353A] ml-auto"
                        onClick={() => navigate(`/build/temps/${tempTypeRef.current && tempTypeRef.current !== AppType.ALL && tempTypeRef.current !== AppType.HOSTED_APP ? tempTypeRef.current : AppType.FLOW}`)}
                    ><MoveOneIcon className="dark:text-slate-50" />{t('build.manageAppTemplates')}</Button>
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
                            visibleApps.map((item) => item.flow_type === AppNumType.HOSTED_APP ? (
                                <HostedAppCard
                                    key={item.id}
                                    item={item}
                                    currentUser={user}
                                    isAdmin={user.role === 'admin'}
                                    canDelete={canDelete(item.id)}
                                    canSwitch={item.status === 2 ? canUnpublish(item.id) : canPublish(item.id)}
                                    canManagePermission={canManage(item.id)}
                                    onPermission={handleOpenPermission}
                                    onChanged={reload}
                                    labelPannel={
                                        <LabelShow
                                            data={item}
                                            user={user}
                                            type={item.flow_type}
                                            all={filteredOptions}
                                            onChange={refetchLabels}>
                                        </LabelShow>
                                    }
                                />
                            ) : (
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
                                    onCopy={canCreateApp && canRead(item.id) ? handleCopyApp : undefined}
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
                                        <Badge className={`absolute py-0 px-1 right-0 bottom-0 rounded-none rounded-br-md  ${item.flow_type === AppNumType.ASSISTANT && 'bg-[#fdb136]'}`}>
                                            {typeCnNames[item.flow_type]}
                                        </Badge>
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
