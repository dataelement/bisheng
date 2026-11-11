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
import { changeAssistantStatusApi, deleteAssistantApi } from "@/controllers/API/assistant";
import { createAssistantsApi, getAssistantDetailApi, saveAssistanttApi } from "@/controllers/API/assistant";
import { deleteFlowFromDatabase, getAppsApi, getFlowApi, getWorkflowManagementEditorFlow, getWorkflowManagementSummary } from "@/controllers/API/flow";
import type { HostedAppActionResult } from "@/controllers/API/hostedApp";
import { copyReportTemplate, createWorkflowApi, onlineWorkflow, onlineWorkflowApi } from "@/controllers/API/workflow";
import { handleUiRequest } from "@/controllers/request";
import { AppNumType, AppType } from "@/types/app";
import { locationContext } from "@/contexts/locationContext";
import { HostedAppCard } from "./HostedAppCard";
import type { HostedAppActionKind } from "./useHostedAppActions";
import { HOSTED_APP_STATES, stateI18nKey } from "./hostedApp/types";
import { FlowType } from "@/types/flow";
import { useInfiniteCursorTable } from "@/util/hook";
import { generateUUID } from "@/utils";
import { Select, Tag } from "@bisheng/ui";
import { useContext,useEffect,useRef,useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import { WORKFLOW_MANAGEMENT_PATH, WORKFLOW_MANAGEMENT_SCOPE, workflowManagementEditorPath } from "@/utils/workflowManagement";
import CardSelectVersion from "./CardSelectVersion";
import CreateApp from "./CreateApp";
import CreateTemp from "./CreateTemp";
import { canManageAppTemplates } from "./templatePermissions";
import { useCreateTemp,useQueryLabels } from "./hook";

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
    const selectLabels = useSelectLabels()

    const options = [
        { value: 'all', label: t('build.allAppStatus') },
        ...(hosted ? HOSTED_APP_STATES.map(state => ({ value: state, label: t(stateI18nKey(state)) })) : [
            { value: '2', label: t('build.online') },
            { value: '1', label: t('build.offline') },
        ]),
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

/**
 * `includeHosted` is opt-in on purpose: this component is also the template
 * manager's type picker (`appTemps.tsx`), and templates have no hosted-app
 * flavour — an unconditional third option would navigate that page to a 404.
 */
export const SelectType = ({ all = false, includeHosted = false, defaultValue = 'all', onChange }) => {
    const [value, setValue] = useState<string>(defaultValue)
    const { t } = useTranslation();
    const selectLabels = useSelectLabels()

    const options: { label: string; value: string }[] = [
        { label: t('build.workflow'), value: AppType.FLOW },
        { label: t('build.assistant'), value: AppType.ASSISTANT },
    ];

    if (includeHosted) {
        options.push({ label: t('hostedApp.typeName'), value: AppType.HOSTED_APP });
    }

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

interface AppsProps {
    workflowOnly?: boolean;
}

export default function Apps({ workflowOnly = false }: AppsProps) {
    const { user } = useContext(userContext);
    const scopeKey = workflowOnly ? `workflow:${user?.user_id}:${user?.tenant_id}` : 'apps';
    return <AppList key={scopeKey} workflowOnly={workflowOnly} />;
}

function AppList({ workflowOnly }: AppsProps) {
    const { t, i18n } = useTranslation()
    // useErrorPrompt();

    useEffect(() => {
        i18n.loadNamespaces('flow');
    }, [i18n]);
    const { user } = useContext(userContext);
    const { appConfig } = useContext(locationContext);
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
    const { data: dataSource, loading, loaded, loadError, hasMore, search, reload, loadMore, filterData, refreshData } = useInfiniteCursorTable<FlowType>(
        { pageSize: 14, cancelLoadingWhenReload: true, managed: true },
        (param) => getAppsApi({
            cursor: param.cursor,
            pageSize: param.pageSize,
            keyword: param.keyword,
            tag_id: param.tag_id,
            type: workflowOnly ? AppType.FLOW : param.type,
            status: param.status,
            app_state: param.app_state,
            managed: workflowOnly ? false : param.managed,
            action: workflowOnly ? 'visible' : undefined,
            scope: workflowOnly ? WORKFLOW_MANAGEMENT_SCOPE : undefined,
        }),
    )

    // Permission management state
    const [permDialogOpen, setPermDialogOpen] = useState(false);
    const [permTarget, setPermTarget] = useState<{ id: string; name: string; type: string } | null>(null);
    // Three buckets, one per resource type. A hosted app that fell into the
    // workflow bucket would be checked against the wrong type and come back
    // with no actions at all — a card you can see but cannot touch.
    const appRows = (dataSource as AppListRow[]).filter(item => !workflowOnly || item.flow_type === AppNumType.FLOW);
    const workflowResourceIds = appRows
        .filter((item) => item.flow_type !== AppNumType.ASSISTANT && item.flow_type !== AppNumType.HOSTED_APP)
        .map((item) => String(item.id));
    const assistantResourceIds = appRows
        .filter((item) => item.flow_type === AppNumType.ASSISTANT)
        .map((item) => String(item.id));
    const hostedAppResourceIds = appRows
        .filter((item) => item.flow_type === AppNumType.HOSTED_APP)
        .map((item) => String(item.id));
    const { actions: workflowActions } = useResourceActions('workflow', workflowResourceIds, APP_ACTIONS,
        workflowOnly ? String(user.tenant_id) : undefined);
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

    const canManageTemplates = !workflowOnly && canManageAppTemplates(user);
    // Application creation and template management have separate permissions.
    // Only global super admins bypass the role menu permission.
    const canCreateApp =
        user.role === 'admin' ||
        (user.web_menu || []).includes('create_app');
    const canCopy = (id: string | number) => canCreateApp && (workflowOnly ? canEdit(id) : canRead(id));

    const [copyingId, setCopyingId] = useState<string | number | null>(null);

    const handleCopyApp = async (item: any) => {
        if (!canCopy(item.id) || copyingId) return;
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
            const flow = await (workflowOnly ? getWorkflowManagementEditorFlow : getFlowApi)(String(item.id));
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
                    navigate(workflowOnly ? workflowManagementEditorPath(res.id) : `/flow/${res.id}`);
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
    const handleCheckedChange = async (checked, data) => {
        if (checked ? !canPublish(data.id) : !canUnpublish(data.id)) return false;
        if (workflowOnly) {
            const { versions } = await getWorkflowManagementSummary(String(data.id));
            const current = versions.find(version => version.is_current === 1);
            if (!current) return false;
            await onlineWorkflowApi({ flow_id: data.id, version_id: current.id, status: checked ? 2 : 1 });
            reload();
            return true;
        }
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

    // A hosted-app action answers with the state it left the app in. Patch the
    // row from that answer *before* refetching: taking one offline waits on
    // `docker stop` (~10s), and the list request that follows is another round
    // trip on top — long enough for the card to look like nothing happened.
    // Failures re-sync too (`result` is null): a rejected action is usually one
    // that already landed, which is exactly the case that used to need F5.
    const handleHostedAppChanged = (kind: HostedAppActionKind, result: HostedAppActionResult | null) => {
        if (kind !== 'delete' && result?.app_id && result.state) {
            refreshData(
                (row) => String(row.id) === String(result.app_id),
                { status: result.state === 'online' ? 2 : 1, app_state: result.state } as Partial<FlowType>,
            )
        }
        reload()
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
                return promise.then(() => { reload(); next() });
            }
        })
    }


    const handleSetting = (data) => {
        if (workflowOnly) {
            return navigate(canEdit(data.id)
                ? workflowManagementEditorPath(String(data.id))
                : `${WORKFLOW_MANAGEMENT_PATH}/${encodeURIComponent(data.id)}`);
        }
        if (data.flow_type === AppNumType.HOSTED_APP) {
            return navigate(`/build/apps/${data.id}`)
        }
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
    const { search: entrySearch } = useLocation();
    const kunlianEntry = new URLSearchParams(entrySearch).get('kunlian_workflow') === 'new';
    const openedKunlianCreate = useRef(false);
    useEffect(() => {
        if (canCreateApp && !openedKunlianCreate.current && kunlianEntry) {
            openedKunlianCreate.current = true;
            createAppModalRef.current?.open(AppType.FLOW, 0);
        }
    }, [canCreateApp, kunlianEntry]);
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
        <div className="px-10 py-10 h-full overflow-y-scroll scrollbar-hide relative bg-[#f8f8f8] dark:bg-background-main border-t">
            {workflowOnly && <h1 className="text-xl font-semibold mb-5">{t('build.workflowManagement')}</h1>}
            <div className="flex gap-4">
                <SearchInput className="w-64" placeholder={t(workflowOnly ? 'build.searchWorkflow' : 'build.searchApp')} onChange={(e) => search(e.target.value)}></SearchInput>
                {!workflowOnly && <SelectType all includeHosted={hostedAppEnabled} onChange={(v) => {
                    tempTypeRef.current = v
                    setTypeFilter(v)
                    // Switching type resets the state filter: `status` and
                    // `app_state` are two different columns and leaving the
                    // previous one set would silently narrow the new list.
                    filterData({ type: v, status: undefined, app_state: undefined })
                }} />}
                <SelectAppStatus
                    key={hostedSelected ? 'hosted' : 'default'}
                    hosted={hostedSelected}
                    onChange={(v) => {
                        filterData(hostedSelected
                            ? { app_state: v === 'all' ? undefined : v, status: undefined }
                            : { status: v === 'all' ? undefined : Number(v), app_state: undefined })
                    }}
                />
                {!workflowOnly && <LabelFilterSelect
                    options={allOptions}
                    value={selectLabel.value}
                    onChange={handleLabelSearch}
                />}
                {canManageTemplates && (
                    <Button variant="text" className="hover:bg-gray-50 flex gap-2 dark:hover:bg-[#34353A] ml-auto" onClick={() => navigate(`/build/temps/${tempTypeRef.current && tempTypeRef.current !== AppType.ALL && tempTypeRef.current !== AppType.HOSTED_APP ? tempTypeRef.current : AppType.FLOW}`)} color="default"><Outlined.MoveToFolder className="dark:text-slate-50" />{t('build.manageAppTemplates')}</Button>
                )}
            </div>
            {/* list */}
            {
                loading || (workflowOnly && !loaded && !loadError)
                    ? <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                        <LoadingIcon />
                    </div>
                    : <div className="mt-6 flex gap-2 flex-wrap pb-20">
                        {canCreateApp && (workflowOnly ? (
                            <Button onClick={() => handleCreateApp(AppType.FLOW)}>{t('build.createWorkflow')}</Button>
                        ) : (
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
                        ))}
                        {workflowOnly && loadError && (
                            <Button variant="outlined" onClick={reload}>{t('build.reloadWorkflows')}</Button>
                        )}
                        {workflowOnly && loaded && !loadError && !visibleApps.length && (
                            <p className="text-muted-foreground">{t('build.noWorkflows')}</p>
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
                                    onChanged={handleHostedAppChanged}
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
                                    onClick={() => (workflowOnly || canEdit(item.id)) && handleSetting(item)}
                                    // onSwitchClick={() => {
                                    //     !item.write && item.status !== 2 && message({
                                    //         description: t('build.noPermissionToPublish', { type: typeCnNames[item.flow_type] }),
                                    //         variant: 'warning'
                                    //     })
                                    // }}
                                    canAddTemplate={canManageTemplates && canRead(item.id)}
                                    onAddTemp={canManageTemplates ? toggleTempModal : undefined}
                                    onCheckedChange={handleCheckedChange}
                                    onDelete={canDelete(item.id) ? handleDelete : undefined}
                                    onSetting={(item) => handleSetting(item)}
                                    onPermission={canManage(item.id) ? handleOpenPermission : undefined}
                                    showSwitch={item.status === 2 ? canUnpublish(item.id) : canPublish(item.id)}
                                    canSwitch={item.status === 2 ? canUnpublish(item.id) : canPublish(item.id)}
                                    showCopy={canCopy(item.id)}
                                    onCopy={canCopy(item.id) ? handleUiRequest(handleCopyApp) : undefined}
                                    headSelecter={(
                                        (workflowOnly ? canEdit(item.id) : true) && item.version_list?.length ? <CardSelectVersion
                                            showPop={item.status !== 2}
                                            data={item}
                                        /> : null)}
                                    labelPannel={workflowOnly ? undefined :
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
        {!workflowOnly && <div className="flex justify-between absolute bottom-0 left-0 w-full bg-[#f8f8f8] dark:bg-background-main h-16 items-center px-10 z-20">
            <div className="flex items-center gap-2">
                <p className="text-sm text-muted-foreground break-keep">{t('build.manageYourApplications')}</p>
            </div>
            {/* F027: legacy AutoPagination slot — infinite scroll trigger
                moved INSIDE the scroll container above; this bar now only
                holds the "manage your applications" caption. */}
        </div>}
        {/* create flow&assistant */}
        <CreateApp ref={createAppModalRef} kunlianEntry={kunlianEntry} workflowManagement={workflowOnly} />
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
