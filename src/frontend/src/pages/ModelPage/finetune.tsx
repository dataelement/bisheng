import { useContext, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { alertContext } from "../../contexts/alertContext";
import { deleteTaskApi, getTasksApi } from "../../controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import CreateTask from "./components/CreateTask";
import FinetuneDetail, { BadgeView } from "./components/FinetuneDetail";
import FinetuneHead from "./components/FinetuneHead";
import PaginationComponent from "../../components/PaginationComponent";

export const Finetune = ({ rtClick, gpuClick }) => {
    const { setSuccessData } = useContext(alertContext);
    const { t } = useTranslation()

    const pageSize = 20
    const { currentPage, tasks, searchTask, loadTasks } = useTasks(pageSize)
    // 详情
    const [taskId, setTaskId] = useState('')

    // del
    const handleDeleteTask = async () => {
        const res = await captureAndAlertRequestErrorHoc(deleteTaskApi(taskId))
        if (!res) return

        setSuccessData({ title: t('finetune.deleteSuccess') })
        setTaskId('')
        loadTasks()
    }

    const [createOpen, setCreateOpen] = useState(false)

    return <div className="relative">
        <div className={createOpen ? 'hidden' : 'block'}>
            <FinetuneHead onChange={searchTask} rtClick={rtClick} onCreate={() => setCreateOpen(true)}></FinetuneHead>
            {/* body */}
            {tasks?.length === 0 ?
                <div className="mt-6 text-center text-gray-400">{t('finetune.noData')}</div>
                : <div className="flex gap-4 mt-4">
                    <div className="w-[40%] border-r">
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
                                    <TableRow key={task.id} onClick={() => setTaskId(task.id)} className="cursor-pointer">
                                        <TableCell className="font-medium">{task.model_name}</TableCell>
                                        <TableCell><BadgeView value={task.status}></BadgeView></TableCell>
                                        <TableCell>{task.server_name}</TableCell>
                                        <TableCell className="text-right">{task.create_time.replace('T', ' ')}</TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                        <PaginationComponent
                            page={currentPage}
                            pageSize={pageSize}
                            total={100}
                            onChange={(newPage) => loadTasks(newPage)}
                        />
                    </div>
                    <div className="flex-1 overflow-hidden">
                        {taskId ?
                            <FinetuneDetail id={taskId} onDelete={handleDeleteTask} onStatusChange={loadTasks}></FinetuneDetail> :
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
                            loadTasks();
                            setCreateOpen(false);
                            setTaskId(id)
                        }}></CreateTask>
                </div>
            }
        </div>
    </div>
};

const useTasks = (pageSize) => {
    const [tasks, setTasks] = useState([]);
    const filterRef = useRef({ keyword: '', type: 'all', rt: 'all' }); // 当前选项
    // page
    const [currentPage, setCurrentPage] = useState(1)
    // search input
    const searchInputRef = useRef<HTMLInputElement>(null);

    const handleSearchTask = (keyword, type, rt) => {
        filterRef.current = { keyword, type, rt };
        loadTable()
    }

    const loadTable = async (page?) => {
        page && setCurrentPage(page)

        const { type, rt, keyword } = filterRef.current
        const res = await getTasksApi({
            page: page || currentPage,
            limit: pageSize,
            keyword,
            server: rt,
            status: type
        })

        setTasks(res)
    }

    return {
        currentPage,
        tasks,
        searchInputRef,
        searchTask: handleSearchTask,
        loadTasks: loadTable
    }
}