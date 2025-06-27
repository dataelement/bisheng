import { LoadIcon } from "@/components/bs-icons";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Checkbox } from "@/components/bs-ui/checkBox";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/bs-ui/dialog";
import { Switch } from "@/components/bs-ui/switch";
import { message, useToast } from "@/components/bs-ui/toast/use-toast";
import { ArrowLeft, SquarePen } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import 'react-quill/dist/quill.snow.css';
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import { Label } from "@/components/bs-ui/label";
import ShadTooltip from "../../components/ShadTooltipComponent";
import { Button, LoadButton } from "../../components/bs-ui/button";
import { Input, InputList, SearchInput, Textarea } from "../../components/bs-ui/input";
import AutoPagination from "../../components/bs-ui/pagination/autoPagination";
import * as XLSX from 'xlsx';
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../components/bs-ui/table";
import { deleteQa, generateSimilarQa, getQaDetail, getQaFile, getQaFilePreview, getQaList, postImportQaFile, updateKnowledgeApi, updateQa, updateQaStatus } from "../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import { useDebounce, useTable } from "../../util/hook";
import { LoadingIcon } from "@/components/bs-icons/loading";
import KnowledgeBaseSettingsDialog from "./components/EditKnowledgeDialog";
import { downloadFile, formatDate, processImageUrlsSafely } from "@/util/utils";
import SimpleUpload from "@/components/bs-ui/upload/simple";
import { checkSassUrl } from "@/components/bs-comp/FileView";
import { generateUUID } from "@/components/bs-ui/utils";
import RichText from "@/components/bs-comp/richText";
import RichInput from "./components/RichInput/index";
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
    
    const handleAnswerChange = (value) => {
        setForm((prevForm) => ({
            ...prevForm,
            answer: value
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
                description: t('max10000CharactersForAnswer')
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
                        {/* <Textarea
                            name="answer"
                            className={`col-span-3 h-36 ${error.answer && 'border-red-400'}`}
                            value={form.answer}
                            onChange={handleInputChange}
                        /> */}
                        <RichInput
                            className={`col-span-3 h-36 ${error.answer && 'border-red-400'}`}
                            value={processImageUrlsSafely(form.answer, __APP_ENV__.BASE_URL)}
                            onChange={handleAnswerChange}
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

    const { id } = useParams();
    const [selectedItems, setSelectedItems] = useState([]); // 存储选中的项
    const [selectAll, setSelectAll] = useState(false); // 全选状态
    const editRef = useRef(null)
    const importRef = useRef(null)
    const [libInfo, setLibInfo] = useState({ name: '', desc: '' })
    const [open, setOpen] = useState(false)
    const { message } = useToast()
    const [hasPermission, setHasPermission] = useState(false)

    const { page, pageSize, data: datalist, total, loading, setPage, search, reload, refreshData } = useTable({}, (param) =>
        getQaList(id, param).then(res => {
            setHasPermission(res.writeable)
            setSelectedItems([]);
            setSelectAll(false);
            return res
        })
    )

    // 轮询
    useEffect(() => {
        const runing = datalist.some(item => item.status === 2)
        if (runing) {
            const timer = setTimeout(() => {
                reload()
            }, 5000)
            return () => clearTimeout(timer)
        }
    }, [datalist])

    useEffect(() => {
        // @ts-ignore
        const [libname, libdesc] = window.libname || [] // 临时记忆
        if (libname) {
            localStorage.setItem('libname', libname)
            localStorage.setItem('libdesc', libdesc)
        }
        setLibInfo({ name: libname || localStorage.getItem('libname'), desc: libdesc || localStorage.getItem('libdesc') })
    }, [])

    const handleCheckboxChange = (id) => {
        setSelectedItems((prevSelectedItems) => {
            if (prevSelectedItems.includes(id)) {
                return prevSelectedItems.filter(item => item !== id);
            } else {
                return [...prevSelectedItems, id];
            }
        });
    };

    const handleSelectAll = () => {
        if (selectAll) {
            setSelectedItems([]);
        } else {
            setSelectedItems(datalist.map(item => item.id));
        }
        setSelectAll(!selectAll);
    };

    useEffect(() => {
        setSelectedItems([]);
        setSelectAll(false);
    }, [page]);

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
        bsConfirm({
            desc: t('confirmDeleteSelectedQaData'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(deleteQa(selectedItems).then(res => {
                    reload();
                }));
                next();
            },
        });
    };

    const {toast} = useToast()


    const handleStatusClick = useDebounce(async (id: number, checked: boolean) => {
        const targetStatus = checked ? 1 : 0;
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
            })
            refreshData(item => item.id === id, {
                status: 3
            });
        }
    }, 300, false)
    
    const handleSave = (form) => {
        captureAndAlertRequestErrorHoc(updateKnowledgeApi({
            knowledge_id: Number(id),
            name: form.name,
            description: form.desc
        })).then((res) => {
        if (!res) return
            // api
            setLibInfo(form)
            setOpen(false)
            message({ variant: 'success', description: t('saved') })
            localStorage.setItem('libname', form.name)
            localStorage.setItem('libdesc', form.desc)
        })
    }

    return <div className="relative px-2 pt-4 size-full">
        {/* {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <LoadingIcon />
        </div>} */}
        <div className="h-full bg-background-login">
            <div className="flex justify-between">
                <div className="flex justify-between items-center mb-4">
                    <div className="flex items-center">
                        <ShadTooltip content={t('back')} side="top">
                            <button className="extra-side-bar-buttons w-[36px]" onClick={() => { }} >
                                <Link to='/filelib'><ArrowLeft className="side-bar-button-size" /></Link>
                            </button>
                        </ShadTooltip>
                        <div>
                            <div className="group flex items-center">
                                <span className="text-gray-700 text-sm font-black pl-4 dark:text-white">{libInfo.name}</span>
                                {/* edit dialog */}
                                <Dialog open={open} onOpenChange={setOpen} >
                                    <DialogTrigger asChild>
                                        <Button variant="ghost" size="icon" className="group-hover:visible invisible"><SquarePen className="w-4 h-4" /></Button>
                                    </DialogTrigger>
                                    {
                                        open && <KnowledgeBaseSettingsDialog initialName={libInfo.name} initialDesc={libInfo.desc} onSave={handleSave}></KnowledgeBaseSettingsDialog>
                                    }
                                </Dialog>
                            </div>
                            <p className="max-w-96 pl-4 text-muted-foreground text-sm truncate">{libInfo.desc}</p>
                        </div>
                    </div>
                </div>
                <div className="flex justify-between items-center mb-4">
                    <div className={selectedItems.length ? 'visible' : 'invisible'}>
                        <span className="pl-1 text-sm">{t('selectedItems')}: {selectedItems.length}</span>
                        <Button variant="link" className="text-red-500 ml-2" onClick={handleDeleteSelected}>{t('batchDelete')}</Button>
                    </div>
                    <div className="flex gap-4 items-center">
                        <SearchInput placeholder={t('qaContent')} onChange={(e) => search(e.target.value)}></SearchInput>
                        <Button variant="outline" className="px-8" onClick={() => importRef.current.open()}>{t('importQa')}</Button>
                        <Button variant="outline" className="px-8" onClick={() => {
                            getQaFile(id).then(res => {
                                const fileUrl = res.file_list[0];
                                downloadFile(checkSassUrl(fileUrl), `${libInfo.name} ${formatDate(new Date(), 'yyyy-MM-dd')}.xlsx`);
                            })
                        }}>{t('exportQa')}</Button>
                        <Button className="px-8" onClick={() => editRef.current.open()}>{t('createQA')}</Button>
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
                            <TableHead className="w-[130px] flex items-center gap-4">{t('type')}</TableHead>
                            <TableHead>{t('creationTime')}</TableHead>
                            <TableHead>{t('updateTime')}</TableHead>
                            <TableHead className="w-20">{t('creator')}</TableHead>
                            <TableHead className="w-[140px]">{t('status')}</TableHead>
                            <TableHead className="text-right pr-6">{t('operations')}</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {datalist.map((el: any) => (
                            <TableRow key={el.id}>
                                <TableCell className="font-medium">
                                    <Checkbox checked={selectedItems.includes(el.id)} onCheckedChange={() => handleCheckboxChange(el.id)} />
                                </TableCell>
                                <TableCell className="font-medium">
                                    <div className="max-h-48 overflow-y-auto scrollbar-hide">
                                        {el.questions}
                                    </div>
                                </TableCell>
                                <TableCell className="font-medium">
                                    <div className="max-h-48 overflow-y-auto scrollbar-hide">
                                        <RichText msg={el.answers}/>
                                    </div>
                                </TableCell>
                                <TableCell>{[t('unknown'), t('manualCreation'), t('APIImport'), t('bulkImport') , t('bulkImport')][el.source]}</TableCell>
                                <TableCell>{el.create_time.replace('T', ' ')}</TableCell>
                                <TableCell>{el.update_time.replace('T', ' ')}</TableCell>
                                <TableCell>{el.user_name}</TableCell>
                                <TableCell>
                                    <div className="flex items-center">
                                        {el.status !== 2 && <Switch
                                            checked={el.status === 1}
                                            onCheckedChange={(bln) => handleStatusClick(el.id, bln)}
                                        />}
                                        {el.status === 2 && (
                                            <span className="ml-2 text-sm">处理中</span>
                                        )}
                                        {el.status === 3 && (
                                            <span className="ml-2 text-sm">未启用，请重试</span>
                                        )}
                                    </div>
                                </TableCell>
                                {hasPermission ? <TableCell className="text-right">
                                    <Button variant="link" onClick={() => editRef.current.edit(el)} className="ml-4">{t('update')}</Button>
                                    <Button variant="link" onClick={() => handleDelete(el.id)} className="ml-4 text-red-500">{t('delete')}</Button>
                                </TableCell> : <TableCell className="text-right">
                                    <Button variant="link" disabled className="ml-4">{t('update')}</Button>
                                    <Button variant="link" disabled className="ml-4 text-red-500">{t('delete')}</Button>
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
                    onChange={(newPage) => setPage(newPage)}
                />
            </div>
        </div>
        <EditQa ref={editRef} knowlageId={id} onChange={reload} />
        <ImportQa ref={importRef} knowlageId={id} onChange={reload} />
    </div >
};
