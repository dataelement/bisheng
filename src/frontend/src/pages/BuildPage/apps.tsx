import CardComponent from "@/components/bs-comp/cardComponent";
import LabelShow from "@/components/bs-comp/cardComponent/LabelShow";
import AppTempSheet from "@/components/bs-comp/sheets/AppTempSheet";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { MoveOneIcon } from "@/components/bs-icons/moveOne";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { SearchInput } from "@/components/bs-ui/input";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import SelectSearch from "@/components/bs-ui/select/select";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { userContext } from "@/contexts/userContext";
import { readTempsDatabase } from "@/controllers/API";
import { changeAssistantStatusApi } from "@/controllers/API/assistant";
import { deleteFlowFromDatabase, getAppsApi, saveFlowToDatabase, updataOnlineState } from "@/controllers/API/flow";
import { onlineWorkflow } from "@/controllers/API/workflow";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { AppType } from "@/types/app";
import { FlowType } from "@/types/flow";
import { useTable } from "@/util/hook";
import { generateUUID } from "@/utils";
import { useContext, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useQueryLabels } from "./assistant";
import CreateApp from "./CreateApp";
import CardSelectVersion from "./skills/CardSelectVersion";
import CreateTemp from "./skills/CreateTemp";

export const SelectType = ({ all = false, defaultValue = 'all', onChange }) => {
    const [value, setValue] = useState<string>(defaultValue)
    const options = [
        { label: '助手', value: 'assistant' },
        { label: '技能', value: 'skill' },
        { label: '工作流', value: 'flow' }
    ]
    if (all) {
        options.unshift({ label: '全部应用类型', value: 'all' })
    }

    return <Select value={value} onValueChange={(v) => { onChange(v); setValue(v) }}>
        <SelectTrigger className="max-w-32">
            <SelectValue placeholder={'全部应用类型'} />
        </SelectTrigger>
        <SelectContent>
            <SelectGroup>
                {options.map(el => (
                    <SelectItem key={el.value} value={el.value}>{el.label}</SelectItem>
                ))}
            </SelectGroup>
        </SelectContent>
    </Select>
}

