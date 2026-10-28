import { Button, Dropdown, DropdownItem, DropdownSeparator, SearchInput, notification } from '@bisheng/ui';
import { QaLibraryDialog } from "./components/QaLibraryDialog";
// @ts-strict-ignore
import { Outlined } from "bisheng-icons";
import { Shield } from "lucide-react";
import { KnowledgeHint, KnowledgeTooltip } from "./components/KnowledgeTooltip";


import LoadMore from "@/components/bs-comp/loadMore";
import { PermissionDialog } from "@/components/bs-comp/permission/PermissionDialog";
import { useLazyResourceActions } from "@/components/bs-comp/permission/useResourceActions";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";


import { Table,TableBody,TableCell,TableHead,TableHeader,TableRow } from "@/components/bs-ui/table";


import { userContext } from "@/contexts/userContext";
import { copyQaDatabase,deleteFileLib,readFileLibDatabase } from "@/controllers/API";
import { showApiError } from "@/controllers/request";
import { useInfiniteCursorTable } from "@/util/hook";

import { useContext,useEffect,useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

// Knowledge base status
const enum KnowledgeBaseStatus {
    Unpublished = 0,
    Published = 1,
    Copying = 2,
    Rebuilding = 3,
    Failed = 4
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
}

const doing = {};
interface KnowledgeQaProps {
    toolbarTarget?: HTMLDivElement | null;
}

export default function KnowledgeQa({ toolbarTarget }: KnowledgeQaProps) {
    const [open, setOpen] = useState(false);
    const { user } = useContext(userContext);

    const navigate = useNavigate();
    const [settingsOpen, setSettingsOpen] = useState(false);
    const [currentSettingLib, setCurrentSettingLib] = useState(null);
    const [copyLoadingId, setCopyLoadingId] = useState<string | null>(null);
    const [selectOpenId, setSelectOpenId] = useState<string | null>(null);
    const [modalKey, setModalKey] = useState(0);
    const [permDialogOpen, setPermDialogOpen] = useState(false);
    const [permTarget, setPermTarget] = useState<{ id: string; name: string } | null>(null);
    const {
        actions: rowActions,
        loading: rowActionsLoading,
        load: loadRowActions,
    } = useLazyResourceActions('knowledge_library', KB_ROW_ACTIONS);

    // F027: cursor-based infinite scroll; no `total` / `page` anymore.
    const { data: datalist, loading, hasMore, search, reload, loadMore } = useInfiniteCursorTable(
        { cancelLoadingWhenReload: true },
        (param) =>
            readFileLibDatabase({ cursor: param.cursor, pageSize: param.pageSize, name: param.keyword, type: 1, action: 'visible' }),
    );
    const visibleLibs = datalist;
    const hasAction = (el: KnowledgeListRow, action: string) =>
        Array.isArray(el.actions) && el.actions.includes(action);
    const hasRowAction = (el: KnowledgeListRow, action: string) =>
        rowActions[String(el.id)]?.includes(action) ?? false;
    const canEdit = (el: KnowledgeListRow) =>
        hasRowAction(el, 'edit');
    const canDelete = (el: KnowledgeListRow) =>
        hasRowAction(el, 'delete');
    const canCreateLibrary =
        user.role === 'admin' ||
        (user.web_menu || []).includes('create_knowledge');
    const canReadRow = (el: KnowledgeListRow) =>
        hasAction(el, 'visible');
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

    useEffect(() => {
        const todos = datalist.filter(lib => lib.state === KnowledgeBaseStatus.Copying);
        todos.forEach(lib => {
            if (doing[lib.id] && datalist.find(item => item.id === lib.id && item.state !== KnowledgeBaseStatus.Copying)) {
                notification.open({ type: 'success', description: String(t('copyCompleted', { name: lib.name }) ?? '') });
                delete doing[lib.id];
            }
        });

        const timer = todos.length > 0 ? setTimeout(reload, 5000) : null;
        return () => clearTimeout(timer);
    }, [datalist]);

    const handleDelete = (id) => {
        bsConfirm({
            title: t('prompt'),
            desc: t('lib.confirmDeleteLibrary', { ns: 'bs' }),
            onOk(next) {
                return deleteFileLib(id).then(() => { reload(); next() });
            },
        });
    };

    const handleOpenSettings = (lib) => {
        const newCurrentLib = JSON.parse(JSON.stringify(lib));
        newCurrentLib.__updateKey = Date.now();

        setCurrentSettingLib(newCurrentLib);
        setSettingsOpen(true);
        setModalKey(prev => prev + 1);
        setSelectOpenId(null);
    };

    const handleSettingsClose = (isOpen) => {
        setSettingsOpen(isOpen);
        if (!isOpen) {
            setCurrentSettingLib(null);
        }
    };

    // F027: persist only the tab type — the cursor token isn't restorable.
    const handleCachePage = () => {
        window.LibPage = { type: 'qa' };
    };

    useEffect(() => {
        // F027: useInfiniteCursorTable auto-loads page 1; drop the marker.
        delete window.LibPage;
    }, []);

    const { t } = useTranslation('knowledge');

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
            notification.open({ type: 'error', description: String(t('error.checkFailed', { ns: 'permission' }) ?? '') });
        }
    };

    const handleCopy = async (elem) => {
        const newName = `${elem.name}${t('copySuffix')}`;
        if (newName.length > 200) {
            notification.open({ type: 'error', description: String(t('copyNameExceedsLimit') ?? '') });
            setSelectOpenId(null);
            return;
        }

        setCopyLoadingId(String(elem.id));
        doing[elem.id] = true;

        try {
            await copyQaDatabase(elem.id, newName);
            reload();
        } catch (error) {
            delete doing[elem.id];
            showApiError(error);
        } finally {
            setCopyLoadingId(null);
            setSelectOpenId(null);
        }
    };

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
                    {t('setting')}
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

    const toolbar = (
        <div className="flex items-center justify-end gap-4">
            <SearchInput placeholder={t('lib.searchPlaceholder', { ns: 'bs' })} onChange={(e) => search(e.target.value)} />
            {canCreateLibrary && <Button onClick={() => setOpen(true)}>{t('create', { ns: 'bs' })}</Button>}
        </div>
    );

    return (
        <div className="relative">
            {toolbarTarget ? createPortal(toolbar, toolbarTarget) : toolbarTarget === undefined ? toolbar : null}
            {loading && (
                <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                    <Outlined.Loading  className="size-4 animate-spin"/>
                </div>
            )}
            <div className="h-[calc(100vh-128px-var(--license-banner-h,0px))] overflow-y-auto pb-20">
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>{t('lib.libraryName', { ns: 'bs' })}</TableHead>
                            <TableHead>{t('updateTime')}</TableHead>
                            <TableHead>{t('lib.createUser', { ns: 'bs' })}</TableHead>
                            {showOperationsColumn && (
                                <TableHead className="text-right">{t('operations')}</TableHead>
                            )}
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {visibleLibs.map((el: KnowledgeListRow) => (
                            <TableRow
                                key={el.id}
                                onClick={() => {
                                    if (!canReadRow(el)) return;
                                    if ([KnowledgeBaseStatus.Copying, KnowledgeBaseStatus.Unpublished].includes(el.state)) return;
                                    window.libname = [el.name, el.description];
                                    navigate(`/filelib/qalib/${el.id}`);
                                    handleCachePage();
                                }}
                            >
                                <TableCell className="font-medium max-w-[280px]">
                                    <div className="flex items-center gap-2">
                                            <div className="flex size-8 shrink-0 items-center justify-center rounded-[8px] bg-fill-2 group-odd:bg-white dark:group-odd:bg-fill-2 text-text-2">
                                                <Outlined.Books size={16} className="shrink-0" />
                                            </div>
                                            <div className="min-w-0">
                                                <div className="flex w-[264px] max-w-full items-center gap-1 pt-2 text-[14px] font-medium">
                                                    <span className="min-w-0 truncate">{el.name}</span>
                                                    {el.description && <KnowledgeHint content={el.description} className="shrink-0" />}
                                                </div>
                                                <KnowledgeTooltip content={el.description || ''}>
                                                    <div className="max-w-[400px] truncate pt-1 text-[12px] text-[#5A5A5A]">
                                                        {el.description || ''}
                                                    </div>
                                                </KnowledgeTooltip>
                                            </div>
                                    </div>
                                </TableCell>
                                <TableCell className="text-[#5A5A5A]">
                                    {el.update_time.replace('T', ' ')}
                                </TableCell>
                                <TableCell className="max-w-[300px] break-all">
                                    <div className="truncate-multiline text-[#5A5A5A]">{el.user_name || '--'}</div>
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
                    `overflow-y-auto` scroll container. */}
                {hasMore && <LoadMore onScrollLoad={loadMore} />}
            </div>
            {/* Create modal */}
            <QaLibraryDialog
                datalist={datalist}
                open={open}
                onOpenChange={setOpen}
                onLoadEnd={() => { }}
                mode="create"
            />

            {/* Settings modal */}
            {settingsOpen && (
                <QaLibraryDialog
                    key={`settings-modal-${modalKey}`}
                    datalist={datalist}
                    open={settingsOpen}
                    onOpenChange={handleSettingsClose}
                    onLoadEnd={reload}
                    mode="edit"
                    currentLib={currentSettingLib}
                />
            )}

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
