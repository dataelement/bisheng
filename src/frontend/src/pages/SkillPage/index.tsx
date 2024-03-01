import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { bsconfirm } from "../../alerts/confirm";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Tabs, TabsContent } from "../../components/ui/tabs";
import { alertContext } from "../../contexts/alertContext";
import { userContext } from "../../contexts/userContext";
import { readTempsDatabase } from "../../controllers/API";
import { deleteFlowFromDatabase, getFlowApi, readFlowsFromDatabase, saveFlowToDatabase } from "../../controllers/API/flow";
import { useDebounce } from "../../util/hook";
import { generateUUID } from "../../utils";
import CardItem from "./components/CardItem";
import CreateTemp from "./components/CreateTemp";
import SkillTemps from "./components/SkillTemps";
import Templates from "./temps";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import { Search } from "lucide-react";

export default function SkillPage() {
    const { t } = useTranslation()

    const [isTempsPage, setIsTempPage] = useState(false)

    const [open, setOpen] = useState(false)
    const navigate = useNavigate()

    const { page, loading, inputRef, search, loadPage, delFlow } = useSkills()

    const [temps, loadTemps] = useTemps()
    const { open: tempOpen, flowRef, toggleTempModal } = useCreateTemp()

    const handleDelete = (id) => {
        bsconfirm({
            desc: t('skills.confirmDeleteSkill'),
            okTxt: t('delete'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(deleteFlowFromDatabase(id).then(() => delFlow(id)));
                next()
            }
        })
    }

    const { user } = useContext(userContext);
    const { setErrorData } = useContext(alertContext);
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

    return <div className={`w-full p-6 h-screen overflow-y-auto`}>
        {/* loading */}
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <span className="loading loading-infinity loading-lg"></span>
        </div>}

        {/* 技能列表 */}
        <Tabs defaultValue="my" className="w-full">
            <TabsContent value="my">
                <div className="flex justify-end gap-4">
                    {user.role === 'admin' && <Button className="h-8 rounded-full" onClick={() => setIsTempPage(true)}>{t('skills.manageTemplate')}</Button>}
                    <Button className="h-8 rounded-full" onClick={() => setOpen(true)}>{t('skills.createNew')}</Button>
                </div>
                <span className="main-page-description-text">{t('skills.manageProjects')}</span>
                <div className="w-[400px] relative top-[-20px]">
                    <Input
                        ref={inputRef}
                        defaultValue={window.SearchSkillsPage?.key || ''}
                        placeholder={t('skills.skillSearch')}
                        className=""
                        onChange={e => search(e.target.value)}></Input>
                    <Search className="absolute right-4 top-2 text-gray-300 pointer-events-none"></Search>
                </div>
                {/* cards */}
                <div className="w-full flex flex-wrap mt-1">
                    {page.flows.map((flow) => (
                        <CardItem
                            key={flow.id}
                            data={flow}
                            isAdmin={user.role === 'admin'}
                            edit={flow.write}
                            onDelete={() => handleDelete(flow.id)}
                            onCreate={toggleTempModal}
                            onBeforeEdit={() =>
                                window.SearchSkillsPage = { no: page.pageNo, key: inputRef.current.value } // 临时缓存方案
                            }
                        ></CardItem>
                    ))}
                </div>
                {/* 分页 */}
                {/* <Pagination count={10}></Pagination> */}
                <div className="join grid grid-cols-2 w-[200px] mx-auto my-4">
                    <button disabled={page.pageNo === 1} className="join-item btn btn-outline btn-xs" onClick={() => loadPage(page.pageNo - 1)}>{t('previousPage')}</button>
                    <button disabled={page.end} className="join-item btn btn-outline btn-xs" onClick={() => loadPage(page.pageNo + 1)}>{t('nextPage')}</button>
                </div>
            </TabsContent>
            <TabsContent value="temp"> </TabsContent>
        </Tabs>
        {/* chose template */}
        <SkillTemps flows={temps} isTemp open={open} setOpen={setOpen} onSelect={handldSelectTemp}></SkillTemps>
        {/* 添加模板 */}
        <CreateTemp flow={flowRef.current} open={tempOpen} setOpen={() => toggleTempModal()} onCreated={loadTemps} ></CreateTemp>
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

// 技能列表相关
const useSkills = () => {
    const [page, setPage] = useState({
        pageNo: 1,
        pages: 0,
        flows: [],
        end: false
    })
    const [loading, setLoading] = useState(false)
    // 分页
    const loadPage = (_page) => {
        setLoading(true)
        readFlowsFromDatabase(_page, inputRef.current.value || '').then(res => {
            setPage({
                pageNo: _page,
                pages: res.pages,
                flows: res.data,
                end: res.pages === _page
            })
            setLoading(false)
        })
    }

    const inputRef = useRef(null)
    useEffect(() => {
        // 输入框记忆
        if (window.SearchSkillsPage) {
            loadPage(window.SearchSkillsPage.no)
            delete window.SearchSkillsPage
            return
        }
        loadPage(1)
    }, [])

    // search
    function search(value) {
        loadPage(1)
    }

    return {
        page,
        loading,
        inputRef,
        loadPage,
        search: useDebounce(search, 600, false),
        delFlow: (id) => {
            setPage((data) => ({
                ...data,
                flows: data.flows.filter(item => item.id !== id)
            }));
        }
    }
}
