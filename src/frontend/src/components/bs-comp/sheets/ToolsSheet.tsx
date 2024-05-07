import { ToolIcon } from "@/components/bs-icons/tool";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/bs-ui/accordion";
import { Button } from "@/components/bs-ui/button";
import { SearchInput } from "@/components/bs-ui/input";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/bs-ui/sheet";
import { getAssistantToolsApi } from "@/controllers/API/assistant";
import { useEffect, useMemo, useRef, useState } from "react";
import { TitleIconBg } from "../cardComponent";
import ToolItem from "@/pages/SkillPage/components/ToolItem";

export default function ToolsSheet({ select, onSelect, children }) {

    const [keyword, setKeyword] = useState(' ')
    const allDataRef = useRef([])

    useEffect(() => {
        getAssistantToolsApi('all').then(res => {
            allDataRef.current = res
            setKeyword('')
        })
    }, [])

    const options = useMemo(() => {
        return allDataRef.current.filter(el => el.name.toLowerCase().includes(keyword.toLowerCase()))
    }, [keyword])

    return <Sheet onOpenChange={open => !open && setKeyword('')}>
        <SheetTrigger asChild>
            {children}
        </SheetTrigger>
        <SheetContent className="w-[1000px] sm:max-w-[1000px] bg-gray-100">
            <div className="flex h-full" onClick={e => e.stopPropagation()}>
                <div className="w-fit p-6">
                    <SheetTitle>添加工具</SheetTitle>
                    <SearchInput placeholder="搜索" className="mt-6" onChange={(e) => setKeyword(e.target.value)} />
                </div>
                <div className="flex-1 bg-[#fff] p-5 pt-12 h-full overflow-auto scrollbar-hide">
                    <Accordion type="single" collapsible className="w-full">
                        {
                            options.length ? options.map(el => (
                                <ToolItem
                                    key={el.id}
                                    type={'add'}
                                    select={select}
                                    data={el}
                                    onSelect={onSelect}
                                ></ToolItem>
                            )) : <div className="pt-40 text-center text-sm text-muted-foreground mt-2">
                                空空如也
                            </div>
                        }
                    </Accordion>
                </div>
            </div>
        </SheetContent>
    </Sheet>
};
