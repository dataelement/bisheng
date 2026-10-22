import { Button, Dropdown, DropdownItem, DropdownSeparator, SearchInput, Select, toast, notification } from '@bisheng/ui';
import { KnowledgeLibraryDialog } from "./components/KnowledgeLibraryDialog";
// @ts-strict-ignore
import { Outlined } from "bisheng-icons";
import { Shield } from "lucide-react";
import { useNavigate } from "react-router-dom";


import {
Table,
TableBody,
TableCell,
TableHead,
TableHeader,
TableRow
} from "../../components/bs-ui/table";
import { KnowledgeTooltip } from "./components/KnowledgeTooltip";



import { PermissionDialog } from "@/components/bs-comp/permission/PermissionDialog";
import { useLazyResourceActions } from "@/components/bs-comp/permission/useResourceActions";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { FilterIcon } from "@/components/bs-icons/filter";




import { useContext,useEffect,useState } from "react";
import { useTranslation } from "react-i18next";
import LoadMore from "../../components/bs-comp/loadMore";
import { userContext } from "../../contexts/userContext";
import { copyLibDatabase,deleteFileLib,readFileLibDatabase } from "../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import { useInfiniteCursorTable } from "../../util/hook";
import { FileAbnormalStatusCell } from "./components/FileAbnormalStatusCell";

// Knowledge base status
const enum KnowledgeBaseStatus {
    Unpublished = 0,
    Published = 1,   // Document knowledge base build success status
    Copying = 2,
    Rebuilding = 3,  // Document knowledge base rebuilding status
    Failed = 4       // Document knowledge base rebuild failed status
}

const KB_MANAGE_ACTION = 'manage_permission'
const KB_ROW_ACTIONS = ['edit', 'delete', KB_MANAGE_ACTION]

interface KnowledgeListRow {
    id: string | number;
    state: number;
    actions?: string[];
    name: string;
    description?: string;
    update_time: string;
    user_name?: string;
    has_abnormal_files?: boolean;
}

