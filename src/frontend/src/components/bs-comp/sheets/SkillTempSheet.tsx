import { readTempsDatabase } from "@/controllers/API";
import { useEffect, useMemo, useRef, useState } from "react";
import { SearchInput } from "../../bs-ui/input";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "../../bs-ui/sheet";
import CardComponent from "../cardComponent";
import { useNavigate } from "react-router-dom";

export default function SkillTempSheet({ children, onSelect }) {
    const [open, setOpen] = useState(false)

    const navigate = useNavigate()

    const [keyword, setKeyword] = useState(' ')
    const allDataRef = useRef([])

    useEffect(() => {
        readTempsDatabase().then(res => {
            allDataRef.current = res
            setKeyword('')
        })
    }, [])

    const options = useMemo(() => {
        return allDataRef.current.filter(el => el.name.toLowerCase().includes(keyword.toLowerCase()))
    }, [keyword])

    return <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
            {children}
        </SheetTrigger>
        <SheetContent className="sm:min-w-[966px] bg-gray-100">
            <div className="flex h-full">
                <div className="w-fit pr-6">
                    <SheetTitle>技能模板</SheetTitle>
                    <SheetDescription>您可以从这里挑选一个模板开始，或者自定义高级模板</SheetDescription>
                    <SearchInput value={keyword} placeholder="搜索" className="my-6" onChange={(e) => setKeyword(e.target.value)} />
                </div>
                <div className="flex-1 min-w-[696px] bg-[#fff] p-6 h-full flex flex-wrap gap-1 overflow-y-auto scrollbar-hide content-start">
                    <CardComponent
                        id={0}
                        type="sheet"
                        data={null}
                        title='自定义技能'
                        description=''
                        onClick={() => navigate('/skill')}
                    ></CardComponent>
                    {
                        options.map((flow, i) => (
                            <CardComponent key={i}
                                id={i + 1}
                                data={flow}
                                title={flow.name}
                                description={flow.description}
                                type="sheet"
                                footer={null}
                                onClick={() => { onSelect(flow.id); setOpen(false) }}
                            />
                        ))
                    }
                </div>
            </div>
        </SheetContent>
    </Sheet>
};
