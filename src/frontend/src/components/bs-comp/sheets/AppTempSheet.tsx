import { readTempsDatabase } from "@/controllers/API";
import { AppType } from "@/types/app";
import { Bot, Boxes, Workflow } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { SearchInput } from "../../bs-ui/input";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "../../bs-ui/sheet";
import CardComponent from "../cardComponent";

/** 应用模板选择 */
export default function AppTempSheet({ children, onCustomCreate, onSelect }) {
    const [open, setOpen] = useState(false)
    const [type, setType] = useState<AppType>(AppType.ASSISTANT)
    const createDesc = useMemo(() => {
        const descs = {
            [AppType.ASSISTANT]: {
                title: '自定义助手',
                desc: <>
                    <p>通过描述角色和任务来零代码创建应用</p>
                    <p>助手可以调用多个技能和工具</p>
                </>
            },
            [AppType.FLOW]: {
                title: '自定义工作流',
                desc: '通过简单的节点编排任务流程，支持并行和成环，支持工作流执行过程中复杂人机交互'
            },
            [AppType.SKILL]: {
                title: '自定义技能',
                desc: '通过丰富的组件搭建应用，提供更多参数以供效果调优。'
            }
        }
        return descs[type]
    }, [type])

    const navigate = useNavigate()
    const { t } = useTranslation()

    const [keyword, setKeyword] = useState(' ')
    const allDataRef = useRef([])

    useEffect(() => {
        setKeyword(' ')
        readTempsDatabase(type).then(res => {
            allDataRef.current = res
            setKeyword('')
        })
    }, [type])

    const options = useMemo(() => {
        return allDataRef.current.filter(el => el.name.toLowerCase().includes(keyword.toLowerCase()))
    }, [keyword])

    return <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
            {children}
        </SheetTrigger>
        <SheetContent className="sm:min-w-[966px] ">
            <div className="flex h-full" onClick={e => e.stopPropagation()}>
                <div className="w-fit p-6">
                    <SheetTitle>应用模板</SheetTitle>
                    <SheetDescription>您可以选择一个模板开始，或者自定义创建一个空白应用</SheetDescription>
                    <SearchInput value={keyword} placeholder={t('build.search')} className="my-6" onChange={(e) => setKeyword(e.target.value)} />
                    {/* type */}
                    <div className="mt-4">
                        <div
                            className={`flex items-center gap-2 px-4 py-2 rounded-md cursor-pointer hover:bg-muted-foreground/10 transition-all duration-200 mt-1 ${type === AppType.FLOW && 'bg-muted-foreground/10'}`}
                            onClick={() => setType(AppType.FLOW)}
                        >
                            <Workflow />
                            <span>工作流</span>
                        </div>
                        <div
                            className={`flex items-center gap-2 px-4 py-2 rounded-md cursor-pointer hover:bg-muted-foreground/10 transition-all duration-200 ${type === AppType.ASSISTANT && 'bg-muted-foreground/10'}`}
                            onClick={() => setType(AppType.ASSISTANT)}
                        >
                            <Bot />
                            <span>助手</span>
                        </div>
                        <div
                            className={`flex items-center gap-2 px-4 py-2 rounded-md cursor-pointer hover:bg-muted-foreground/10 transition-all duration-200 mt-1 ${type === AppType.SKILL && 'bg-muted-foreground/10'}`}
                            onClick={() => setType(AppType.SKILL)}
                        >
                            <Boxes />
                            <span>技能</span>
                        </div>
                    </div>
                </div>
                <div className="flex-1 min-w-[696px] bg-[#fff] dark:bg-[#030712] p-5 pt-12 h-full flex flex-wrap gap-1.5 overflow-y-auto scrollbar-hide content-start">
                    <CardComponent
                        id={0}
                        type="sheet"
                        data={null}
                        title={createDesc.title}
                        description={createDesc.desc}
                        onClick={() => { onCustomCreate(type); setOpen(false) }}
                    // onClick={() => navigate('/build/skill')}
                    ></CardComponent>
                    {
                        options.map((flow, i) => (
                            <CardComponent key={i}
                                id={i + 1}
                                data={flow}
                                logo={flow.logo}
                                title={flow.name}
                                description={flow.description}
                                type="sheet"
                                footer={null}
                                onClick={() => { onSelect(type, flow.id); setOpen(false) }}
                            />
                        ))
                    }
                </div>
            </div>
        </SheetContent>
    </Sheet>
};
