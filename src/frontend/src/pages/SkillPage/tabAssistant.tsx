import { useTranslation } from "react-i18next";
import CardComponent from "../../components/bs-comp/cardComponent";
import { Dialog, DialogTrigger } from "../../components/bs-ui/dialog";
import { SearchInput } from "../../components/bs-ui/input";
import AutoPagination from "../../components/bs-ui/pagination/autoPagination";
import { AssistantItemDB, changeAssistantStatusApi, deleteAssistantApi, getAssistantsApi, saveAssistanttApi } from "../../controllers/API/assistant";
import { FlowType } from "../../types/flow";
import { useTable } from "../../util/hook";
import CreateAssistant from "./components/CreateAssistant";
import { useNavigate } from "react-router-dom";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";

export default function Assistants() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { message } = useToast()

    const { page, pageSize, data: dataSource, total, loading, setPage, search, reload, refreshData } = useTable<AssistantItemDB>({ pageSize: 15 }, (param) =>
        getAssistantsApi(param.page, param.pageSize, param.keyword)
    )

    const handleDelete = (data) => {
        bsConfirm({
            desc: '确认删除该助手？',
            okTxt: t('delete'),
            onOk(next) {
                deleteAssistantApi(data.id).then(() => reload())
                next()
            }
        })
    }

    const handleCheckedChange = (checked, data) => {
        return captureAndAlertRequestErrorHoc(changeAssistantStatusApi(data.id, checked ? 1 : 0)).then(res => {
            if (res === null) {
                refreshData((item) => item.id === data.id, { status: checked ? 1 : 0 })
            }
            return res
        })
    }

    return <div className="h-full relative">
        <div className="px-10 py-10 h-full overflow-y-scroll scrollbar-hide relative top-[-60px]">
            <div className="flex">
                <SearchInput className="w-64" placeholder="搜索您需要的助手" onChange={(e) => search(e.target.value)}></SearchInput>
            </div>
            {/* list */}
            {
                loading
                    ? <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                        <span className="loading loading-infinity loading-lg"></span>
                    </div>
                    : <div className="mt-6 flex gap-2 flex-wrap pb-20 min-w-[980px]">
                        {/* 创建助手 */}
                        <Dialog>
                            <DialogTrigger asChild>
                                <CardComponent<FlowType>
                                    data={null}
                                    type='skill'
                                    title="新建助手"
                                    description={(<>
                                        <p>通过描述角色和任务来创建你的助手</p>
                                        <p>助手可以调用多个技能和工具</p>
                                    </>)}
                                    onClick={() => console.log('新建')}
                                ></CardComponent>
                            </DialogTrigger>
                            <CreateAssistant ></CreateAssistant>
                        </Dialog>
                        {
                            dataSource.map((item, i) => (
                                <CardComponent<AssistantItemDB>
                                    data={item}
                                    id={item.id}
                                    edit={item.write}
                                    checked={item.status === 1}
                                    type='assist'
                                    title={item.name}
                                    description={item.desc}
                                    user={item.user_name}
                                    onClick={() => item.status !== 1 && navigate('/assistant/' + item.id)}
                                    onSwitchClick={() => !item.write && item.status !== 1 && message({ title: '提示', description: '请联系管理员上线助手', variant: 'warning' })}
                                    onDelete={handleDelete}
                                    onSetting={() => navigate('/assistant/' + item.id)}
                                    onCheckedChange={handleCheckedChange}
                                ></CardComponent>
                            ))
                        }
                    </div>
            }
        </div>
        {/* footer */}
        <div className="flex justify-between absolute bottom-0 left-0 w-full bg-[#F4F5F8] h-16 items-center px-10">
            <p className="text-sm text-muted-foreground break-keep">在此页面管理您的助手，对助手上下线、编辑等等</p>
            <AutoPagination className="m-0 w-auto justify-end" page={page} pageSize={pageSize} total={total} onChange={setPage}></AutoPagination>
        </div>
    </div>
};
