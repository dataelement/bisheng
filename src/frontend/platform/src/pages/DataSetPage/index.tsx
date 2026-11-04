// @ts-strict-ignore
import { Pagination, Button, SearchInput, notification } from '@bisheng/ui';

import { checkSassUrl } from "@/components/bs-comp/FileView";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";


import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";

import { deleteDatasetApi, getFileUrlApi, getPresetFileApi } from "@/controllers/API/finetune";
import { useTable } from "@/util/hook";
import { downloadFile } from "@/util/utils";
import { useRef } from "react";
import { useTranslation } from "react-i18next";
import CreateDataSet from "./CreateDataSet";

export default function DataSetPage() {
    const { t } = useTranslation();
    const paginationLocale = usePaginationLocale();
    const { page, pageSize, data: datalist, total, loading, setPage, search, reload } = useTable({}, (param) =>
        getPresetFileApi({ page_size: 20, page_num: param.page, keyword: param.keyword })
    );

    const handleDelete = (id) => {
        bsConfirm({
            desc: t('dataset.confirmDelete'),
            onOk(next) {
                return deleteDatasetApi(id).then(() => {
                    reload();
                    next();
                });
            },
        });
    };

    const modelRef = useRef(null);


    const handleDownloadFile = async (name, url) => {
        const res = await getFileUrlApi(url);
        if (!res.url) {
            return notification.open({ type: 'error', description: String(t('dataset.fileNotFound') ?? '') });
        }
        await downloadFile(checkSassUrl(res.url), name + '.json');
    };

    return (
        <div className="relative h-full px-2 py-4">
            {loading && (
                <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                    <LoadingIcon />
                </div>
            )}
            <div className="h-[calc(100vh-128px-var(--license-banner-h,0px))] overflow-y-auto pb-10">
                <div className="mr-2 flex justify-end gap-4 items-center">
                    <SearchInput placeholder={t('dataset.name')} onChange={(e) => search(e.target.value)} className={"w-56 shrink-0"} />
                    <Button onClick={() => modelRef.current.open()}>{t('dataset.create')}</Button>
                </div>
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[200px]">{t('dataset.name')}</TableHead>
                            <TableHead>{t('dataset.creationTime')}</TableHead>
                            <TableHead>{t('dataset.updateTime')}</TableHead>
                            <TableHead>{t('dataset.createUser')}</TableHead>
                            <TableHead className="text-right">{t('operations')}</TableHead>
                        </TableRow>
                    </TableHeader>

                    <TableBody>
                        {datalist.map((el) => (
                            <TableRow key={el.id}>
                                <TableCell className="font-medium max-w-[200px]">
                                    <div className="truncate-multiline">{el.name}</div>
                                </TableCell>
                                <TableCell>{el.create_time.replace('T', ' ')}</TableCell>
                                <TableCell>{el.update_time.replace('T', ' ')}</TableCell>
                                <TableCell className="max-w-[300px] break-all">
                                    <div className="truncate-multiline">{el.user_name || '--'}</div>
                                </TableCell>
                                <TableCell onClick={() => { window.libname = el.name; }}>
                                    <div className="flex justify-end gap-2">
                                        <Button size="small" variant="link" onClick={() => handleDownloadFile(el.name, el.url)}>{t('dataset.download')}</Button>
                                        <Button size="small" variant="link" color="danger" onClick={() => handleDelete(el.id)}>{t('delete')}</Button>
                                    </div>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>
            <div className="bisheng-table-footer px-6 bg-background-login">
                <div className="ml-auto">
                    <Pagination locale={paginationLocale}
                        current={page}
                        pageSize={pageSize}
                        total={total}
                        onChange={(newPage) => setPage(newPage)}
                    />
                </div>
            </div>
            <CreateDataSet ref={modelRef} onChange={reload} />
        </div>
    );
}
