import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { bsconfirm } from "../../alerts/confirm";
import { MoveOneIcon } from "../../components/bs-icons/moveOne";
import { Button } from "../../components/bs-ui/button";
import { SearchInput } from "../../components/bs-ui/input";
import AutoPagination from "../../components/bs-ui/pagination/autoPagination";
import CardComponent from "../../components/cardComponent";
import { userContext } from "../../contexts/userContext";
import { readTempsDatabase } from "../../controllers/API";
import { deleteFlowFromDatabase, readFlowsFromDatabase, saveFlowToDatabase, updataOnlineState } from "../../controllers/API/flow";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import { FlowType } from "../../types/flow";
import { useTable } from "../../util/hook";
import { generateUUID } from "../../utils";
import CreateTemp from "./components/CreateTemp";
import SkillTemps from "./components/SkillTemps";
import Templates from "./temps";

export default function Skills() {
    const { t } = useTranslation()
    const { user } = useContext(userContext);
    const navigate = useNavigate()

    const { page, pageSize, data: dataSource, total, loading, setPage, search, reload } = useTable<FlowType>({ pageSize: 11 }, (param) =>
        readFlowsFromDatabase(param.page, param.pageSize, param.keyword)
    )

    // template
    const [temps, loadTemps] = useTemps()
    const [open, setOpen] = useState(false)

    const { open: tempOpen, flowRef, toggleTempModal } = useCreateTemp()
    const [isTempsPage, setIsTempPage] = useState(false)

    // 上下线
    const handleCheckedChange = (checked, data) => {
        return captureAndAlertRequestErrorHoc(updataOnlineState(data.id, data, checked).then(res => {
            data.status = checked ? 2 : 1
        }))
    }

    const handleDelete = (data) => {
        bsconfirm({
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
        navigate("/skill/" + data.id)
    }

    // 选模板(创建技能)
    const handldSelectTemp = async (el) => {
        const [flow] = await readTempsDatabase(el.id)

        flow.name = `${flow.name}-${generateUUID(5)}`
        captureAndAlertRequestErrorHoc(saveFlowToDatabase({ ...flow, id: flow.flow_id }).then(res => {
            res.user_name = user.user_name
            res.write = true
            setOpen(false)
            navigate("/skill/" + res.id)
        }))
    }
    // 模板管理
    if (isTempsPage) return <Templates onBack={() => setIsTempPage(false)} onChange={loadTemps}></Templates>

    return <div className="h-full relative">
        <div className="px-10 py-10 h-full overflow-y-scroll scrollbar-hide">
            <div className="flex gap-2">
                <SearchInput className="w-64" placeholder={t('skills.skillSearch')} onChange={(e) => search(e.target.value)}></SearchInput>
                {user.role === 'admin' && <Button
                    variant="ghost"
                    className="hover:bg-gray-50 flex gap-2"
                    onClick={() => setIsTempPage(true)}
                ><MoveOneIcon />{t('skills.manageTemplate')}</Button>}
            </div>
            {/* list */}
            {
                loading
                    ? <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
                        <span className="loading loading-infinity loading-lg"></span>
                    </div>
                    : <div className="mt-6 flex gap-2 flex-wrap pb-20 min-w-[980px]">
                        <CardComponent<FlowType>
                            data={null}
                            type='skill'
                            title={t('skills.createNew')}
                            description={(<>
                                <p>没有想法？</p>
                                <p>我们提供场景模板供您使用和参考</p>
                            </>)}
                            onClick={() => setOpen(true)}
                        ></CardComponent>
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
        {/* chose template */}
        <SkillTemps flows={temps} isTemp open={open} setOpen={setOpen} onSelect={handldSelectTemp}></SkillTemps>
        {/* 添加模板 */}
        <CreateTemp flow={flowRef.current} open={tempOpen} setOpen={() => toggleTempModal()} onCreated={loadTemps} ></CreateTemp>
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

// 获取模板数据
const useTemps = () => {
    const [temps, setTemps] = useState([]);

    const loadTemps = () => {
        readTempsDatabase().then(setTemps);
    };

    useEffect(() => {
        loadTemps();
    }, []);

    return [temps, loadTemps];
};