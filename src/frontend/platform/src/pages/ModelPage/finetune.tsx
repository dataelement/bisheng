import { userContext } from "@/contexts/userContext";
import { useKnowledgePageScope } from "@/hooks/useKnowledgePageScope";
import { canManageModelSettings } from "./manage/permissions";
import { Pagination } from "@bisheng/ui";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/bs-ui/table";
import { alertContext } from "../../contexts/alertContext";
import { deleteTaskApi, getTasksApi } from "../../controllers/API/finetune";
import { useDebounce, useTable } from "../../util/hook";
import CreateTask from "./components/CreateTask";
import FinetuneDetail, { BadgeView } from "./components/FinetuneDetail";
import FinetuneHead from "./components/FinetuneHead";
import RTConfig from "./components/RTConfig";
import { CpuDetail } from "./cpuInfo";

export const Finetune = () => {
    const { scopes } = useKnowledgePageScope();
    const scope = scopes?.ordinary;
    if (!scope) return null;
    return <FinetuneContent key={`${scope.identityKey}:${scope.tenantId}:${scope.managementTenantId}`} />;
};

function FinetuneContent() {
    const { user } = useContext(userContext);
    const canManageServices = canManageModelSettings(user);
    const { setSuccessData } = useContext(alertContext);
    const { t, i18n } = useTranslation();
    const paginationLocale = usePaginationLocale();

    useEffect(() => {
        i18n.loadNamespaces('model');
    }, [i18n]);

    const [rtOpen, setRTOpen] = useState(false)
    const [showCpu, setShowCpu] = useState({
        type: 'model',
        show: false
    })

    const { page, pageSize, data: tasks, total, setPage, search, reload, filterData } = useTable({}, (param) =>
        getTasksApi({
            page: param.page,
            limit: param.pageSize,
            model_name: param.keyword,
            server: param.rt || 'all',
            status: param.type || 'all'
        })
    )
    // Details
    const [taskId, setTaskId] = useState('')

    // del
    const handleDeleteTask = async () => {
        const res = await deleteTaskApi(taskId)
        if (res !== null) return

        setSuccessData({ title: t('deleteSuccess') })
        setTaskId('')
        reload()
    }

    const [createOpen, setCreateOpen] = useState(false)

    // useDebounce
    const changeItem = useDebounce((id) => {
        // Scroll to the top
        const scorllDom = document.querySelector('#model-scroll')
        scorllDom && (scorllDom.scrollTop = 0)
        setTaskId(id)
    }, 600, false)

    return <div className="relative bg-background-main-content pt-2">
        <div className={createOpen ? 'hidden' : 'block'}>
            <FinetuneHead onSearch={search} onFilter={filterData} rtClick={canManageServices ? () => setRTOpen(true) : undefined} onCreate={() => setCreateOpen(true)}></FinetuneHead>
            {/* body */}
            {tasks?.length === 0 ?
                <div className="mt-6 text-center text-gray-400">{t('finetune.noData')}</div>
                : <div className="flex gap-4 mt-4">
                    <div className="w-[40%] relative">
                        <div className="border-r overflow-y-auto max-h-[calc(100vh-150px-var(--license-banner-h,0px))] pb-20">
                            <Table className="px-2">
                                <TableHeader>
                                    <TableRow>
                                        <TableHead className="w-[100px]">{t('finetune.modelName')}</TableHead>
                                        <TableHead className="w-[100px]"></TableHead>
                                        <TableHead>{t('finetune.rtService')}</TableHead>
                                        <TableHead className="text-right">{t('finetune.createTime')}</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {tasks.map((task: any) => (
                                        <TableRow key={task.id} onClick={() => changeItem(task.id)} className={`cursor-pointer ${task.id === taskId && 'bg-gray-100'}`}>
                                            <TableCell className="font-medium">{task.model_name}</TableCell>
                                            <TableCell className="whitespace-nowrap"><BadgeView value={task.status}></BadgeView></TableCell>
                                            <TableCell>{task.server_name}</TableCell>
                                            <TableCell className="text-right">{task.create_time.replace('T', ' ')}</TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </div>
                        <div className="bisheng-table-footer bg-background-login">
                            <p className="desc"></p>
                            <Pagination locale={paginationLocale}
                                current={page}
                                pageSize={pageSize}
                                total={total}
                                onChange={(newPage) => setPage(newPage)}
                            />
                        </div>
                    </div>
                    <div className="flex-1 overflow-hidden overflow-y-auto max-h-[calc(100vh-150px-var(--license-banner-h,0px))]">
                        {taskId ?
                            <FinetuneDetail id={taskId} onDelete={handleDeleteTask} onStatusChange={reload}></FinetuneDetail> :
                            <div className="flex justify-center items-center h-full">
                                <p className="text-sm text-muted-foreground">{t('finetune.selectModel')}</p>
                            </div>}
                    </div>
                </div>
            }
        </div>

        {/* create */}
        <div className={createOpen ? 'block' : 'hidden'}>
            {
                createOpen && <div>
                    <CreateTask
                        rtClick={canManageServices ? () => setRTOpen(true) : undefined}
                        gpuClick={() => setShowCpu({ type: 'finetune', show: true })}
                        onCancel={() => setCreateOpen(false)}
                        onCreate={(id) => {
                            reload();
                            setCreateOpen(false);
                            setTaskId(id)
                        }}></CreateTask>
                </div>
            }
        </div>
        {/* FT services */}
        {canManageServices && <RTConfig open={rtOpen} onChange={() => setRTOpen(false)}></RTConfig>}
        {/* GPU usage */}
        <Dialog open={showCpu.show} onOpenChange={(show) => setShowCpu({ ...showCpu, show })}>
            <DialogContent className="sm:max-w-[80%]">
                <DialogHeader>
                    <DialogTitle>{t('model.gpuResourceUsageTitle')}</DialogTitle>
                </DialogHeader>
                <div className="flex flex-wrap justify-center overflow-y-auto no-scrollbar">
                    {showCpu.show && <CpuDetail type={showCpu.type} />}
                </div>
            </DialogContent>
        </Dialog>
    </div>
};
