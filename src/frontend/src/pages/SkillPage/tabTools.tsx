import { Accordion } from "@/components/bs-ui/accordion"
import { Button } from "@/components/bs-ui/button"
import { SearchInput } from "@/components/bs-ui/input"
import { getAssistantToolsApi } from "@/controllers/API/assistant"
import { PersonIcon, StarFilledIcon } from "@radix-ui/react-icons"
import { useEffect, useMemo, useRef, useState } from "react"
import EditTool from "./components/EditTool"
import ToolItem from "./components/ToolItem"

export default function tabTools({ select = null, onSelect }) {
    const [keyword, setKeyword] = useState(' ')
    const [allData, setAllData] = useState([])

    const [type, setType] = useState('') // '' add edit
    const editRef = useRef(null)

    const loadData = (_type = 'custom') => {
        getAssistantToolsApi(_type).then(res => {
            setAllData(res)
            setKeyword('')
        })
    }
    useEffect(() => {
        loadData(type === '' ? 'default' : 'custom')
    }, [type])

    const options = useMemo(() => {
        return allData.filter(el => el.name.toLowerCase().includes(keyword.toLowerCase()))
    }, [keyword, allData])


    return <div className="flex h-full relative" onClick={e => e.stopPropagation()}>
        <div className="w-full flex h-full overflow-y-scroll scrollbar-hide  relative top-[-60px]">
            <div className="w-fit p-6">
                <h1>添加工具</h1>
                <SearchInput placeholder="搜索" className="mt-6" onChange={(e) => setKeyword(e.target.value)} />
                <Button className="w-full mt-4" onClick={() => editRef.current.open()} >创建自定义工具</Button>
                <div className="mt-4">
                    <div
                        className={`flex items-center gap-2 px-4 py-2 rounded-md cursor-pointer hover:bg-muted-foreground/10 transition-all duration-200 ${type === '' && 'bg-muted-foreground/10'}`}
                        onClick={() => setType('')}
                    >
                        <PersonIcon />
                        <span>内置工具</span>
                    </div>
                    <div
                        className={`flex items-center gap-2 px-4 py-2 rounded-md cursor-pointer hover:bg-muted-foreground/10 transition-all duration-200 mt-1 ${type === 'edit' && 'bg-muted-foreground/10'}`}
                        onClick={() => setType('edit')}
                    >
                        <StarFilledIcon />
                        <span>自定义工具</span>
                    </div>
                </div>
            </div>
            <div className="w-full flex-1 bg-[#fff] p-5 pt-12 h-full overflow-auto scrollbar-hide">
                <Accordion type="single" collapsible className="w-full">
                    {
                        options.length ? options.map(el => (
                            <ToolItem
                                key={el.id}
                                type={type}
                                select={select}
                                data={el}
                                onSelect={onSelect}
                                onEdit={(id) => editRef.current.edit(el)}
                            ></ToolItem>
                        )) : <div className="pt-40 text-center text-sm text-muted-foreground mt-2">
                            空空如也
                        </div>
                    }
                </Accordion>
            </div>
        </div>
        {/* footer */}
        <div className="flex justify-between absolute bottom-0 left-0 w-full bg-[#F4F5F8] h-16 items-center px-10">
            <p className="text-sm text-muted-foreground break-keep">在此页面管理您的自定义工具，对自定义工具创建、编辑等等</p>
        </div>

        <EditTool onReload={loadData} ref={editRef} />
    </div>
};
