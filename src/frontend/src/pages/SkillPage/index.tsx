import { useContext, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import {
    Tabs,
    TabsContent
} from "../../components/ui/tabs";
import { alertContext } from "../../contexts/alertContext";
import { TabsContext } from "../../contexts/tabsContext";
import { userContext } from "../../contexts/userContext";
import { readTempsDatabase, saveFlowToDatabase } from "../../controllers/API";
import { generateUUID } from "../../utils";
import CardItem from "./components/CardItem";
import CreateTemp from "./components/CreateTemp";
import SkillTemps from "./components/SkillTemps";
import Templates from "./temps";

export default function SkillPage() {
    const { user } = useContext(userContext);
    const [isTempsPage, setIsTempPage] = useState(false)

    const [open, setOpen] = useState(false)
    const navigate = useNavigate()
    const { page, flows, pages, turnPage, search, removeFlow, setFlows } = useContext(TabsContext);
    const { setErrorData } = useContext(alertContext);

    const [temps, setTemps] = useState([])
    const loadTemps = () => {
        readTempsDatabase().then(setTemps)
    }
    useEffect(() => {
        loadTemps()
    }, [])

    const { open: tempOpen, flowRef, toggleTempModal } = useCreateTemp()
    const { delShow, idRef, close, delConfim } = useDelete()
    // 分页
    const [pageEnd, setPageEnd] = useState(false)
    const loadPage = (_page) => {
        // setLoading(true)
        turnPage(_page).then(res => {
            setPageEnd(res.length < 20)
            // setLoading(false)
        })
    }

    // 选模板
    const handldSelectTemp = (el) => {
        el.name = `${el.name}-${generateUUID(5)}`
        saveFlowToDatabase({ ...el, id: el.flow_id }).then(res => {
            setOpen(false)
            setFlows(el => [res, ...el])
            navigate("/skill/" + res.id)
        }).catch(e => {
            console.error(e.response.data.detail);
            setErrorData({
                title: "提示: ",
                list: [e.response.data.detail],
            });
        })
    }

    // 输入框记忆
    const inputRef = useRef(null)
    useEffect(() => {
        // @ts-ignore
        inputRef.current.value = window.SearchInput || ''
    }, [])

    // 检索
    const timerRef = useRef(null)
    const hanldeInputChange = (e) => {
        clearTimeout(timerRef.current)
        timerRef.current = setTimeout(() => {
            const value = e.target.value
            search(value)
            // @ts-ignore
            window.SearchInput = value
        }, 500);
    }

    // 模板管理
    if (isTempsPage) return <Templates onBack={() => setIsTempPage(false)} onChange={loadTemps}></Templates>

    return <div className={`w-full p-6 h-screen overflow-y-auto`}>
        <Tabs defaultValue="my" className="w-full">
            {/* <TabsList className="">
                <TabsTrigger value="my" className="roundedrounded-xl">我的</TabsTrigger>
                <TabsTrigger value="temp">模版</TabsTrigger>
            </TabsList> */}
            <TabsContent value="my">
                <div className="flex justify-end gap-4">
                    {user.role === 'admin' && <Button className="h-8 rounded-full" onClick={() => setIsTempPage(true)}>管理技能模板</Button>}
                    <Button className="h-8 rounded-full" onClick={() => setOpen(true)}>新建</Button>
                </div>
                <span className="main-page-description-text">这里管理您的个人项目，对技能上下线、编辑等等</span>
                <Input ref={inputRef} defaultValue={window.SearchInput || ''} placeholder="技能搜索" className=" w-[400px] relative top-[-20px]" onChange={hanldeInputChange}
                // onKeyDown={e => e.key === 'Enter' && handleSearch(e)}
                ></Input>
                <div className="w-full flex flex-wrap mt-1">
                    {flows.map((flow) => (
                        <CardItem
                            key={flow.id}
                            data={flow}
                            isAdmin={user.role === 'admin'}
                            edit
                            onDelete={() => delConfim(flow.id)}
                            onCreate={toggleTempModal}
                        ></CardItem>
                    ))}
                </div>
                {/* 分页 */}
                {/* <Pagination count={10}></Pagination> */}
                <div className="join grid grid-cols-2 w-[200px] mx-auto my-4">
                    <button disabled={page === 1} className="join-item btn btn-outline btn-xs" onClick={() => loadPage(page - 1)}>上一页</button>
                    <button disabled={page >= pages || pageEnd} className="join-item btn btn-outline btn-xs" onClick={() => loadPage(page + 1)}>下一页</button>
                </div>
            </TabsContent>
            <TabsContent value="temp"> </TabsContent>
        </Tabs>
        {/* chose temp */}
        <SkillTemps flows={temps} isTemp open={open} setOpen={setOpen} onSelect={handldSelectTemp}></SkillTemps>
        {/* 添加模板 */}
        <CreateTemp flow={flowRef.current} open={tempOpen} setOpen={() => toggleTempModal()} onCreated={loadTemps} ></CreateTemp>
        {/* Open the modal using ID.showModal() method */}
        <dialog className={`modal ${delShow && 'modal-open'}`}>
            <form method="dialog" className="modal-box w-[360px] bg-[#fff] shadow-lg dark:bg-background">
                <h3 className="font-bold text-lg">提示!</h3>
                <p className="py-4">确认删除该技能？</p>
                <div className="modal-action">
                    <Button className="h-8 rounded-full" variant="outline" onClick={close}>取消</Button>
                    <Button className="h-8 rounded-full" variant="destructive" onClick={() => { removeFlow(idRef.current); close() }}>删除</Button>
                </div>
            </form>
        </dialog>
    </div>
};


const useDelete = () => {
    const [delShow, setDelShow] = useState(false)
    const idRef = useRef('')

    return {
        delShow,
        idRef,
        close: () => {
            setDelShow(false)
        },
        delConfim: (id) => {
            idRef.current = id
            setDelShow(true)
        }
    }
}

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