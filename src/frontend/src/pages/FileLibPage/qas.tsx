import { LoadIcon } from "@/components/bs-icons";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Checkbox } from "@/components/bs-ui/checkBox";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Switch } from "@/components/bs-ui/switch";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { ArrowLeft, Filter } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import ShadTooltip from "../../components/ShadTooltipComponent";
import { Button } from "../../components/bs-ui/button";
import { Input, InputList, SearchInput, Textarea } from "../../components/bs-ui/input";
import AutoPagination from "../../components/bs-ui/pagination/autoPagination";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger } from "../../components/bs-ui/select";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../components/bs-ui/table";
import { deleteFile, readFileByLibDatabase } from "../../controllers/API";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import { useTable } from "../../util/hook";

const defaultQa = {
    question: '',
    similarQuestions: [''],
    answer: ''
}
// 添加&编辑qa
const EditQa = forwardRef(function ({ onChange }, ref) {
    const [open, setOpen] = useState(false);
    const [form, setForm] = useState({ ...defaultQa });
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState({
        question: false,
        answer: false
    });

    const idRef = useRef('')
    useImperativeHandle(ref, () => ({
        open() {
            setOpen(true);
        },
        edit(id) {
            idRef.current = id;
            setOpen(true);
            // 加载表单数据
            setForm({
                question: '嘻嘻嘻',
                similarQuestions: ['1234', ''],
                answer: '呃呃呃呃'
            })
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
        setLoading(true);

        setTimeout(() => {
            setForm((prevForm) => {
                const updatedSimilarQuestions = [...prevForm.similarQuestions];
                updatedSimilarQuestions.splice(updatedSimilarQuestions.length - 1, 0, ...['1111', '2222']);
                return {
                    ...prevForm,
                    similarQuestions: updatedSimilarQuestions
                };
            });
            setLoading(false);
        }, 1000);
    };

    const { message } = useToast()
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
                description: '问题、答案不能为空'
            });
        }

        // 调用接口
        onChange();
        close();
    };

    const close = () => {
        idRef.current = '';
        setForm({ ...defaultQa });
        setOpen(false);
        setError({
            question: false,
            answer: false
        })
    }

    return (
        <Dialog open={open} onOpenChange={(bln) => bln ? setOpen(bln) : close()}>
            <DialogContent className="sm:max-w-[625px]">
                <DialogHeader>
                    <DialogTitle></DialogTitle>
                </DialogHeader>
                <div className="flex flex-col gap-4 py-2">
                    <div>
                        <label htmlFor="question" className="bisheng-label"><span className="text-red-500">*</span>问题</label>
                        <Input name="question" className={`mt-2 col-span-3 ${error.question && 'border-red-400'}`} value={form.question} onChange={handleInputChange} />
                    </div>
                    <div>
                        <label htmlFor="similarQuestions" className="bisheng-label">相似问</label>
                        <InputList
                            value={form.similarQuestions}
                            onChange={handleSimilarQuestionsChange}
                        />
                        <Button className="mt-2" size="sm" onClick={handleModelGenerate} disabled={loading}>
                            {loading && <LoadIcon />}模型生成
                        </Button>
                    </div>
                    <div>
                        <label htmlFor="answer" className="bisheng-label"><span className="text-red-500">*</span>答案</label>
                        <Textarea name="answer" className={`mt-2 col-span-3 ${error.answer && 'border-red-400'}`} value={form.answer} onChange={handleInputChange} />
                    </div>
                </div>
                <DialogFooter>
                    <DialogClose>
                        <Button variant="outline" className="px-11" type="button" onClick={close}>取消</Button>
                    </DialogClose>
                    <Button type="submit" className="px-11" onClick={handleSubmit}>确认导入</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
});


