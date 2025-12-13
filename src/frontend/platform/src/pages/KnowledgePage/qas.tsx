import { checkSassUrl } from "@/components/bs-comp/FileView";
import { LoadIcon } from "@/components/bs-icons";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Checkbox } from "@/components/bs-ui/checkBox";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Switch } from "@/components/bs-ui/switch";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import Tip from "@/components/bs-ui/tooltip/tip";
import { downloadFile, formatDate } from "@/util/utils";
import { ArrowLeft, SquareCheckBig, SquareX, Trash2 } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import ShadTooltip from "../../components/ShadTooltipComponent";
import { Button, LoadButton } from "../../components/bs-ui/button";
import { Input, InputList, SearchInput, Textarea } from "../../components/bs-ui/input";
import AutoPagination from "../../components/bs-ui/pagination/autoPagination";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../components/bs-ui/table";
import { deleteQa, generateSimilarQa, getQaDetail, getQaFile, getQaList, updateQa, updateQaStatus } from "../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import { useTable } from "../../util/hook";
import { ImportQa } from "./components/ImportQa";

const defaultQa = {
    question: '',
    similarQuestions: [''],
    answer: ''
}

// 添加&编辑qa
const EditQa = forwardRef(function ({ knowlageId, onChange }, ref) {
    const { t } = useTranslation('knowledge');
    const [open, setOpen] = useState(false);
    const [form, setForm] = useState({ ...defaultQa });
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState({
        question: false,
        answer: false
    });

    const idRef = useRef('');
    const sourceRef = useRef('');
    useImperativeHandle(ref, () => ({
        open() {
            setOpen(true);
        },
        edit(item) {
            const { id, source } = item;
            idRef.current = id;
            sourceRef.current = source;
            setOpen(true);

            getQaDetail(id).then(res => {
                const { questions, answers } = res;
                const [question, ...similarQuestions] = questions;
                setForm({
                    question,
                    similarQuestions: [...similarQuestions, ''],
                    answer: answers
                });
            });
        }
    }));

    const handleInputChange = (e) => {
        const { name, value } = e.target;
        setForm((prevForm) => ({
            ...prevForm,
            [name]: value
        }));
    };

    const handleSimilarQuestionsChange = (list) => {
        setForm((prevForm) => ({
            ...prevForm,
            similarQuestions: list
        }));
    };

    // 模型生成
    const handleModelGenerate = async () => {
        if (!form.question) {
            return message({
                variant: 'warning',
                description: t('pleaseEnterQuestion')
            });
        }
        setLoading(true);
        captureAndAlertRequestErrorHoc(generateSimilarQa(form.question, form.answer).then(res => {
            setForm((prevForm) => {
                const updatedSimilarQuestions = [...prevForm.similarQuestions];
                updatedSimilarQuestions.splice(updatedSimilarQuestions.length - 1, 0, ...res.questions);
                return {
                    ...prevForm,
                    similarQuestions: updatedSimilarQuestions
                };
            });
            setLoading(false);
        }));
    };

    const { message } = useToast();
    const [saveLoad, setSaveLoad] = useState(false);
    const handleSubmit = async () => {
        const isQuestionEmpty = !form.question.trim();
        const isAnswerEmpty = !form.answer.trim();

        if (isQuestionEmpty || isAnswerEmpty) {
            setError({
                question: isQuestionEmpty,
                answer: isAnswerEmpty
            });

            return message({
                variant: 'warning',
                description: t('questionAndAnswerCannotBeEmpty')
            });
        }

        const _similarQuestions = form.similarQuestions.filter((question) => question.trim() !== '');
        if (_similarQuestions.some((q) => q.length > 100)) {
            return message({
                variant: 'warning',
                description: t('max100CharactersForSimilarQuestion')
            });
        }
        if (form.answer.length > 10000) {
            return message({
                variant: 'warning',
                description: t('max1000CharactersForAnswer')
            });
        }

        setSaveLoad(true);
        await captureAndAlertRequestErrorHoc(updateQa(idRef.current, {
            questions: [form.question, ..._similarQuestions],
            answers: [form.answer],
            knowledge_id: knowlageId,
            source: sourceRef.current || 1
        }));

        onChange();
        setSaveLoad(false);
        close();
    };

    const close = () => {
        idRef.current = '';
        sourceRef.current = '';
        setForm({ ...defaultQa });
        setOpen(false);
        setError({
            question: false,
            answer: false
        });
    };

    return (
        <Dialog open={open} onOpenChange={(bln) => bln ? setOpen(bln) : close()}>
            <DialogContent className="sm:max-w-[625px]">
                <DialogHeader>
                    <DialogTitle>{idRef.current ? t('updateQa') : t('createQa')}</DialogTitle>
                </DialogHeader>
                <div className="flex flex-col gap-4 py-2">
                    <div>
                        <label htmlFor="question" className="bisheng-label">
                            <span className="text-red-500">*</span>{t('question')}
                        </label>
                        <Input
                            name="question"
                            className={`col-span-3 ${error.question && 'border-red-400'}`}
                            value={form.question}
                            onChange={handleInputChange}
                        />
                    </div>
                    <div>
                        <label htmlFor="similarQuestions" className="bisheng-label">{t('similarQuestions')}</label>
                        <InputList
                            className="max-h-60 overflow-y-auto"
                            value={form.similarQuestions}
                            onChange={handleSimilarQuestionsChange}
                        />
                        <Button className="mt-2" size="sm" onClick={handleModelGenerate} disabled={loading}>
                            {loading && <LoadIcon />} {t('aiGenerate')}
                        </Button>
                    </div>
                    <div>
                        <label htmlFor="answer" className="bisheng-label">
                            <span className="text-red-500">*</span>{t('answer')}
                        </label>
                        <Textarea
                            name="answer"
                            className={`col-span-3 h-36 ${error.answer && 'border-red-400'}`}
                            value={form.answer}
                            onChange={handleInputChange}
                        />
                    </div>
                </div>
                <DialogFooter>
                    <DialogClose>
                        <Button variant="outline" className="px-11" type="button" onClick={close}>
                            {t('cancel2')}
                        </Button>
                    </DialogClose>
                    <LoadButton loading={saveLoad} type="submit" className="px-11" onClick={handleSubmit}>
                        {t('confirm')}
                    </LoadButton>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
});


export default function QasPage() {
    const { t } = useTranslation('knowledge')

    const { id } = useParams()
    const [title, setTitle] = useState('')
    const [selectedItems, setSelectedItems] = useState([]);
    const [selectAll, setSelectAll] = useState(false);
    const editRef = useRef(null)
    const importRef = useRef(null)
    const [hasPermission, setHasPermission] = useState(false)
    const { toast } = useToast();

      const sourceTypeKeys = [
        'source_unknown',      // 0: 未知
        'source_manual',       // 1: 手动创建
        'source_annotation_import', // 2: 标注导入
        'source_api_import',   // 3: api导入
        'source_batch_import'  // 4: 批量导入
    ];

    const { page, pageSize, data: datalist, total, loading, setPage, search, reload, refreshData } = useTable({}, (param) =>
        getQaList(id, param).then(res => {
            setHasPermission(res.writeable)
            return res
        })
    )

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
        if (!selectedItems.length) return;

        try {
            const itemsToEnable = selectedItems.filter(id => {
                const item = datalist.find(el => el.id === id);
                return !item || item.status !== 1;
            });

            if (itemsToEnable.length === 0) {
                toast({ variant: 'info', description: t('theSelectedItemsAlreadyEnabled') });
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
                toast({ variant: 'success', description: t('successfullyEnabled', { count: successCount }) });
            }
            if (failedIds.length > 0) {
                toast({
                    variant: 'warning',
                    description: t('someItemsFailedToEnable', { ids: failedIds.join(', ') })
                });
            }
        } catch (error) {
            toast({ variant: 'error', description: t('batchEnableOperationFailed') });
        }
    };

    const handleDisableSelected = async () => {
        if (!selectedItems.length) return;

        try {
            const itemsToDisable = selectedItems.filter(id => {
                const item = datalist.find(el => el.id === id);
                return !item || item.status !== 0; // 0 = Disabled
            });

            if (itemsToDisable.length === 0) {
                toast({ variant: 'info', description: t('theSelectedItemsAlreadyDisabled') });
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
                toast({ variant: 'success', description: t('successfullyDisabled', { count: successCount }) });
            }
            if (failedIds.length > 0) {
                toast({
                    variant: 'warning',
                    description: t('someItemsFailedToDisable', { ids: failedIds.join(', ') })
                });
            }
        } catch (error) {
            toast({ variant: 'error', description: t('batchDisableOperationFailed') });
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
        bsConfirm({
            desc: t('confirmDeleteSelectedQaData'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(deleteQa([id]).then(res => {
                    reload()
                }))
                next()
            },
        })
    }

    const handleDeleteSelected = () => {
        if (!selectedItems.length) return;

        bsConfirm({
            desc: t('confirmDeleteSelectedQaData', { count: selectedItems.length }), // Display the total number of selected items
            onOk(next) {
                captureAndAlertRequestErrorHoc(
                    deleteQa(selectedItems) // Pass all selected IDs
                        .then(res => {
                            reload(); // Refresh all data
                            setSelectedItems([]); // Clear selected items
                            setSelectAll(false);
                        })
                );
                next();
            },
        });
    };

    const handleStatusClick = async (id: number, checked: boolean) => {
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
            toast({
                variant: 'error',
                description: error
            });
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
                            <ShadTooltip content={t('back')} side="top">
                                <button className="extra-side-bar-buttons w-[36px]" onClick={() => { }} >
                                    <Link to='/filelib'><ArrowLeft className="side-bar-button-size" /></Link>
                                </button>
                            </ShadTooltip>
                            <span className="text-gray-700 text-sm font-black pl-4 dark:text-white">{title}</span>
                        </div>
                    </div>
                    <div className={selectedItems.length ? 'visible' : 'invisible'}>
                        <Tip content={!hasPermission && t('noOperationPermission')} side='top'>
                            <Button variant="outline" className="disabled:pointer-events-auto ml-2" disabled={!hasPermission} onClick={handleDeleteSelected}>
                                <Trash2 className="mr-2 h-4 w-4" ></Trash2> {t('delete')}
                            </Button>
                        </Tip>
                        <Tip content={!hasPermission && t('noOperationPermission')} side='top'>
                            <Button variant="outline" className="disabled:pointer-events-auto ml-2" disabled={!hasPermission} onClick={handleDisableSelected}>
                                <SquareX className="mr-2 h-4 w-4" /> {t('disable')}
                            </Button>
                        </Tip>
                        <Tip content={!hasPermission && t('noOperationPermission')} side='top'>
                            <Button variant="outline" className="disabled:pointer-events-auto ml-2" disabled={!hasPermission} onClick={handleEnableSelected}>
                                <SquareCheckBig className="mr-2 h-4 w-4" /> {t('enable')}
                            </Button>
                        </Tip>
                    </div>
                    <div className="flex justify-between items-center mb-4">
                        <div className="flex gap-4 items-center">
                            <SearchInput placeholder={t('qaContent')} onChange={(e) => search(e.target.value)}></SearchInput>
                            <Tip content={!hasPermission && t('noOperationPermission')} side='top'>
                                <Button variant="outline" disabled={!hasPermission} className="disabled:pointer-events-auto px-8" onClick={() => importRef.current.open()}>{t('import')}</Button>
                            </Tip>
                            <Button variant="outline" className="px-8" onClick={() => {
                                getQaFile(id).then(res => {
                                    const fileUrl = res.file_list[0];
                                    downloadFile(checkSassUrl(fileUrl), `${title} ${formatDate(new Date(), 'yyyy-MM-dd')}.xlsx`);
                                })
                            }}>{t('export')}</Button>
                            <Tip content={!hasPermission && t('noOperationPermission')} side='top'>
                                <Button className="disabled:pointer-events-auto px-8" disabled={!hasPermission} onClick={() => editRef.current.open()}>{t('createQA')}</Button>
                            </Tip>
                        </div>
                    </div>
                </div>
                <div className="overflow-y-auto h-[calc(100vh-132px)] pb-20">
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className="w-8">
                                    <Checkbox checked={selectAll} onCheckedChange={handleSelectAll} />
                                </TableHead>
                                <TableHead className="w-[340px]">{t('question')}</TableHead>
                                <TableHead className="w-[340px]">{t('answer')}</TableHead>
                                <TableHead>{t('type')}</TableHead>
                                <TableHead>{t('updateTime')}</TableHead>
                                <TableHead>{t('createUser')}</TableHead>
                                <TableHead className="text-right pr-6">{t('operations')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {datalist.map(el => (
                                <TableRow key={el.id} className={hasPermission ? "hover:bg-gray-100" : ""}>
                                    <TableCell className="font-medium" onClick={(e) => e.stopPropagation()}>
                                        <Checkbox
                                            checked={selectedItems.includes(el.id)}
                                            onCheckedChange={() => handleCheckboxChange(el.id)}
                                            onClick={(e) => e.stopPropagation()}
                                        />
                                    </TableCell>

                                    <TableCell
                                        className="font-medium cursor-pointer"
                                        onClick={() => hasPermission && editRef.current.edit(el)}
                                    >
                                        <div className="max-h-48 overflow-y-auto scrollbar-hide">
                                            {el.questions}
                                        </div>
                                    </TableCell>

                                    <TableCell
                                        className="font-medium cursor-pointer"
                                        onClick={() => hasPermission && editRef.current.edit(el)}
                                    >
                                        <div className="max-h-48 overflow-y-auto scrollbar-hide">
                                            {el.answers}
                                        </div>
                                    </TableCell>

                                    <TableCell
                                        className="cursor-pointer"
                                        onClick={() => hasPermission && editRef.current.edit(el)}
                                    >
                                        {/* {['未知', '手动创建', '标注导入', 'api导入', '批量导入'][el.source]} */}
                                        {t(sourceTypeKeys[el.source] || sourceTypeKeys[0])}
                                    </TableCell>
                                    <TableCell>{el.update_time.replace('T', ' ')}</TableCell>
                                    <TableCell>{el.user_name}</TableCell>
                                    <TableCell className="text-right">
                                        <div className="flex items-center justify-end gap-2">
                                            <div className="flex items-center">
                                                {el.status !== 2 && (
                                                    <Tip
                                                        content={!hasPermission && t('noOperationPermission')}
                                                        side='top'>
                                                        <div>
                                                            <Switch
                                                                checked={el.status === 1}
                                                                disabled={!hasPermission}
                                                                className="disabled:pointer-events-auto"
                                                                onCheckedChange={(bln) => handleStatusClick(el.id, bln)}
                                                            />
                                                        </div>
                                                    </Tip>
                                                )}
                                                {el.status === 2 && (
                                                    <span className="text-sm">{t('processing')}</span>
                                                )}
                                                {el.status === 3 && (
                                                    <span className="text-sm">{t('notEnabled')}</span>
                                                )}
                                            </div>
                                            <Tip
                                                content={!hasPermission && t('noOperationPermission')}
                                                styleClasses="-translate-x-6"
                                                side='top'>
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    className="disabled:pointer-events-auto"
                                                    disabled={!hasPermission}
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        handleDelete(el.id);
                                                    }}
                                                >
                                                    <Trash2 size={16} />
                                                </Button>
                                            </Tip>
                                        </div>
                                    </TableCell>
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
                        onChange={(newPage) => setPage(newPage)}
                    />
                </div>
            </div>
            <EditQa ref={editRef} knowlageId={id} onChange={reload} />
            <ImportQa ref={importRef} knowlageId={id} onChange={reload} />
        </div>
    );
}