const TypeNames = {
    5: AppType.ASSISTANT,
    1: AppType.SKILL,
    10: AppType.FLOW
}
export default function apps() {
    const { t } = useTranslation()
    const { user } = useContext(userContext);
    const { message } = useToast()
    const navigate = useNavigate()

    const { page, pageSize, data: dataSource, total, loading, setPage, search, reload, refreshData, filterData } = useTable<FlowType>({ pageSize: 14 }, (param) =>
        getAppsApi(param)
    )

    const { open: tempOpen, tempType, flowRef, toggleTempModal } = useCreateTemp()

    // 上下线
    const handleCheckedChange = (checked, data) => {
        if (data.flow_type === 1) {
            return captureAndAlertRequestErrorHoc(updataOnlineState(data.id, data, checked).then(res => {
                if (res) {
                    refreshData((item) => item.id === data.id, { status: checked ? 2 : 1 })
                }
                return res
            }))
        } else if (data.flow_type === 5) {
            return captureAndAlertRequestErrorHoc(changeAssistantStatusApi(data.id, checked ? 1 : 0)).then(res => {
                if (res === null) {
                    refreshData((item) => item.id === data.id, { status: checked ? 1 : 0 })
                }
                return res
            })
        } else if (data.flow_type === 10) {
            return captureAndAlertRequestErrorHoc(onlineWorkflow(data, checked ? 2 : 1)).then(res => {
                if (res === null) {
                    refreshData((item) => item.id === data.id, { status: checked ? 1 : 0 })
                }
                return res
            })
        }
    }

    const handleDelete = (data) => {
        console.log('data :>> ', data);
        const descMap = {
            [AppType.SKILL]: t('skills.confirmDeleteSkill'),
            [AppType.FLOW]: t('flows.confirmDeleteFlow'),
            [AppType.ASSISTANT]: t('assistants.confirmDeleteAssistant')
        }
        bsConfirm({
            desc: descMap[data.type],
            okTxt: t('delete'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(deleteFlowFromDatabase(data.id).then(reload));
                next()
            }
        })
    }

    const handleSetting = (data) => {
        if (data.flow_type === 5) {
            // 上线状态下，助手不能进入编辑
            navigate(`/assistant/${data.id}`)
        } else if (data.flow_type === 1) {
            const vid = data.version_list.find(item => item.is_current === 1)?.id
            navigate(`/build/skill/${data.id}/${vid}`)
        } else {
            navigate(`/flow/${data.id}`)
        }
    }

    const createAppModalRef = useRef(null)
    const handleCreateApp = async (type, tempId = 0) => {
        if (type === AppType.SKILL) {
            if (!tempId) return navigate('/build/skill')
            // 选模板(创建技能)
            const [flow] = await readTempsDatabase(type, tempId)

            flow.name = `${flow.name}-${generateUUID(5)}`
            // @ts-ignore
            captureAndAlertRequestErrorHoc(saveFlowToDatabase({ ...flow, id: flow.flow_id }).then((res: any) => {
                res.user_name = user.user_name
                res.write = true
                // setOpen(false)
                navigate(`/build/skill/${res.id}/${res.version_id}`)
            }))
        } else {
            createAppModalRef.current.open(type, tempId)
        }
    }

    const { selectLabel, setSelectLabel, setSearchKey, filteredOptions, allOptions, refetchLabels } = useQueryLabels(t)
    const handleLabelSearch = (id) => {
        setSelectLabel(allOptions.find(l => l.value === id))
        filterData({ tag_id: id })
    }

    const tempTypeRef = useRef(null)
    return <div className="h-full relative">
        <div className="px-10 py-10 h-full overflow-y-scroll scrollbar-hide relative bg-background-main border-t">
            <div className="flex gap-4">
                <SearchInput className="w-64" placeholder="搜索您需要的应用" onChange={(e) => search(e.target.value)}></SearchInput>
                <SelectType all onChange={(v) => {
                    tempTypeRef.current = v
                    filterData({ type: v })
                }} />
                <SelectSearch
                    value={!selectLabel.value ? '' : selectLabel.value}
                    options={allOptions}
                    selectPlaceholder={t('chat.allLabels')}
                    inputPlaceholder={t('chat.searchLabels')}
                    selectClass="w-52"
                    onOpenChange={() => setSearchKey('')}
                    onChange={(e) => setSearchKey(e.target.value)}
                    onValueChange={handleLabelSearch}>
                </SelectSearch>
                {user.role === 'admin' && <Button
                    variant="ghost"
                    className="hover:bg-gray-50 flex gap-2 dark:hover:bg-[#34353A] ml-auto"
                    onClick={() => navigate(`/build/temps/${tempTypeRef.current && tempTypeRef.current !== AppType.ALL ? tempTypeRef.current : AppType.ASSISTANT}`)}
                ><MoveOneIcon className="dark:text-slate-50" />管理应用模板</Button>}
            </div>
            {/* list */}
            {
                loading
                    ? <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                        <LoadingIcon />
                    </div>
                    : <div className="mt-6 flex gap-2 flex-wrap pb-20 min-w-[980px]">
                        <AppTempSheet onSelect={handleCreateApp} onCustomCreate={handleCreateApp}>
                            <CardComponent<FlowType>
                                data={null}
                                type='assist'
                                title={'新建应用'}
                                description={(<>
                                    <p>我们提供场景模板供您使用和参考</p>
                                </>)}
                            ></CardComponent>
                        </AppTempSheet>
                        {
                            dataSource.map((item: any, i) => (
                                <CardComponent<FlowType>
                                    key={item.id}
                                    data={item}
                                    id={item.id}
                                    logo={item.logo}
                                    type={TypeNames[item.flow_type]}
                                    edit={item.write}
                                    title={item.name}
                                    isAdmin={user.role === 'admin'}
                                    description={item.description}
                                    checked={item.status === 2}
                                    user={item.user_name}
                                    currentUser={user}
                                    onClick={() => handleSetting(item)}
                                    onSwitchClick={() => !item.write && item.status !== 2 && message({ title: t('prompt'), description: t('skills.contactAdmin'), variant: 'warning' })}
                                    onAddTemp={toggleTempModal}
                                    onCheckedChange={handleCheckedChange}
                                    onDelete={handleDelete}
                                    onSetting={(item) => handleSetting(item)}
                                    headSelecter={(
                                        // 技能版本
                                        item.type !== AppType.SKILL ? <CardSelectVersion
                                            showPop={item.status !== 2}
                                            data={item}
                                        ></CardSelectVersion> : null)}
                                    labelPannel={
                                        <LabelShow
                                            data={item}
                                            user={user}
                                            type={'skill'} // TODO: 三类
                                            all={filteredOptions}
                                            onChange={refetchLabels}>
                                        </LabelShow>
                                    }
                                ></CardComponent>
                            ))
                        }
                    </div>
            }
        </div>
        {/* 添加模板 */}
        <CreateTemp flow={flowRef.current} type={tempType} open={tempOpen} setOpen={() => toggleTempModal()} onCreated={() => { }} ></CreateTemp>
        {/* footer */}
        <div className="flex justify-between absolute bottom-0 left-0 w-full bg-background-main h-16 items-center px-10">
            <p className="text-sm text-muted-foreground break-keep">在此页面管理您的应用，对应用上下线、编辑等等</p>
            <AutoPagination className="m-0 w-auto justify-end" page={page} pageSize={pageSize} total={total} onChange={setPage}></AutoPagination>
        </div>
        {/* 创建应用弹窗 flow&assistant */}
        <CreateApp ref={createAppModalRef} />
    </div>
};

// 创建技能模板弹窗状态
const useCreateTemp = () => {
    const [open, setOpen] = useState(false)
    const [tempType, setType] = useState<AppType>(AppType.ALL)
    const flowRef = useRef(null)

    return {
        open,
        tempType,
        flowRef,
        toggleTempModal(flow?) {
            const map = { 10: "flow", 5: "assistant", 1: "skill" }
            flowRef.current = flow || null
            flow && setType(map[flow.flow_type])
            setOpen(!open)
        }
    }
}
