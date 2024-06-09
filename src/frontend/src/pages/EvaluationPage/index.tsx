import { useNavigate } from "react-router-dom";
import { Button } from "../../components/bs-ui/button";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../components/bs-ui/table";
import {
    Tabs,
    TabsContent,
} from "../../components/bs-ui/tabs";

import { useTranslation } from "react-i18next";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import AutoPagination from "../../components/bs-ui/pagination/autoPagination";
import { useTable } from "../../util/hook";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Evaluation, deleteEvaluationApi, getEvaluationApi, getEvaluationUrlApi } from "@/controllers/API/evaluate";
import { EvaluationScore, EvaluationStatus, TypeEvaluation } from "@/utils";
import { downloadFile } from "@/util/utils";
import { checkSassUrl } from "../ChatAppPage/components/FileView";
import { Badge } from "@/components/bs-ui/badge";
import { useEffect } from "react";
import { map } from "lodash";

export default function EvaluationPage() {
    const navigate = useNavigate()

    const { page, pageSize, data: datalist, total, loading, setPage, search, reload } = useTable({}, (param) =>
        getEvaluationApi(param.page, param.pageSize)
    )

    useEffect(() => {
        const intervalId = setInterval(() => {
          reload(); 
        }, 6000); // 每 6 秒轮询一次
    
        return () => clearInterval(intervalId);
      }, [reload]);
    

    const handleDelete = (id) => {
        bsConfirm({
            title: t('prompt'),
            desc: t('evaluation.confirmDeleteEvaluation'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(deleteEvaluationApi(id).then(res => {
                    reload();
                }));
                next()
            },
        })
    }

    const handleDownload = async (el) => {
        const { url } = await getEvaluationUrlApi(el.result_file_path)        
        await downloadFile(url, el.file_name)
    }

    const { t } = useTranslation();

    return (
        <div className="w-full h-full px-2 py-4 relative">
            {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                <span className="loading loading-infinity loading-lg"></span>
            </div>}
            <div className="h-full overflow-y-auto pb-10">
                <Tabs defaultValue="account" className="w-full mb-[40px]">
                    <TabsContent value="account">
                        <div className="flex justify-end gap-4 items-center">
                            <Button className="px-8" onClick={() => navigate('/evaluation/create')}>{t('create')}</Button>
                        </div>
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead className="w-[80px]">{t('evaluation.id')}</TableHead>
                                    <TableHead className="w-[100px]">{t('evaluation.filename')}</TableHead>
                                    <TableHead>{t('evaluation.skillAssistant')}</TableHead>
                                    <TableHead className="w-[80px]">{t('evaluation.status')}</TableHead>
                                    <TableHead>{t('evaluation.score')}</TableHead>
                                    <TableHead>{t('createTime')}</TableHead>
                                    <TableHead className="text-right">{t('operations')}</TableHead>
                                </TableRow>
                            </TableHeader>

                            <TableBody>
                                {datalist.map((el: Evaluation) => (
                                    <TableRow key={el.id}>
                                        <TableCell className="font-medium">{el.id}</TableCell>
                                        <TableCell>{el.file_name || '--'}</TableCell>
                                        <TableCell>
                                            <div className="flex items-center">
                                                <Badge className="whitespace-nowrap">{TypeEvaluation[el.exec_type]}</Badge>&nbsp;<span className="whitespace-nowrap">{el.unique_name}</span>&nbsp;{el.version_name && <Button variant="link">{el.version_name}</Button>}
                                            </div>
                                        </TableCell>
                                        <TableCell>{EvaluationStatus[el.status]}</TableCell>
                                        <TableCell>
                                            <div className="flex flex-wrap">
                                                {map(el.result_score,(value,key)=>{
                                                    return <span className="whitespace-nowrap">{EvaluationScore[key]}：{value}</span>
                                                })}
                                            </div>
                                        </TableCell>
                                        <TableCell>{el.create_time.replace('T', ' ') || '--'}</TableCell>
                                        <TableCell className="text-right">
                                            <div className="flex">
                                                <Button variant="link" className="no-underline hover:underline" onClick={()=>handleDownload(el)}>{t('evaluation.download')}</Button>
                                                <Button variant="link" onClick={() => handleDelete(el.id)} className="ml-1 text-red-500 px-0">{t('delete')}</Button>
                                            </div>
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </TabsContent>
                    <TabsContent value="password"></TabsContent>
                </Tabs>
            </div>
            <div className="bisheng-table-footer px-6">
                <p className="desc">{t('evaluation.evaluationCollection')}</p>
                <div>
                    <AutoPagination
                        page={page}
                        pageSize={pageSize}
                        total={total}
                        onChange={(newPage) => setPage(newPage)}
                    />
                </div>
            </div>
            {/* <CreateModal datalist={datalist} open={open} setOpen={setOpen}></CreateModal> */}
        </div>
    );
}