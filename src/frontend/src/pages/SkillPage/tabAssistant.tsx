import { useTranslation } from "react-i18next";
import { bsconfirm } from "../../alerts/confirm";
import CardComponent from "../../components/bs-comp/cardComponent";
import { Dialog, DialogTrigger } from "../../components/bs-ui/dialog";
import { SearchInput } from "../../components/bs-ui/input";
import AutoPagination from "../../components/bs-ui/pagination/autoPagination";
import { AssistantItemDB, deleteAssistantApi, getAssistantsApi, saveAssistanttApi } from "../../controllers/API/assistant";
import { FlowType } from "../../types/flow";
import { useTable } from "../../util/hook";
import CreateAssistant from "./components/CreateAssistant";
import { useNavigate } from "react-router-dom";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";

export default function Assistants() {
    const { t } = useTranslation()
    const navigate = useNavigate()

    const { page, pageSize, data: dataSource, total, loading, setPage, search, reload } = useTable<AssistantItemDB>({ pageSize: 11 }, (param) =>
        getAssistantsApi(param.page, param.pageSize, param.keyword)
    )

    const handleDelete = (data) => {
        bsconfirm({
            desc: '确认删除该助手？',
            okTxt: t('delete'),
            onOk(next) {
                deleteAssistantApi(data.id).then(() => reload())
                next()
            }
        })
    }

    const handleCheckedChange = (checked, id) => {
        return captureAndAlertRequestErrorHoc(saveAssistanttApi({ id, status: checked ? 1 : 0 }))
    }

    return <div className="h-full relative">
        <div className="px-10 py-10 h-full overflow-y-scroll scrollbar-hide">
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
                                        <p>没有想法？</p>
                                        <p>我们提供场景模板供您使用和参考</p>
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
                                    edit
                                    checked={item.status === 1}
                                    type='assist'
                                    title={item.name}
                                    description={item.desc}
                                    user={item.user_name}
                                    onDelete={handleDelete}
                                    onSetting={() => navigate('/assistant/' + item.id)}
                                    onCheckedChange={(checked) => handleCheckedChange(checked, item.id)}
                                ></CardComponent>
                            ))
                        }
                    </div>
            }
        </div>
        {/* footer */}
        <div className="flex justify-between absolute bottom-0 left-0 w-full bg-[#F4F5F8] h-16 items-center px-10">
            <p className="text-sm text-muted-foreground break-keep">助手是可以调用一个或者多个技能的智能体</p>
            <AutoPagination className="m-0 w-auto justify-end" page={page} pageSize={pageSize} total={total} onChange={setPage}></AutoPagination>
        </div>
    </div>
};
