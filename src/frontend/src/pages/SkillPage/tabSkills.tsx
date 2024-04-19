import SkillTempSheet from "@/components/bs-comp/sheets/SkillTempSheet";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { useContext, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import CardComponent from "../../components/bs-comp/cardComponent";
import { MoveOneIcon } from "../../components/bs-icons/moveOne";
import { Button } from "../../components/bs-ui/button";
import { SearchInput } from "../../components/bs-ui/input";
import AutoPagination from "../../components/bs-ui/pagination/autoPagination";
import { userContext } from "../../contexts/userContext";
import { readTempsDatabase } from "../../controllers/API";
import { deleteFlowFromDatabase, readFlowsFromDatabase, saveFlowToDatabase, updataOnlineState } from "../../controllers/API/flow";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import { FlowType } from "../../types/flow";
import { useTable } from "../../util/hook";
import { generateUUID } from "../../utils";
import CreateTemp from "./components/CreateTemp";

export default function Skills() {
    const { t } = useTranslation()
    const { user } = useContext(userContext);
    const { message } = useToast()
    const navigate = useNavigate()

    const { page, pageSize, data: dataSource, total, loading, setPage, search, reload, refreshData } = useTable<FlowType>({ pageSize: 14 }, (param) =>
        readFlowsFromDatabase(param.page, param.pageSize, param.keyword)
    )
    const [open, setOpen] = useState(false)

    const { open: tempOpen, flowRef, toggleTempModal } = useCreateTemp()

    // 上下线
    const handleCheckedChange = (checked, data) => {
        return captureAndAlertRequestErrorHoc(updataOnlineState(data.id, data, checked).then(res => {
            if (res) {
                refreshData((item) => item.id === data.id, { status: checked ? 2 : 1 })
            }
            return res
        }))
    }

    const handleDelete = (data) => {
        bsConfirm({
            desc: t('skills.confirmDeleteSkill'),
            okTxt: t('delete'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(deleteFlowFromDatabase(data.id).then(reload));
                next()
            }
        })
    }

    const handleSetting = (data) => {
        // console.log('data :>> ', data);
        navigate("/build/skill/" + data.id)
    }

    // 选模板(创建技能)
    const handldSelectTemp = async (tempId) => {
        const [flow] = await readTempsDatabase(tempId)

        flow.name = `${flow.name}-${generateUUID(5)}`
        captureAndAlertRequestErrorHoc(saveFlowToDatabase({ ...flow, id: flow.flow_id }).then(res => {
            res.user_name = user.user_name
            res.write = true
            setOpen(false)
            navigate("/build/skill/" + res.id)
        }))
    }

    return <div className="h-full relative">
        <div className="px-10 py-10 h-full overflow-y-scroll scrollbar-hide  relative top-[-60px]">
            <div className="flex gap-2">
                <SearchInput className="w-64" placeholder={t('skills.skillSearch')} onChange={(e) => search(e.target.value)}></SearchInput>
                {user.role === 'admin' && <Button
                    variant="ghost"
                    className="hover:bg-gray-50 flex gap-2"
                    onClick={() => navigate('/build/temps')}
                ><MoveOneIcon />{t('skills.manageTemplate')}</Button>}
            </div>
            {/* list */}
            {
                loading
                    ? <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                        <span className="loading loading-infinity loading-lg"></span>
                    </div>
                    : <div className="mt-6 flex gap-2 flex-wrap pb-20 min-w-[980px]">
                        <SkillTempSheet onSelect={handldSelectTemp}>
                            <CardComponent<FlowType>
                                data={null}
                                type='skill'
                                title={t('skills.createNew')}
                                description={(<>
                                    <p>技能通过可视化的流程编排，明确任务执行步骤</p>
                                    <p>我们提供场景模板供您使用和参考</p>
                                </>)}
                            ></CardComponent>
                        </SkillTempSheet>
                        {
                            dataSource.map((item, i) => (
                                <CardComponent<FlowType>
                                    data={item}
                                    id={item.id}
                                    type='skill'
                                    edit={item.write}
                                    title={item.name}
                                    isAdmin={user.role === 'admin'}
                                    description={item.description}
                                    checked={item.status === 2}
                                    user={item.user_name}
                                    onClick={() => item.status !== 2 && handleSetting(item)}
                                    onSwitchClick={() => !item.write && item.status !== 2 && message({ title: '提示', description: '请联系管理员上线技能', variant: 'warning' })}
                                    onAddTemp={toggleTempModal}
                                    onCheckedChange={handleCheckedChange}
                                    onDelete={handleDelete}
                                    onSetting={handleSetting}
                                ></CardComponent>
                            ))
                        }
                    </div>
            }
        </div>
        {/* 添加模板 */}
        <CreateTemp flow={flowRef.current} open={tempOpen} setOpen={() => toggleTempModal()} onCreated={() => { }} ></CreateTemp>
        {/* footer */}
        <div className="flex justify-between absolute bottom-0 left-0 w-full bg-[#F4F5F8] h-16 items-center px-10">
            <p className="text-sm text-muted-foreground break-keep">{t('skills.manageProjects')}</p>
            <AutoPagination className="m-0 w-auto justify-end" page={page} pageSize={pageSize} total={total} onChange={setPage}></AutoPagination>
        </div>
    </div>
};

// 创建技能模板弹窗状态
const useCreateTemp = () => {
    const [open, setOpen] = useState(false)
    const flowRef = useRef(null)

    return {
        open,
        flowRef,
        toggleTempModal(flow?) {
            flowRef.current = flow || null
            setOpen(!open)
        }
    }
}