export default function QasPage() {
    const { t } = useTranslation()

    const { id } = useParams()
    const [title, setTitle] = useState('')
    const [selectedItems, setSelectedItems] = useState([]); // 存储选中的项
    const [selectAll, setSelectAll] = useState(false); // 全选状态
    const editRef = useRef(null)

    const { page, pageSize, data: datalist, total, loading, setPage, search, reload, filterData, refreshData } = useTable({}, (param) =>
        readFileByLibDatabase({ ...param, id, name: param.keyword }).then(res => {
            // setHasPermission(res.writeable)
            setSelectedItems([]);
            setSelectAll(false);
            return res
        })
    )

    // filter
    const [filter, setFilter] = useState(999)
    useEffect(() => {
        filterData({ status: filter })
    }, [filter])

    useEffect(() => {
        // @ts-ignore
        const libname = window.libname // 临时记忆
        if (libname) {
            localStorage.setItem('libname', window.libname)
        }
        setTitle(window.libname || localStorage.getItem('libname'))
    }, [])

    const handleDelete = (id) => {
        bsConfirm({
            title: t('prompt'),
            desc: '确认删除所选QA数据!',
            onOk(next) {
                captureAndAlertRequestErrorHoc(deleteFile(id).then(res => {
                    reload()
                }))
                next()
            },
        })
    }

    const selectChange = (id) => {
        setFilter(Number(id))
    }

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

    const handleDeleteSelected = () => {
        bsConfirm({
            title: t('prompt'),
            desc: '确认删除所选QA数据!',
            onOk(next) {
                captureAndAlertRequestErrorHoc(
                    Promise.all(selectedItems.map(id => deleteFile(id)))
                        .then(res => {
                            reload();
                        })
                );
                next();
            },
        });
    };

    return <div className="w-full h-full px-2 pt-4 relative">
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <span className="loading loading-infinity loading-lg"></span>
        </div>}
        <div className="h-full overflow-y-auto pb-10 bg-background-login">
            <div className="flex justify-between items-center mb-4">
                <div className="flex items-center">
                    <ShadTooltip content="back" side="top">
                        <button className="extra-side-bar-buttons w-[36px]" onClick={() => { }} >
                            <Link to='/filelib'><ArrowLeft className="side-bar-button-size" /></Link>
                        </button>
                    </ShadTooltip>
                    <span className=" text-gray-700 text-sm font-black pl-4">{title}</span>
                </div>
                <div className="flex gap-4 items-center">
                    <SearchInput placeholder={t('search')} onChange={(e) => search(e.target.value)}></SearchInput>
                    <Button className="px-8" onClick={() => editRef.current.open()}>创建QA</Button>
                </div>
            </div>
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-8">
                            <Checkbox checked={selectAll} onCheckedChange={handleSelectAll} />
                        </TableHead>
                        <TableHead className="w-[340px]">问题</TableHead>
                        <TableHead className="w-[340px]">答案</TableHead>
                        <TableHead className="w-[130px] flex items-center gap-4">类型
                            {/* Select component */}
                            {/* <Select onValueChange={selectChange}>
                                <SelectTrigger className="border-none w-16">
                                    <Filter size={16} className={`cursor-pointer ${filter === 999 ? '' : 'text-gray-950'}`} />
                                </SelectTrigger>
                                <SelectContent className="w-fit">
                                    <SelectGroup>
                                        <SelectItem value={'999'}>{t('all')}</SelectItem>
                                        <SelectItem value={'1'}>手动创建</SelectItem>
                                        <SelectItem value={'2'}>审计标记</SelectItem>
                                    </SelectGroup>
                                </SelectContent>
                            </Select> */}
                        </TableHead>
                        <TableHead>创建时间</TableHead>
                        <TableHead>更新时间</TableHead>
                        <TableHead className="w-20">创建者</TableHead>
                        <TableHead>状态</TableHead>
                        <TableHead className="text-right pr-6">{t('operations')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {datalist.map(el => (
                        <TableRow key={el.id}>
                            <TableCell className="font-medium">
                                <Checkbox checked={selectedItems.includes(el.id)} onCheckedChange={() => handleCheckboxChange(el.id)} />
                            </TableCell>
                            <TableCell className="font-medium">{el.file_name}</TableCell>
                            <TableCell className="font-medium">{el.file_name}</TableCell>
                            <TableCell>{el.file_name}</TableCell>
                            <TableCell>{el.update_time.replace('T', ' ')}</TableCell>
                            <TableCell>{el.update_time.replace('T', ' ')}</TableCell>
                            <TableCell>创建人</TableCell>
                            <TableCell>
                                <Switch checked={true} onCheckedChange={(bln) => { /* api */ }} />
                            </TableCell>
                            <TableCell className="text-right">
                                <Button variant="link" onClick={() => editRef.current.edit(el.id)} className="ml-4">更新</Button>
                                <Button variant="link" onClick={() => handleDelete(el.id)} className="ml-4 text-red-500">{t('delete')}</Button>
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </div>
        <div className="bisheng-table-footer px-6">
            <div>
                <span>已选：{selectedItems.length}</span>
                <Button variant="link" className="text-red-500 ml-4" onClick={handleDeleteSelected}>删除</Button>
            </div>
            <div>
                <AutoPagination
                    page={page}
                    pageSize={pageSize}
                    total={total}
                    onChange={(newPage) => setPage(newPage)}
                />
            </div>
        </div>
        <EditQa ref={editRef} onChange={reload} />
    </div >
};
