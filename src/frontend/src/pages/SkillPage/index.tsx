import { useContext, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import {
    Tabs,
    TabsContent
} from "../../components/ui/tabs";
import { TabsContext } from "../../contexts/tabsContext";
import { readTempsDatabase, saveFlowToDatabase } from "../../controllers/API";
import { generateUUID } from "../../utils";
import CardItem from "./components/CardItem";
import SkillTemps from "./components/SkillTemps";


export default function SkillPage() {
    const [open, setOpen] = useState(false)
    const navigate = useNavigate()
    const { flows, turnPage, search, removeFlow, setFlows } = useContext(TabsContext);
    const handleCreate = () => {
        navigate("/files");
        setOpen(false)
    }

    const [temps, setTemps] = useState([])
    useEffect(() => {
        readTempsDatabase().then(res => {
            setTemps(res)
        })
    }, [])

    const { delShow, idRef, close, delConfim } = useDelete()
    // 分页
    const [page, setPage] = useState(1)
    const [pageEnd, setPageEnd] = useState(false)
    const loadPage = (_page) => {
        // setLoading(true)
        setPage(_page)
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

    // [我的 模板]
    // 我的有 新建；弹窗（名称和描述）;成功跳转编排页
    // 卡片列表（id取余头像 标题 描述 上下线 编辑）；我的 有上下线，上线后不可编辑；模板显示添加，添加后跳转个人列表
    return <div className={`w-full p-6 h-screen overflow-y-auto`}>
        <Tabs defaultValue="my" className="w-full">
            {/* <TabsList className="">
                <TabsTrigger value="my" className="roundedrounded-xl">我的</TabsTrigger>
                <TabsTrigger value="temp">模版</TabsTrigger>
            </TabsList> */}
            <TabsContent value="my">
                <div className="flex justify-end"><Button className="h-8 rounded-full" onClick={() => setOpen(true)}>新建</Button></div>
                <span className="main-page-description-text">这里管理您的个人项目，对技能上下线、编辑等等</span>
                <Input ref={inputRef} placeholder="技能搜索" className=" w-[400px] relative top-[-20px]" onChange={hanldeInputChange}
                // onKeyDown={e => e.key === 'Enter' && handleSearch(e)}
                ></Input>
                <div className="w-full flex flex-wrap mt-1">
                    {flows.map((flow) => (
                        <CardItem key={flow.id} data={flow} edit onDelete={() => delConfim(flow.id)}></CardItem>
                    ))}
                </div>
                {/* 分页 */}
                {/* <Pagination count={10}></Pagination> */}
                <div className="join grid grid-cols-2 w-[200px] mx-auto">
                    <button disabled={page === 1} className="join-item btn btn-outline btn-xs" onClick={() => loadPage(page - 1)}>上一页</button>
                    <button disabled={pageEnd} className="join-item btn btn-outline btn-xs" onClick={() => loadPage(page + 1)}>下一页</button>
                </div>
            </TabsContent>
            <TabsContent value="temp">
                {/* <div className="w-full flex flex-wrap mt-11">
                    {[1, 2, 3, 4].map((item, i) => (
                        <CardItem key={item} index={i}></CardItem>
                    ))}
                </div> */}
                {/* 分页 */}
            </TabsContent>
        </Tabs>
        {/* 添加模型 */}
        <SkillTemps flows={temps} isTemp open={open} setOpen={setOpen} onSelect={handldSelectTemp}></SkillTemps>
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