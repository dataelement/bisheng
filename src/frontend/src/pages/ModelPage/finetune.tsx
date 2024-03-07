import { useContext, useState } from "react";
import { useTranslation } from "react-i18next";
import PaginationComponent from "../../components/PaginationComponent";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { alertContext } from "../../contexts/alertContext";
import { deleteTaskApi, getTasksApi } from "../../controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import { useDebounce, useTable } from "../../util/hook";
import CreateTask from "./components/CreateTask";
import FinetuneDetail, { BadgeView } from "./components/FinetuneDetail";
import FinetuneHead from "./components/FinetuneHead";

export const Finetune = ({ rtClick, gpuClick }) => {
    const { setSuccessData } = useContext(alertContext);
    const { t } = useTranslation()

    const { page, pageSize, data: tasks, total, setPage, search, reload, filterData } = useTable((param) =>
        getTasksApi({
            page: param.page,
            limit: param.pageSize,
            model_name: param.keyword,
            server: param.rt || 'all',
            status: param.type || 'all'
        })
    )
    // 详情
    const [taskId, setTaskId] = useState('')

    // del
    const handleDeleteTask = async () => {
        const res = await captureAndAlertRequestErrorHoc(deleteTaskApi(taskId))
        if (res !== null) return

        setSuccessData({ title: t('deleteSuccess') })
        setTaskId('')
        reload()
    }

    const [createOpen, setCreateOpen] = useState(false)

    // useDebounce
    const changeItem = useDebounce((id) => {
        // 滚动到顶部
        const scorllDom = document.querySelector('#model-scroll')
        scorllDom && (scorllDom.scrollTop = 0)
        setTaskId(id)
    }, 600, false)

    return <div className="relative">
        <div className={createOpen ? 'hidden' : 'block'}>
            <FinetuneHead onSearch={search} onFilter={filterData} rtClick={rtClick} onCreate={() => setCreateOpen(true)}></FinetuneHead>
            {/* body */}
            {tasks?.length === 0 ?
                <div className="mt-6 text-center text-gray-400">{t('finetune.noData')}</div>
                : <div className="flex gap-4 mt-4">
                    <div className="w-[40%]">
                        <div className="border-r overflow-y-auto max-h-[calc(100vh-208px)]">
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead className="w-[100px]">{t('finetune.modelName')}</TableHead>
                                        <TableHead></TableHead>
                                        <TableHead>{t('finetune.rtService')}</TableHead>
                                        <TableHead className="text-right">{t('finetune.createTime')}</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {tasks.map((task) => (
                                        <TableRow key={task.id} onClick={() => changeItem(task.id)} className={`cursor-pointer ${task.id === taskId && 'bg-gray-100'}`}>
                                            <TableCell className="font-medium">{task.model_name}</TableCell>
                                            <TableCell><BadgeView value={task.status}></BadgeView></TableCell>
                                            <TableCell>{task.server_name}</TableCell>
                                            <TableCell className="text-right">{task.create_time.replace('T', ' ')}</TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </div>
                        <PaginationComponent
                            page={page}
                            pageSize={pageSize}
                            total={total}
                            onChange={(newPage) => setPage(newPage)}
                        />
                    </div>
                    <div className="flex-1 overflow-hidden overflow-y-auto max-h-[calc(100vh-180px)]">
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
                        rtClick={rtClick}
                        gpuClick={gpuClick}
                        onCancel={() => setCreateOpen(false)}
                        onCreate={(id) => {
                            reload();
                            setCreateOpen(false);
                            setTaskId(id)
                        }}></CreateTask>
                </div>
            }
        </div>
    </div>
};