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

import { useContext, useState } from "react";
import { useTranslation } from "react-i18next";
import { userContext } from "../../contexts/userContext";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import AutoPagination from "../../components/bs-ui/pagination/autoPagination";
import { useTable } from "../../util/hook";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Evaluation, deleteEvaluationApi, getEvaluationApi, getEvaluationUrlApi } from "@/controllers/API/evaluate";
import { TypeEvaluation } from "@/utils";
import { downloadFile } from "@/util/utils";
import { checkSassUrl } from "../ChatAppPage/components/FileView";

export default function EvaluationPage() {
    const [open, setOpen] = useState(false);
    const { user } = useContext(userContext);
    const navigate = useNavigate()

    const { page, pageSize, data: datalist, total, loading, setPage, search, reload } = useTable({}, (param) =>
        getEvaluationApi(param.page, param.pageSize)
    )

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
        const { url } = await getEvaluationUrlApi('evaluation/dataset/32ae590662e24e8f98fd75d525273812.docx')
        await downloadFile(checkSassUrl(url), el.file_path)
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
                                    <TableHead className="w-[200px]">{t('evaluation.id')}</TableHead>
                                    <TableHead>{t('evaluation.filename')}</TableHead>
                                    <TableHead>{t('evaluation.skillAssistant')}</TableHead>
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
                                        <TableCell>{TypeEvaluation[el.exec_type]}&nbsp;{el.unique_name}&nbsp;{el.version_name}</TableCell>
                                        <TableCell>{el.result_score}</TableCell>
                                        <TableCell>{el.create_time.replace('T', ' ') || '--'}</TableCell>
                                        <TableCell className="text-right" onClick={() => {
                                            // @ts-ignore
                                            window.libname = el.name;
                                        }}>
                                            <Button variant="link" className="no-underline hover:underline" onClick={()=>handleDownload(el)}>{t('evaluation.download')}</Button>
                                            <Button variant="link" onClick={() => handleDelete(el.id)} className="ml-4 text-red-500 px-0">{t('delete')}</Button>
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