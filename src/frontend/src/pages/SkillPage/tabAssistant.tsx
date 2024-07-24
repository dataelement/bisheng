import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import DialogForceUpdate from "@/components/bs-ui/dialog/DialogForceUpdate";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import CardComponent from "../../components/bs-comp/cardComponent";
import { SearchInput } from "../../components/bs-ui/input";
import AutoPagination from "../../components/bs-ui/pagination/autoPagination";
import { AssistantItemDB, changeAssistantStatusApi, deleteAssistantApi, getAssistantsApi } from "../../controllers/API/assistant";
import { FlowType } from "../../types/flow";
import { useTable } from "../../util/hook";
import CreateAssistant from "./components/CreateAssistant";
import { userContext } from "@/contexts/userContext";
import { useContext, useEffect, useRef, useState } from "react";
import SelectSearch from "@/components/bs-ui/select/select"
import { getAllLabelsApi } from "@/controllers/API/label";

export default function Assistants() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { message } = useToast()
    const { user } = useContext(userContext)
    const [labels, setLabels] = useState<any[]>([])
    const labelsRef = useRef([])

    useEffect(() => {
        getAllLabelsApi().then(res => {
            const newData = res.data.map(d => ({ label:d.name, value:d.id, edit:false, selected:false }))
            labelsRef.current = newData
            setLabels(newData)
        })
    }, [])

    const { page, pageSize, data: dataSource, total, loading, setPage, search, reload, refreshData, filterData } = useTable<AssistantItemDB>({ pageSize: 15 }, (param) =>
        getAssistantsApi(param.page, param.pageSize, param.keyword, param.tag_id)
    )

    const handleDelete = (data) => {
        bsConfirm({
            desc: t('deleteAssistant'),
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

    const [selectLabel, setSelectLabel] = useState({label:'', value:-1})
    const handleLabelSearch = (id) => {
        setSelectLabel(labels.find(l => l.value === id))
        filterData({tag_id: id})
    }

    const handleSelectSearch = (e) => {
        const key = e.target.value
        const newData = labelsRef.current.filter(l => l.label.toUpperCase().includes(key.toUpperCase()) || l.value === selectLabel.value)
        setLabels(newData)
    }

    const handleClear = () => {
        setSelectLabel(pre => ({...pre, value:-1}))
        filterData({tag_id: -1})
    }

    return <div className="h-full relative">
        <div className="px-10 py-10 h-full overflow-y-scroll scrollbar-hide relative top-[-60px]">
            <div className="flex space-x-4">
                <SearchInput className="w-64" placeholder={t('build.searchAssistant')} onChange={(e) => search(e.target.value)}></SearchInput>
                <SelectSearch value={selectLabel.value === -1 ? '' : selectLabel.value} options={labels} 
                    selectPlaceholder="全部标签"
                    inputPlaceholder="搜索标签"
                    selectClass="w-64"
                    onOpenChange={() => setLabels(labelsRef.current)}
                    onChange={handleSelectSearch} 
                    onValueChange={handleLabelSearch}>
                    <div onClick={handleClear} className="bg-[#F5F5F5] rounded-sm mb-2 item-center h-[30px]">
                        <span className="ml-2 text-[#727C8F] cursor-default">清除已选项</span>
                    </div>
                </SelectSearch>
            </div>
            {/* list */}
            {
                loading
                    ? <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                        <span className="loading loading-infinity loading-lg"></span>
                    </div>
                    : <div className="mt-6 flex gap-2 flex-wrap pb-20 min-w-[980px]">
                        {/* 创建助手 */}
                        <DialogForceUpdate
                            trigger={
                                <CardComponent<FlowType>
                                    data={null}
                                    type='skill'
                                    title={t('build.createAssistant')}
                                    description={(<>
                                        <p>{t('build.createDescription')}</p>
                                        <p>{t('build.nextDescription')}</p>
                                    </>)}
                                    onClick={() => console.log('新建')}
                                ></CardComponent>
                            }>
                            <CreateAssistant ></CreateAssistant>
                        </DialogForceUpdate>
                        {
                            dataSource.map((item:any, i) => (
                                <CardComponent<AssistantItemDB>
                                    data={item}
                                    id={item.id}
                                    logo={item.logo}
                                    edit={item.write}
                                    checked={item.status === 1}
                                    type='assist'
                                    title={item.name}
                                    description={item.desc}
                                    user={item.user_name}
                                    currentUser={user}
                                    allLabels={labels}
                                    onClick={() => item.status !== 1 && navigate('/assistant/' + item.id)}
                                    onSwitchClick={() => !item.write && item.status !== 1 && message({ title: t('prompt'), description: t('skills.contactAdmin'), variant: 'warning' })}
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
        <div className="flex justify-between absolute bottom-0 left-0 w-full bg-background-main h-16 items-center px-10">
            <p className="text-sm text-muted-foreground break-keep">{t('build.manageAssistant')}</p>
            <AutoPagination className="m-0 w-auto justify-end" page={page} pageSize={pageSize} total={total} onChange={setPage}></AutoPagination>
        </div>
    </div>
};
