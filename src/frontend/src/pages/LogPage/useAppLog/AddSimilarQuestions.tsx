import KnowledgeSelect from "@/components/bs-comp/selectComponent/knowledge";
import { Button } from "@/components/bs-ui/button";
import { Checkbox } from "@/components/bs-ui/checkBox";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { addSimilarQa, getQaList } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useTable } from "@/util/hook";
import { forwardRef, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

const AddSimilarQuestions = forwardRef(({ }, ref) => {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);
    const [knowledgeLib, setKnowledgeLib] = useState([]);
    const [selectedItems, setSelectedItems] = useState([]);
    const [error, setError] = useState(false);

    const { page, pageSize, data: datalist, total, loading, setPage, filterData, clean } = useTable({ unInitData: true }, (param) =>
        getQaList(param.id, { page: param.page, pageSize: 10, keyword: param.searchKey })
    );

    const qRef = useRef('');

    useImperativeHandle(ref, () => ({
        open(id, qa) {
            qRef.current = qa.q;
            setOpen(true);
            setKnowledgeLib([]);
            setSelectedItems([]);
        }
    }));

    const handleKnowledgeLibChange = (value) => {
        setKnowledgeLib(value);
    };

    const handleCheckboxChange = (id) => {
        setSelectedItems((prevSelectedItems) =>
            prevSelectedItems.includes(id)
                ? prevSelectedItems.filter((item) => item !== id)
                : [...prevSelectedItems, id]
        );
    };

    const { message } = useToast();
    const handleSubmit = async () => {
        const errors = []
        if (knowledgeLib.length === 0) {
            errors.push('QA知识库不能为空');
        }
        if (selectedItems.length === 0) {
            errors.push('至少选一个相似问题');
        }
        if (errors.length > 0) {
            setError(true);
            return message({ variant: 'warning', description: errors })
        }

        captureAndAlertRequestErrorHoc(addSimilarQa({
            ids: selectedItems,
            question: qRef.current
        }).then(res => {
            message({
                variant: 'success',
                description: '添加成功'
            });
        }))
    };

    const close = () => {
        qRef.current = '';
        setKnowledgeLib([]);
        setSelectedItems([]);
        setOpen(false);
        setError(false);
        clean()
    };

    return (
        <Dialog open={open} onOpenChange={(bln) => bln ? setOpen(bln) : close()}>
            <DialogContent className="sm:max-w-[825px]">
                <DialogHeader>
                    <DialogTitle>添加到相似问</DialogTitle>
                </DialogHeader>
                <div className="flex flex-col gap-4 py-2">
                    <div className="flex items-center">
                        <Label htmlFor="knowledgeLib" className="bisheng-label w-24">QA知识库</Label>
                        <KnowledgeSelect
                            type="qa"
                            value={knowledgeLib}
                            onChange={handleKnowledgeLibChange}
                            className={`${error && knowledgeLib.length === 0 ? 'border-red-400' : ''}`}
                        />
                    </div>
                    <div className="flex items-center">
                        <Label htmlFor="knowledgeLib" className="bisheng-label w-24">搜索QA</Label>
                        <Input placeholder='请输入' onChange={(e) => knowledgeLib.length && filterData({ id: knowledgeLib[0].value, searchKey: e.target.value })} />
                    </div>
                    <div className="relative">
                        {loading && (
                            <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                                <span className="loading loading-infinity loading-lg"></span>
                            </div>
                        )}
                        <div className="h-[510px] overflow-y-auto">
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead className="w-8"></TableHead>
                                        <TableHead className="w-[300px]">问题</TableHead>
                                        <TableHead>答案</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {datalist.map((el) => (
                                        <TableRow key={el.id}>
                                            <TableCell className="font-medium">
                                                <Checkbox checked={selectedItems.includes(el.id)} onCheckedChange={() => handleCheckboxChange(el.id)} />
                                            </TableCell>
                                            <TableCell className="font-medium">
                                                <div className="whitespace-nowrap text-ellipsis overflow-hidden">{el.questions}</div>
                                            </TableCell>
                                            <TableCell className="font-medium whitespace-nowrap text-ellipsis overflow-hidden">
                                                <div className="whitespace-nowrap text-ellipsis overflow-hidden">{el.answers}</div>
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                    {datalist.length === 0 && <TableRow>
                                        <TableCell colSpan={3} className="font-medium text-center">请通过搜索查找QA</TableCell>
                                    </TableRow>}
                                </TableBody>
                            </Table>
                        </div>
                        <div className="bisheng-table-footer px-6 bg-transparent">
                            <AutoPagination
                                className="justify-end"
                                page={page}
                                pageSize={pageSize}
                                total={total}
                                onChange={(newPage) => setPage(newPage)}
                            />
                        </div>
                    </div>
                    <DialogFooter>
                        <DialogClose>
                            <Button variant="outline" className="px-11" type="button" onClick={close}>取消</Button>
                        </DialogClose>
                        <Button type="submit" className="px-11" onClick={handleSubmit}>确认</Button>
                    </DialogFooter>
                </div>
            </DialogContent>
        </Dialog>
    );
});

export default AddSimilarQuestions;
