import CardComponent from "@/components/bs-comp/cardComponent";
import LabelShow from "@/components/bs-comp/cardComponent/LabelShow";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import DialogForceUpdate from "@/components/bs-ui/dialog/DialogForceUpdate";
import { SearchInput } from "@/components/bs-ui/input";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import SelectSearch from "@/components/bs-ui/select/select";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { userContext } from "@/contexts/userContext";
import { AssistantItemDB, changeAssistantStatusApi, deleteAssistantApi, getAssistantsApi } from "@/controllers/API/assistant";
import { getAllLabelsApi } from "@/controllers/API/label";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { FlowType } from "@/types/flow";
import { useTable } from "@/util/hook";
import { useContext, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from 'react-query';
import { useNavigate } from "react-router-dom";
import CreateAssistant from "./CreateAssistant";

export default function Assistants() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { message } = useToast()
    const { user } = useContext(userContext)

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

    const { selectLabel, setSelectLabel, setSearchKey, filteredOptions, allOptions, refetchLabels } = useQueryLabels(t)
    const handleLabelSearch = (id) => {
        setSelectLabel(allOptions.find(l => l.value === id))
        filterData({ tag_id: id })
    }

    return <div className="h-full relative bg-background-main border-t">
        <div className="px-10 py-10 h-full overflow-y-scroll scrollbar-hide relative">
            <div className="flex space-x-4">
                <SearchInput className="w-64" placeholder={t('build.searchAssistant')} onChange={(e) => search(e.target.value)}></SearchInput>
                <SelectSearch value={!selectLabel.value ? '' : selectLabel.value} options={allOptions}
                    selectPlaceholder={t('chat.allLabels')}
                    inputPlaceholder={t('chat.searchLabels')}
                    selectClass="w-64"
                    onOpenChange={() => setSearchKey('')}
                    onChange={(e) => setSearchKey(e.target.value)}
                    onValueChange={handleLabelSearch}>
                </SelectSearch>
            </div>
            {/* list */}
            {
                loading
                    ? <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                        <LoadingIcon />
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
                            dataSource.map((item: any, i) => (
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
                                    onClick={() => item.status !== 1 && navigate('/assistant/' + item.id)}
                                    onSwitchClick={() => !item.write && item.status !== 1 && message({ title: t('prompt'), description: t('skills.contactAdmin'), variant: 'warning' })}
                                    onDelete={handleDelete}
                                    onSetting={() => navigate('/assistant/' + item.id)}
                                    onCheckedChange={handleCheckedChange}
                                    labelPannel={
                                        <LabelShow
                                            data={item}
                                            user={user}
                                            type={'assist'}
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
        {/* footer */}
        <div className="flex justify-between absolute bottom-0 left-0 w-full bg-background-main h-16 items-center px-10">
            <p className="text-sm text-muted-foreground break-keep">{t('build.manageAssistant')}</p>
            <AutoPagination className="m-0 w-auto justify-end" page={page} pageSize={pageSize} total={total} onChange={setPage}></AutoPagination>
        </div>
    </div>
};


export const useQueryLabels = (t) => {
    const { data: options, refetch } = useQuery({
        queryKey: "QueryLabelsKey",
        queryFn: () => getAllLabelsApi().then(res =>
            res.data.map(d => ({ label: d.name, value: d.id, edit: false, selected: false }))
        )
    });

    const [searchKey, setSearchKey] = useState('');
    const [selectLabel, setSelectLabel] = useState({ label: '', value: null })

    const [filteredOptions, allOptions] = useMemo(() => {
        if (!options) return [[], []]
        const topItem = { label: t('all'), value: -1, edit: false, selected: false }
        if (!searchKey) return [options, [topItem, ...options]];
        // 检索
        const _newOptions = options.filter(op => op.label.toUpperCase().includes(searchKey.toUpperCase()) || op.value === selectLabel.value)
        return [_newOptions, [topItem, ..._newOptions]]
    }, [searchKey, options, selectLabel])

    return {
        selectLabel,
        setSelectLabel,
        setSearchKey,
        filteredOptions,
        allOptions,
        refetchLabels: refetch
    }
}