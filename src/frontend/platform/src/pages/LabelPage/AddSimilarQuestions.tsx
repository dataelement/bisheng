// @ts-strict-ignore
import { captureQaOperation, type QaOperation } from '@bisheng/chat/core';
import { Pagination, Button, Input, toast } from '@bisheng/ui';
import KnowledgeSelect from "@/components/bs-comp/selectComponent/knowledge";
import { LoadingIcon } from "@/components/bs-icons/loading";

import { Checkbox } from "@bisheng/ui";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";

import { Label } from "@/components/bs-ui/label";
import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";

import { addSimilarQa, getQaList } from "@/controllers/API";
import { showApiError } from "@/controllers/request";
import { useTable } from "@/util/hook";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { AnnotationFormHandle, AnnotationFormProps } from "./annotationTypes";

const AddSimilarQuestions = forwardRef<AnnotationFormHandle, AnnotationFormProps>(({ onMarked }, ref) => {
    const { t } = useTranslation();
    const paginationLocale = usePaginationLocale();
    const [open, setOpen] = useState(false);
    const [knowledgeLib, setKnowledgeLib] = useState([]);
    const [selectedItems, setSelectedItems] = useState([]);
    const [error, setError] = useState(false);

    const { page, pageSize, loaded, data: datalist, total, loading, setPage, filterData, clean } = useTable({ unInitData: true }, (param) =>
        getQaList(param.id, { page: param.page, pageSize: 10, keyword: param.searchKey })
    );

    const qRef = useRef('');
    const operationRef = useRef<Readonly<QaOperation>>();
    const generationRef = useRef(0);
    const pendingRef = useRef(false);
    const [saving, setSaving] = useState(false);
    useEffect(() => () => {
        generationRef.current += 1;
        pendingRef.current = false;
        operationRef.current = undefined;
    }, []);

    useImperativeHandle(ref, () => ({
        close,
        open(_id, qa, operation) {
            generationRef.current += 1;
            operationRef.current = operation ? captureQaOperation(operation) : undefined;
            pendingRef.current = false;
            setSaving(false);
            setError(false);
            qRef.current = qa.q;
            setOpen(true);
            setKnowledgeLib([]);
            setSelectedItems([]);
        }
    }));

    const handleKnowledgeLibChange = (option) => {
        setKnowledgeLib(option);
        filterData({ id: option[0].value, searchKey: '' });
    };

    const handleCheckboxChange = (id) => {
        setSelectedItems((prevSelectedItems) =>
            prevSelectedItems.includes(id)
                ? prevSelectedItems.filter((item) => item !== id)
                : [...prevSelectedItems, id]
        );
    };


    const handleSubmit = async () => {
        if (pendingRef.current) return;
        const errors = [];
        if (knowledgeLib.length === 0) {
            errors.push(t('log.qaLibRequired'));
        }
        if (selectedItems.length === 0) {
            errors.push(t('log.selectAtLeastOneQuestion'));
        }
        if (errors.length > 0) {
            setError(true);
            return toast.show({ type: 'warning', message: errors.filter(Boolean).join('\n') });
        }

        const generation = generationRef.current;
        const operation = operationRef.current;
        pendingRef.current = true;
        setSaving(true);
        await addSimilarQa({
            ids: selectedItems,
            question: qRef.current
        }).then(async () => {
            if (generation === generationRef.current) {
                toast.show({ type: 'success', message: String(t('log.addSuccess') ?? '') });
                close();
            }
            await onMarked?.(operation);
        }).catch(showApiError).finally(() => {
            if (generation === generationRef.current) { pendingRef.current = false; setSaving(false); }
        });
    };

    const close = () => {
        generationRef.current += 1;
        operationRef.current = undefined;
        pendingRef.current = false;
        setSaving(false);
        qRef.current = '';
        setKnowledgeLib([]);
        setSelectedItems([]);
        setOpen(false);
        setError(false);
        clean();
    };

    return (
        <Dialog open={open} onOpenChange={(bln) => bln ? setOpen(bln) : close()}>
            <DialogContent className="sm:max-w-[825px]">
                <DialogHeader>
                    <DialogTitle>{t('log.addSimilarQuestionsToQaLib')}</DialogTitle>
                </DialogHeader>
                <div className="flex flex-col gap-4 py-2">
                    <div className="flex items-center gap-4">
                        <Label htmlFor="knowledgeLib" className="bisheng-label w-40 whitespace-nowrap">{t('log.qaKnowledgeLib')}</Label>
                        <KnowledgeSelect
                            type="qa"
                            value={knowledgeLib}
                            onChange={handleKnowledgeLibChange}
                            className={`${error && knowledgeLib.length === 0 ? 'border-red-400' : ''}`}
                        />
                        <Input placeholder={t('log.qaContent')} onChange={(e) => knowledgeLib.length && filterData({ id: knowledgeLib[0].value, searchKey: e.target.value })} />
                    </div>
                    <div className="relative">
                        {loading && (
                            <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                                <LoadingIcon />
                            </div>
                        )}
                        <div className="h-[510px] overflow-y-auto">
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead className="w-8"></TableHead>
                                        <TableHead className="w-[300px]">{t('log.question')}</TableHead>
                                        <TableHead className="w-[360px]">{t('log.answer')}</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {datalist.map((el) => (
                                        <TableRow key={el.id}>
                                            <TableCell className="font-medium">
                                                <Checkbox size="small" aria-label={String(el.questions)} checked={selectedItems.includes(el.id)} onCheckedChange={() => handleCheckboxChange(el.id)} />
                                            </TableCell>
                                            <TableCell className="font-medium">
                                                <div className="max-w-[360px] whitespace-nowrap text-ellipsis overflow-hidden">{el.questions}</div>
                                            </TableCell>
                                            <TableCell className="font-medium whitespace-nowrap text-ellipsis overflow-hidden">
                                                <div className="max-w-[360px] whitespace-nowrap text-ellipsis overflow-hidden">{el.answers}</div>
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                    {loaded && datalist.length === 0 && <TableRow>
                                        <TableCell colSpan={3} className="font-medium text-center">{t('log.empty')}</TableCell>
                                    </TableRow>}
                                    {
                                        !loaded && <TableRow>
                                            <TableCell colSpan={3} className="font-medium text-center">{t('log.selectQaLib')}</TableCell>
                                        </TableRow>
                                    }
                                </TableBody>
                            </Table>
                        </div>
                        <div className="bisheng-table-footer px-6 bg-transparent">
                            <Pagination locale={paginationLocale} size="small" simple
                                className="justify-end"
                                current={page}
                                pageSize={pageSize}
                                total={total}
                                onChange={(newPage) => setPage(newPage)}
                            />
                        </div>
                    </div>
                    <DialogFooter>
                        <DialogClose asChild>
                            <Button variant="outlined" type="button" onClick={close} color="default">{t('log.cancel')}</Button>
                        </DialogClose>
                        <Button type="submit" loading={saving} disabled={saving} onClick={handleSubmit}>{t('log.confirm')}</Button>
                    </DialogFooter>
                </div>
            </DialogContent>
        </Dialog>
    );
});


export default AddSimilarQuestions;
