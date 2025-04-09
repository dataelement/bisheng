
import { checkSassUrl } from "@/components/bs-comp/FileView";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { SearchInput } from "@/components/bs-ui/input";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { deleteDatasetApi, getFileUrlApi, getPresetFileApi } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useTable } from "@/util/hook";
import { downloadFile } from "@/util/utils";
import { useRef } from "react";
import { useTranslation } from "react-i18next";
import CreateDataSet from "./CreateDataSet";
import { LoadingIcon } from "@/components/bs-icons/loading";

export default function index() {
    const { t } = useTranslation();
    const { page, pageSize, data: datalist, total, loading, setPage, search, reload } = useTable({}, (param) =>
        getPresetFileApi({ page_size: 20, page_num: param.page, keyword: param.keyword })
    );

    const handleDelete = (id) => {
        bsConfirm({
            desc: t('dataset.confirmDelete'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(deleteDatasetApi(id).then(res => {
                    reload();
                }));
                next();
            },
        });
    };

    const modelRef = useRef(null);

    const { toast } = useToast();
    const handleDownloadFile = async (name, url) => {
        const res = await getFileUrlApi(url);
        if (!res.url) {
            return toast({ variant: 'error', description: t('dataset.fileNotFound') });
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
            <div className="h-[calc(100vh-128px)] overflow-y-auto pb-10">
                <div className="flex justify-end gap-4 items-center">
                    <SearchInput placeholder={t('dataset.name')} onChange={(e) => search(e.target.value)} />
                    <Button className="px-8 text-[#FFFFFF]" onClick={() => modelRef.current.open()}>{t('dataset.create')}</Button>
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
                                <TableCell className="text-right" onClick={() => { window.libname = el.name; }}>
                                    <Button variant="link" className="px-1" onClick={() => handleDownloadFile(el.name, el.url)}>{t('dataset.download')}</Button>
                                    <Button variant="link" onClick={() => handleDelete(el.id)} className="ml-4 text-red-500 px-0">{t('delete')}</Button>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>
            <div className="bisheng-table-footer px-6 bg-background-login">
                <p className="desc">{t('dataset.collection')}</p>
                <div>
                    <AutoPagination
                        page={page}
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
