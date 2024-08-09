
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { SearchInput } from "@/components/bs-ui/input";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { deleteFileLib } from "@/controllers/API";
import { getFileUrlApi, getPresetFileApi } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useTable } from "@/util/hook";
import { downloadFile } from "@/util/utils";
import { t } from "i18next";
import { useRef } from "react";
import { checkSassUrl } from "../ChatAppPage/components/FileView";
import CreateDataSet from "./CreateDataSet";
import { useToast } from "@/components/bs-ui/toast/use-toast";


export default function index() {
    const { page, pageSize, data: datalist, total, loading, setPage, search, reload } = useTable({}, (param) =>
        getPresetFileApi({ page_size: 20, page_num: param.page, keyword: param.keyword }).then(res => ({ data: res, total: res.length }))
    )

    const handleDelete = (id) => {
        bsConfirm({
            title: t('prompt'),
            desc: '确认删除数据集！',
            onOk(next) {
                captureAndAlertRequestErrorHoc(deleteFileLib(id).then(res => {
                    reload();
                }));
                next()
            },
        })
    }

    const modelRef = useRef(null)

    const { toast } = useToast()
    const handleDownloadFile = async (name, url) => {
        const res = await getFileUrlApi(url)
        if (!res.url) {
            return toast({ variant: 'error', description: '文件不存在' })
        }
        await downloadFile(checkSassUrl(res.url), name + '.json')
    }

    return <div className="relative h-full px-2 py-4">
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <span className="loading loading-infinity loading-lg"></span>
        </div>}
        <div className="h-[calc(100vh-128px)] overflow-y-auto pb-10">
            <div className="flex justify-end gap-4 items-center">
                <SearchInput placeholder="搜索" onChange={(e) => search(e.target.value)} />
                <Button className="px-8 text-[#FFFFFF]" onClick={() => modelRef.current.open()}>{t('create')}</Button>
            </div>
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[200px]">数据集名称</TableHead>
                        <TableHead>创建时间</TableHead>
                        <TableHead>更新时间</TableHead>
                        <TableHead>{t('lib.createUser')}</TableHead>
                        <TableHead className="text-right">{t('operations')}</TableHead>
                    </TableRow>
                </TableHeader>

                <TableBody>
                    {datalist.map((el: any) => (
                        <TableRow key={el.id}>
                            <TableCell className="font-medium max-w-[200px]">
                                <div className=" truncate-multiline">{el.name}</div>
                            </TableCell>
                            <TableCell>{el.create_time.replace('T', ' ')}</TableCell>
                            <TableCell>{el.update_time.replace('T', ' ')}</TableCell>
                            <TableCell className="max-w-[300px] break-all">
                                <div className=" truncate-multiline">{el.user_name || '--'}</div>
                            </TableCell>
                            <TableCell className="text-right" onClick={() => {
                                // @ts-ignore
                                window.libname = el.name;
                            }}>
                                {/* <Button variant="link" className="" onClick={() => setOpenData(true)}>添加到数据集</Button> */}
                                <Button variant="link" className="px-1" onClick={() => handleDownloadFile(el.name, el.url)}>下载</Button>
                                <Button variant="link" onClick={() => handleDelete(el.id)} className="ml-4 text-red-500 px-0">{t('delete')}</Button>
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </div>
        <div className="bisheng-table-footer px-6 bg-background-login">
            <p className="desc">{t('lib.libraryCollection')}</p>
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
};