const doing = {} // Record knowledge bases being copied
export default function KnowledgeFile() {
    const [open, setOpen] = useState(false);
    const { user } = useContext(userContext);

    const navigate = useNavigate()
    const [settingsOpen, setSettingsOpen] = useState(false);
    const [currentSettingLib, setCurrentSettingLib] = useState(null);
    const [copyLoadingId, setCopyLoadingId] = useState<string | null>(null);
    // New: Control Select dropdown state to avoid occasional popup issues
    const [selectOpenId, setSelectOpenId] = useState<string | null>(null);
    const [modalKey, setModalKey] = useState(0); // New: Used to force re-render of modal
    const [fileStatusFilter, setFileStatusFilter] = useState<string | null>(null);
    const selectLabels = useSelectLabels();
    // Permission management state
    const [permDialogOpen, setPermDialogOpen] = useState(false);
    const [permTarget, setPermTarget] = useState<{ id: string; name: string } | null>(null);
    const {
        actions: rowActions,
        loading: rowActionsLoading,
        load: loadRowActions,
    } = useLazyResourceActions('knowledge_library', KB_ROW_ACTIONS);

    // F027: cursor-based infinite scroll; no `total` / `page` anymore.
    const { data: datalist, loading, hasMore, search, reload, loadMore, filterData } = useInfiniteCursorTable(
        { cancelLoadingWhenReload: true },
        (param) =>
            readFileLibDatabase({
                cursor: param.cursor,
                pageSize: param.pageSize,
                name: param.keyword,
                action: 'visible',
                has_abnormal: param.has_abnormal,
            }),
    )

    // Permission levels for badge display
    // 列表已由后端 get_knowledge 按 ReBAC 过滤；勿再用批量 check 二次过滤，否则与 FGA/缓存短暂不同步时会出现「接口有数据但表格空白」。
    const visibleLibs = datalist;
    const hasAction = (el: KnowledgeListRow, action: string) =>
        Array.isArray(el.actions) && el.actions.includes(action);
    const hasRowAction = (el: KnowledgeListRow, action: string) =>
        rowActions[String(el.id)]?.includes(action) ?? false;
    const canEdit = (el: KnowledgeListRow) =>
        hasRowAction(el, 'edit');
    const canDelete = (el: KnowledgeListRow) =>
        hasRowAction(el, 'delete');
    // PRD 3.3.3：「创建」「复制」与 ReBAC 编辑权解耦，由 WEB_MENU `create_knowledge` 控制（对齐「创建应用」+ 列表「复制」）
    const canCreateLibrary =
        user.role === 'admin' ||
        (user.web_menu || []).includes('create_knowledge');
    const canReadRow = (el: KnowledgeListRow) =>
        hasAction(el, 'visible');
    /** 与 apps.tsx 一致：create_knowledge 菜单 + 对目标库具备使用/可见（can_read） */
    const canUseCopy = (el: KnowledgeListRow) => canCreateLibrary && canReadRow(el);
    const canManageKb = (el: KnowledgeListRow) =>
        hasRowAction(el, KB_MANAGE_ACTION);
    const isLibraryBusy = (el: KnowledgeListRow) =>
        [KnowledgeBaseStatus.Copying, KnowledgeBaseStatus.Unpublished].includes(el.state);
    const canCopy = (el: KnowledgeListRow) =>
        canUseCopy(el) && el.state === KnowledgeBaseStatus.Published;
    const hasRowActions = (el: KnowledgeListRow) =>
        canManageKb(el) || canCopy(el) || canEdit(el) || canDelete(el);
    const showOperationsColumn = visibleLibs.length > 0;

    // Enable polling during copying
    useEffect(() => {
        const todos = datalist.reduce((prev, curr) => {
            if (curr.state === KnowledgeBaseStatus.Copying) {
                prev.push({ id: curr.id, name: curr.name })
            }
            return prev
        }, [])

        todos.map(todo => {
            if (doing[todo.id]) {
                const lib = datalist.find(item => item.id === todo.id);
                if (lib && lib.state !== KnowledgeBaseStatus.Copying) {
                    toast.show({ type: 'success', message: String(t('copyCompleted', { name: todo.name }) ?? '') })
                    delete doing[todo.id]
                }
            }
        })

        let timer = null
        if (todos.length > 0) {
            timer = setTimeout(() => {
                reload()
            }, 5000);
        }

        return () => {
            clearTimeout(timer)
        }
    }, [datalist])

    const handleDelete = (id) => {
        bsConfirm({
            title: t('prompt'),
            desc: t('lib.confirmDeleteLibrary', { ns: 'bs' }),
            onOk(next) {
                captureAndAlertRequestErrorHoc(deleteFileLib(id).then(res => {
                    reload();
                }));
                next()
            },
        })
    }

    const handleOpenSettings = (lib) => {
        console.log("=== handleOpenSettings execution started ===");
        console.log("Clicked lib ID:", lib.id);
        // 1. Deep copy: Completely break reference association with original lib (solving nested property reference issues)
        const newCurrentLib = JSON.parse(JSON.stringify(lib));
        // 2. Inject unique identifier: Ensure currentSettingLib reference is absolutely unique even if data is identical
        newCurrentLib.__updateKey = Date.now(); // Generate different timestamp for each click

        setCurrentSettingLib(newCurrentLib); // Now passing a completely new object reference
        setSettingsOpen(true);
        setModalKey(prev => prev + 1); // Keep modalKey to ensure modal re-mounts
        console.log("handleOpenSettings called with lib:", newCurrentLib); // Verify print
    };

    const handleSettingsClose = (isOpen) => {
        console.log("handleSettingsClose called with isOpen:", isOpen);
        setSettingsOpen(isOpen);
        if (!isOpen) {
            setCurrentSettingLib(null);
            setSelectOpenId(null);
            console.log("Settings modal closed and state cleared");
        }
    };

    // Cache the active tab hint before entering detail; the parent's
    // ``defaultValue`` reads ``LibPage.type`` to restore the file/qa tab.
    // F027: ``page`` is now an opaque cursor token, not restorable, so we
    // only persist the type marker.
    const handleCachePage = () => {
        window.LibPage = { type: 'file' }
    }

    useEffect(() => {
        // F027: ``useInfiniteCursorTable`` auto-loads page 1 on mount; we no
        // longer try to restore a specific page on return from detail. Just
        // drop the marker so subsequent navigations get a fresh first page.
        delete window.LibPage;
    }, [])

    const { t, i18n } = useTranslation('knowledge');
    const fileStatusFilterOptions = [
        { label: t('fileStatusFilterAll'), value: 'all' },
        { label: t('fileStatusAbnormal'), value: 'abnormal' },
    ];
    useEffect(() => {
        i18n.loadNamespaces('knowledge');
    }, [i18n]);

    const handleRowMenuOpenChange = async (el: KnowledgeListRow, isOpen: boolean) => {
        const resourceId = String(el.id);
        if (!isOpen) {
            setSelectOpenId((current) => current === resourceId ? null : current);
            return;
        }
        if (isLibraryBusy(el) || copyLoadingId === resourceId) return;

        setSelectOpenId(resourceId);
        const result = await loadRowActions(resourceId);
        if (result.hasError) {
            setSelectOpenId((current) => current === resourceId ? null : current);
            toast.show({ type: 'error', message: String(t('error.checkFailed', { ns: 'permission' }) ?? '') });
        }
    };

    // Copy knowledge base
    const handleCopy = async (elem) => {
        const newName = `${elem.name}${t('copySuffix')}`;
        if (newName.length > 200) {
            notification.open({ type: 'error', title: String(t('operationFailed') ?? ''), description: String(t('copyNameExceedsLimit') ?? '') });

            // Reset all related states
            setSelectOpenId(null);
            setCopyLoadingId(null);

            // Force re-render of Select component
            setModalKey(prev => prev + 1);
            return;
        }

        setCopyLoadingId(String(elem.id));
        doing[elem.id] = true;

        try {
            await captureAndAlertRequestErrorHoc(copyLibDatabase(elem.id, newName));
            reload();
        } catch (error) {
            toast.show({ type: 'error', message: String(t('copyFailed') ?? '') });
        } finally {
            setCopyLoadingId(null);
            setSelectOpenId(null);
            // Ensure Select component resets
            setModalKey(prev => prev + 1);
        }
    }

    useEffect(() => {
        console.log("settingsOpen state changed:", settingsOpen);
        console.log("currentSettingLib:", currentSettingLib);
        console.log("modalKey:", modalKey);
    }, [settingsOpen, currentSettingLib, modalKey]);

    const renderRowMenu = (el: KnowledgeListRow) => {
        const resourceId = String(el.id);
        if (rowActionsLoading[resourceId]) {
            return <DropdownItem disabled icon={<Outlined.Loading className="animate-spin" />}>
                {t('knowledgeRowActions.loading', { ns: 'permission' })}
            </DropdownItem>;
        }
        if (!hasRowActions(el)) {
            return <DropdownItem disabled>{t('knowledgeRowActions.empty', { ns: 'permission' })}</DropdownItem>;
        }
        const hasLeadingItems = canManageKb(el) || canCopy(el) || canEdit(el);
        return <>
            {canManageKb(el) && (
                <DropdownItem icon={<Shield />} onSelect={() => {
                    setPermTarget({ id: resourceId, name: el.name });
                    setPermDialogOpen(true);
                    setModalKey(prev => prev + 1);
                }}>
                    {t('managePermission', { ns: 'permission' })}
                </DropdownItem>
            )}
            {canCopy(el) && (
                <DropdownItem icon={<Outlined.Copy />} disabled={copyLoadingId === resourceId} onSelect={() => handleCopy(el)}>
                    {t('lib.copy', { ns: 'bs' })}
                </DropdownItem>
            )}
            {canEdit(el) && (
                <DropdownItem icon={<Outlined.Setting />} onSelect={() => handleOpenSettings(el)}>
                    {t('settings')}
                </DropdownItem>
            )}
            {canDelete(el) && <>
                {hasLeadingItems && <DropdownSeparator />}
                <DropdownItem danger icon={<Outlined.Delete />} onSelect={() => handleDelete(el.id)}>
                    {t('delete')}
                </DropdownItem>
            </>}
        </>;
    };

    return (
        <div className="relative">
            {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                <Outlined.Loading  className="size-4 animate-spin"/>
            </div>}
            <div className="h-[calc(100vh-128px-var(--license-banner-h,0px))] overflow-y-auto pb-20">
                <div className="flex justify-end gap-4 items-center absolute right-0 top-[-40px]">
                    <SearchInput placeholder={t('lib.searchPlaceholder', { ns: 'bs' })} onChange={(e) => search(e.target.value)} />
                    {canCreateLibrary && <Button onClick={() => setOpen(true)}>{t('create', { ns: 'bs' })}</Button>}
                </div>
                <Table noScroll>
                    <TableHeader>
                        <TableRow>
                            <TableHead>{t('lib.libraryName', { ns: 'bs' })}</TableHead>
                            <TableHead>{t('updateTime')}</TableHead>
                            <TableHead>{t('lib.createUser', { ns: 'bs' })}</TableHead>
                            <TableHead>
                                <div className="flex items-center">
                                    {t('fileStatus')}
                                    <Select
                                        {...selectLabels}
                                        options={fileStatusFilterOptions}
                                        value={fileStatusFilter}
                                        onChange={(value) => {
                                            const next = value == null ? null : String(value);
                                            setFileStatusFilter(next);
                                            filterData({ has_abnormal: next === 'abnormal' ? true : undefined })
                                        }}
                                        trigger={
                                            <button
                                                type="button"
                                                className="ml-3 inline-flex outline-none"
                                                aria-label={t('fileStatusFilterLabel', {
                                                    value: fileStatusFilterOptions.find(option => option.value === fileStatusFilter)?.label ?? t('fileStatusFilterAll'),
                                                })}
                                            >
                                                <FilterIcon className={fileStatusFilter ? 'text-primary' : 'text-gray-400'} />
                                            </button>
                                        }
                                    />
                                </div>
                            </TableHead>
                            {showOperationsColumn && (
                                <TableHead className="text-right">{t('operations')}</TableHead>
                            )}
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {visibleLibs.map((el: KnowledgeListRow) => (
                            <TableRow
                                key={el.id}
                                className=""
                                onClick={() => {
                                    if (!canReadRow(el)) return;
                                    if ([KnowledgeBaseStatus.Copying, KnowledgeBaseStatus.Unpublished].includes(el.state)) return;
                                    window.libname = [el.name, el.description];
                                    navigate(`/filelib/${el.id}`);
                                    handleCachePage();
                                }}
                            >
                                <TableCell
                                    className="font-medium max-w-[200px]"
                                >
                                    <div className="flex items-center gap-2">
                                        <div className="flex size-8 shrink-0 items-center justify-center rounded-[8px] bg-fill-2 group-odd:bg-white dark:group-odd:bg-fill-2 text-text-2">
                                            <Outlined.BookOpenText size={16} className="shrink-0" />
                                        </div>
                                        <div>
                                            <div className="truncate max-w-[500px] w-[264px] text-[14px] font-medium pt-2">
                                                {el.name}
                                            </div>
                                            <KnowledgeTooltip
                                                side="top"
                                                content={el.description?.length > 30 ? el.description : ''}
                                            >
                                                <div className="truncate max-w-[500px] text-[12px] text-[#5A5A5A] pt-1">
                                                    {el.description || ''}
                                                </div>
                                            </KnowledgeTooltip>
                                        </div>
                                    </div>
                                </TableCell>

                                <TableCell
                                    className="text-[#5A5A5A]"
                                >
                                    {el.update_time.replace('T', ' ')}
                                </TableCell>

                                <TableCell
                                    className="max-w-[300px] break-all"
                                >
                                    <div className="truncate-multiline text-[#5A5A5A]">{el.user_name || '--'}</div>
                                </TableCell>

                                <TableCell>
                                    <FileAbnormalStatusCell hasAbnormalFiles={el.has_abnormal_files} />
                                </TableCell>

                                {showOperationsColumn && <TableCell className="text-right">
                                    <div className="flex items-center justify-end gap-2">
                                        {(isLibraryBusy(el) || canReadRow(el)) && (
                                            // Menu clicks bubble through the portal; keep them off the row's onClick.
                                            <span className="contents" onClick={(e) => e.stopPropagation()}>
                                                <Dropdown
                                                    key={`${el.id}-${modalKey}`}
                                                    align="end"
                                                    disabled={copyLoadingId === String(el.id)}
                                                    open={selectOpenId === String(el.id)}
                                                    onOpenChange={(isOpen) => void handleRowMenuOpenChange(el, isOpen)}
                                                    menu={renderRowMenu(el)}
                                                >
                                                    <Button
                                                        variant="text"
                                                        color="default"
                                                        size="large"
                                                        iconOnly
                                                        aria-label={t('more', { ns: 'bs' })}
                                                        className="relative"
                                                    >
                                                        {[KnowledgeBaseStatus.Copying, KnowledgeBaseStatus.Unpublished].includes(el.state) ? (
                                                            <>
                                                                <Outlined.Loading className="animate-spin" />
                                                                <div className="absolute -top-8 left-1/2 transform -translate-x-1/2 bg-white text-gray-800 text-xs px-2 py-1 rounded whitespace-nowrap border border-gray-300 shadow-sm">
                                                                    {t('copying')}
                                                                </div>
                                                            </>
                                                        ) : (
                                                            <Outlined.More />
                                                        )}
                                                    </Button>
                                                </Dropdown>
                                            </span>
                                        )}
                                    </div>
                                </TableCell>}
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
                {/* F027: infinite-scroll trigger lives INSIDE the
                    `overflow-y-auto` scroll container so IntersectionObserver
                    tracks in-container scroll. Outside-container placement
                    keeps the footer always-visible and stalls pagination. */}
                {hasMore && <LoadMore onScrollLoad={loadMore} />}
            </div>
            <div className="bisheng-table-footer px-6 bg-background-login">
                <div className="flex items-center gap-2">
                    <p className="desc">{t('lib.libraryCollection', { ns: 'bs' })}</p>
                </div>
            </div>

            {/* Create modal */}
            <KnowledgeLibraryDialog
                datalist={datalist}
                open={open}
                onOpenChange={setOpen}
                onLoadEnd={() => { }}
                mode="create"
            />

            {/* Edit (Settings) modal - using key to force re-render */}
            {settingsOpen && (
                <KnowledgeLibraryDialog
                    key={`settings-modal-${modalKey}`}
                    datalist={datalist}
                    open={settingsOpen}
                    onOpenChange={handleSettingsClose}
                    onLoadEnd={reload}
                    mode="edit"
                    currentLib={currentSettingLib}
                />
            )}

            {/* Permission management dialog */}
            {permTarget && (
                <PermissionDialog
                    open={permDialogOpen}
                    onOpenChange={setPermDialogOpen}
                    resourceType="knowledge_library"
                    resourceId={permTarget.id}
                    resourceName={permTarget.name}
                />
            )}
        </div>
    );
}
