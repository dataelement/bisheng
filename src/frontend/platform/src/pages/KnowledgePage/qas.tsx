// @ts-strict-ignore
import { Button, SearchInput, notification } from '@bisheng/ui';
import { checkSassUrl } from "@/components/bs-comp/FileView";
import { Outlined } from "bisheng-icons";
import { EditQa } from "./components/EditQa";
import { KnowledgeTooltip } from "./components/KnowledgeTooltip";

import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";

import { downloadFile,formatDate } from "@/util/utils";
import { Checkbox,Switch } from "@bisheng/ui";

import { useEffect,useRef,useState } from "react";
import { useTranslation } from "react-i18next";
import { Link,useParams } from "react-router-dom";



import AutoPagination from "../../components/bs-ui/pagination/autoPagination";
import {
Table,
TableBody,
TableCell,
TableHead,
TableHeader,
TableRow
} from "../../components/bs-ui/table";
import { deleteQa,getQaFile,getQaList,updateQaStatus } from "../../controllers/API";
import { checkResourceActionApi } from "../../controllers/API/permission";
import { showApiError } from "../../controllers/request";
import { useTable } from "../../util/hook";
import { ImportQa } from "./components/ImportQa";

export default function QasPage() {
    const { t } = useTranslation('knowledge')

    const { id } = useParams()
    const [title, setTitle] = useState('')
    const [selectedItems, setSelectedItems] = useState([]);
    const [selectAll, setSelectAll] = useState(false);
    const editRef = useRef(null)
    const importRef = useRef(null)
    const [canEditKb, setCanEditKb] = useState(false)
    const [canDeleteKb, setCanDeleteKb] = useState(false)


      const sourceTypeKeys = [
        'source_unknown',      // 0: 未知
        'source_manual',       // 1: 手动创建
        'source_annotation_import', // 2: 标注导入
        'source_api_import',   // 3: api导入
        'source_batch_import'  // 4: 批量导入
    ];

    const { page, pageSize, data: datalist, total, loading, setPage, search, reload, refreshData } = useTable({}, (param) =>
        getQaList(id, param)
    )
    const hasSelectableActions = canEditKb || canDeleteKb;

    useEffect(() => {
        let cancelled = false;
        const loadPermissions = async () => {
            if (!id) {
                setCanEditKb(false);
                setCanDeleteKb(false);
                return;
            }
            const [editResult, deleteResult] = await Promise.all([
                checkResourceActionApi({ resource_type: 'knowledge_library', resource_id: String(id), action: 'edit' }),
                checkResourceActionApi({ resource_type: 'knowledge_library', resource_id: String(id), action: 'delete' }),
            ]);
            if (cancelled) return;
            setCanEditKb(!!editResult?.allowed);
            setCanDeleteKb(!!deleteResult?.allowed);
        };
        void loadPermissions().catch(showApiError);
        return () => {
            cancelled = true;
        };
    }, [id]);

    // Polling effect to check if any item is in processing status
    useEffect(() => {
        const runing = datalist.some(item => item.status === 2)
        if (runing) {
            const timer = setTimeout(() => {
                reload()
            }, 5000)
            return () => clearTimeout(timer)
        }
    }, [datalist])

    // Modify useEffect to handle title processing
    useEffect(() => {
        // Handle potential format issues with window.libname
        let libName = '';
        if (window.libname) {
            if (Array.isArray(window.libname) && window.libname.length > 0) {
                libName = window.libname[0];
            } else if (typeof window.libname === 'string') {
                libName = window.libname;
            }
            // Store only the name in localStorage
            localStorage.setItem('libname', libName);
        } else {
            libName = localStorage.getItem('libname') || '';
        }
        setTitle(libName || t('unknownKnowledgeBase')); // Provide default text
    }, []);

    const handleEnableSelected = async () => {
        if (!canEditKb) return;
        if (!selectedItems.length) return;

        try {
            const itemsToEnable = selectedItems.filter(id => {
                const item = datalist.find(el => el.id === id);
                return !item || item.status !== 1;
            });

            if (itemsToEnable.length === 0) {
                notification.open({ type: 'info', description: String(t('theSelectedItemsAlreadyEnabled') ?? '') });
                return;
            }

            refreshData(
                item => itemsToEnable.includes(item.id),
                { status: 2 } // Processing status
            );

            const results = await Promise.allSettled(
                itemsToEnable.map(id => updateQaStatus(id, 1)) // 1 = Enable
            );

            const successCount = results.filter(res => res.status === 'fulfilled').length;
            const failedIds = results
                .filter(res => res.status === 'rejected')
                .map((res, idx) => itemsToEnable[idx]);

            await reload();
            setSelectedItems([]);
            setSelectAll(false);

            if (successCount > 0) {
                notification.open({ type: 'success', description: String(t('successfullyEnabled', { count: successCount }) ?? '') });
            }
            if (failedIds.length > 0) {
                notification.open({ type: 'warning', description: String(t('someItemsFailedToEnable', { ids: failedIds.join(', ') }) ?? '') });
            }
        } catch (error) {
            showApiError(error);
        }
    };

    const handleDisableSelected = async () => {
        if (!canEditKb) return;
        if (!selectedItems.length) return;

        try {
            const itemsToDisable = selectedItems.filter(id => {
                const item = datalist.find(el => el.id === id);
                return !item || item.status !== 0; // 0 = Disabled
            });

            if (itemsToDisable.length === 0) {
                notification.open({ type: 'info', description: String(t('theSelectedItemsAlreadyDisabled') ?? '') });
                return;
            }

            const results = await Promise.allSettled(
                itemsToDisable.map(id => updateQaStatus(id, 0))
            );

            const successCount = results.filter(res => res.status === 'fulfilled').length;
            const failedIds = results
                .filter(res => res.status === 'rejected')
                .map((res, idx) => itemsToDisable[idx]);

            await reload();
            setSelectedItems([]);
            setSelectAll(false);

            if (successCount > 0) {
                notification.open({ type: 'success', description: String(t('successfullyDisabled', { count: successCount }) ?? '') });
            }
            if (failedIds.length > 0) {
                notification.open({ type: 'warning', description: String(t('someItemsFailedToDisable', { ids: failedIds.join(', ') }) ?? '') });
            }
        } catch (error) {
            showApiError(error);
        }
    };

    const handleCheckboxChange = (id) => {
        setSelectedItems((prevSelectedItems) => {
            if (prevSelectedItems.includes(id)) {
                return prevSelectedItems.filter(item => item !== id);
            } else {
                return [...prevSelectedItems, id];
            }
        });
    };

    useEffect(() => {
        const currentPageIds = datalist.map(item => item.id);
        const isAllSelected = currentPageIds.length > 0 &&
            currentPageIds.every(id => selectedItems.includes(id));
        setSelectAll(isAllSelected);
    }, [datalist, selectedItems]);

    const handleSelectAll = () => {
        const currentPageIds = datalist.map(item => item.id);
        setSelectedItems(prev => {
            const newSelected = new Set(prev);
            if (selectAll) {
                currentPageIds.forEach(id => newSelected.delete(id));
            } else {
                currentPageIds.forEach(id => newSelected.add(id));
            }
            return Array.from(newSelected);
        });
    };

    useEffect(() => {
        const currentPageIds = datalist.map(item => item.id);
        const isCurrentPageAllSelected = currentPageIds.length > 0 &&
            currentPageIds.every(id => selectedItems.includes(id));
        setSelectAll(isCurrentPageAllSelected);
    }, [datalist, selectedItems]);

    const handleDelete = (id) => {
        if (!canDeleteKb) return;
        bsConfirm({
            desc: t('confirmDeleteSelectedQaData'),
            onOk(next) {
                return deleteQa([id]).then(() => {
                    reload()
                    next()
                })
            },
        })
    }

    const handleDeleteSelected = () => {
        if (!canDeleteKb) return;
        if (!selectedItems.length) return;

        bsConfirm({
            desc: t('confirmDeleteSelectedQaData', { count: selectedItems.length }), // Display the total number of selected items
            onOk(next) {
                return deleteQa(selectedItems) // Pass all selected IDs
                        .then(res => {
                            reload(); // Refresh all data
                            setSelectedItems([]); // Clear selected items
                            setSelectAll(false);
                            next();
                        });
            },
        });
    };

    const handleStatusClick = async (id: number, checked: boolean) => {
        if (!canEditKb) return;
        const targetStatus = checked ? 1 : 0;
        const item = datalist.find(el => el.id === id);

        if (item && item.status === targetStatus) {
            return;
        }

        const isOpening = checked;
        try {
            if (isOpening) {
                refreshData(item => item.id === id, { status: 2 });
            }
            await updateQaStatus(id, targetStatus);
            refreshData(item => item.id === id, { status: targetStatus });
        } catch (error) {
            showApiError(error);
            refreshData(item => item.id === id, {
                status: 3
            });
        }
    };

    return (
        <div className="relative px-2 pt-4 size-full">
            <div className="h-full bg-background-login">
                <div className="flex justify-between">
                    <div className="flex justify-between items-center mb-4">
                        <div className="flex items-center">
                            <KnowledgeTooltip content={t('back')} side="top">
                                <button className="extra-side-bar-buttons w-[36px]" onClick={() => { }} >
                                    <Link to='/filelib'><Outlined.ArrowLeft className="side-bar-button-size" /></Link>
                                </button>
                            </KnowledgeTooltip>
                            <span className="text-gray-700 text-sm font-black pl-4 dark:text-white truncate max-w-80">{title}</span>
                        </div>
                    </div>
                    {selectedItems.length > 0 && hasSelectableActions && (
                    <div>
                        {canDeleteKb && (
                            <Button variant="outlined" className="ml-2" onClick={handleDeleteSelected} color="default">
                                <Outlined.Delete className="mr-2 h-4 w-4" ></Outlined.Delete> {t('delete')}
                            </Button>
                        )}
                        {canEditKb && (
                            <Button variant="outlined" className="ml-2" onClick={handleDisableSelected} color="default">
                                <Outlined.CloseCircle className="mr-2 h-4 w-4" /> {t('disable')}
                            </Button>
                        )}
                        {canEditKb && (
                            <Button variant="outlined" className="ml-2" onClick={handleEnableSelected} color="default">
                                <Outlined.Check className="mr-2 h-4 w-4" /> {t('enable')}
                            </Button>
                        )}
                    </div>
                    )}
                    <div className="flex justify-between items-center mb-4">
                        <div className="flex gap-4 items-center">
                            <SearchInput placeholder={t('qaContent')} onChange={(e) => search(e.target.value)}></SearchInput>
                            {canEditKb && <Button variant="outlined" onClick={() => importRef.current.open()} color="default">{t('import')}</Button>}
                            {canEditKb && <Button variant="outlined" onClick={() => {
                                getQaFile(id).then(res => {
                                    const fileUrl = res.file_list[0];
                                    downloadFile(checkSassUrl(fileUrl), `${title} ${formatDate(new Date(), 'yyyy-MM-dd')}.xlsx`);
                                })
                            }} color="default">{t('export')}</Button>}
                            {canEditKb && <Button onClick={() => editRef.current.open()}>{t('createQA')}</Button>}
                        </div>
                    </div>
                </div>
                <div className="overflow-y-auto h-[calc(100vh-132px-var(--license-banner-h,0px))] pb-20">
                    <Table>
                        <TableHeader>
                            <TableRow>
                                {hasSelectableActions && <TableHead className="w-8">
                                    <Checkbox checked={selectAll} onCheckedChange={handleSelectAll} />
                                </TableHead>}
                                <TableHead className="w-[340px]">{t('question')}</TableHead>
                                <TableHead className="w-[340px]">{t('answer')}</TableHead>
                                <TableHead>{t('type')}</TableHead>
                                <TableHead>{t('updateTime')}</TableHead>
                                <TableHead>{t('createUser')}</TableHead>
                                {hasSelectableActions && (
                                    <TableHead className="text-right pr-6">{t('operations')}</TableHead>
                                )}
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {datalist.map(el => (
                                <TableRow key={el.id} className={canEditKb ? "hover:bg-gray-100" : ""}>
                                    {hasSelectableActions && <TableCell className="font-medium" onClick={(e) => e.stopPropagation()}>
                                        <Checkbox
                                            checked={selectedItems.includes(el.id)}
                                            onCheckedChange={() => handleCheckboxChange(el.id)}
                                            onClick={(e) => e.stopPropagation()}
                                        />
                                    </TableCell>}

                                    <TableCell
                                        className="font-medium cursor-pointer"
                                        onClick={() => canEditKb && editRef.current.edit(el)}
                                    >
                                        <div className="max-h-48 overflow-y-auto scrollbar-hide">
                                            {el.questions}
                                        </div>
                                    </TableCell>

                                    <TableCell
                                        className="font-medium cursor-pointer"
                                        onClick={() => canEditKb && editRef.current.edit(el)}
                                    >
                                        <div className="max-h-48 overflow-y-auto scrollbar-hide">
                                            {el.answers}
                                        </div>
                                    </TableCell>

                                    <TableCell
                                        className="cursor-pointer"
                                        onClick={() => canEditKb && editRef.current.edit(el)}
                                    >
                                        {/* {['未知', '手动创建', '标注导入', 'api导入', '批量导入'][el.source]} */}
                                        {t(sourceTypeKeys[el.source] || sourceTypeKeys[0])}
                                    </TableCell>
                                    <TableCell>{el.update_time.replace('T', ' ')}</TableCell>
                                    <TableCell>{el.user_name}</TableCell>
                                    {hasSelectableActions && <TableCell className="text-right">
                                        <div className="flex items-center justify-end gap-2">
                                            {canEditKb && <div className="flex items-center">
                                                {el.status !== 2 && (
                                                    <Switch
                                                        checked={el.status === 1}
                                                        className="disabled:pointer-events-auto"
                                                        onCheckedChange={(bln) => handleStatusClick(el.id, bln)}
                                                    />
                                                )}
                                                {el.status === 2 && (
                                                    <span className="text-sm">{t('processing')}</span>
                                                )}
                                                {el.status === 3 && (
                                                    <span className="text-sm">{t('notEnabled')}</span>
                                                )}
                                            </div>}
                                            {canDeleteKb && (
                                                <Button variant="text" size="medium" className="disabled:pointer-events-auto" onClick={(e) => {
                                                        e.stopPropagation();
                                                        handleDelete(el.id);
                                                    }} color="default" iconOnly>
                                                    <Outlined.Delete size={16} />
                                                </Button>
                                            )}
                                        </div>
                                    </TableCell>}
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </div>
            </div>
            <div className="bisheng-table-footer px-6 justify-end">
                <div>
                    <AutoPagination
                        page={page}
                        pageSize={pageSize}
                        total={total}
                        showTotal={true}
                        onChange={(newPage) => setPage(newPage)}
                    />
                </div>
            </div>
            <EditQa ref={editRef} knowlageId={id} onChange={reload} />
            <ImportQa ref={importRef} knowlageId={id} onChange={reload} />
        </div>
    );
}
