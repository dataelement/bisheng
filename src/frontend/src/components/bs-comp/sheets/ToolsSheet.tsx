import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/bs-ui/accordion";
import { Button } from "@/components/bs-ui/button";
import { SearchInput } from "@/components/bs-ui/input";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/bs-ui/sheet";
import { getAssistantToolsApi } from "@/controllers/API/assistant";
import { useEffect, useMemo, useRef, useState } from "react";
import { TitleIconBg } from "../cardComponent";
import { ToolIcon } from "@/components/bs-icons/tool";

export default function ToolsSheet({ select, onSelect, children }) {

    const [keyword, setKeyword] = useState(' ')
    const allDataRef = useRef([])

    useEffect(() => {
        getAssistantToolsApi().then(res => {
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
                                <AccordionItem key={el.id} value={el.id} className="data-[state=open]:border-2 data-[state=open]:border-primary/20 data-[state=open]:rounded-md">
                                    <AccordionTrigger>
                                        <div className="flex gap-2 text-start relative py-4 pr-4">
                                            <TitleIconBg className="w-8 h-8 min-w-8" id={el.id} ><ToolIcon /></TitleIconBg>
                                            <div>
                                                <p className="text-sm font-medium leading-none">{el.name}</p>
                                                <p className="text-sm text-muted-foreground mt-2">{el.desc}</p>
                                            </div>
                                        </div>
                                    </AccordionTrigger>
                                    <AccordionContent className="py-2">
                                        <div className="px-6 mb-4">
                                            {el.api_params.map(api => (
                                                <div key={api.name} className="relative p-4 rounded-sm  border-t">
                                                    <h1 className="text-sm font-medium leading-none">{api.name}</h1>
                                                    <p className="text-sm text-muted-foreground mt-2">{api.desc}</p>
                                                    {/* <p className="text-sm text-muted-foreground mt-2 flex gap-2">参数:
                                                        {
                                                            api.params.map(param => (
                                                                <span>{param.name}</span>
                                                            ))
                                                        }
                                                    </p> */}
                                                    {select.some(_ => _.id === el.id) ?
                                                        <Button size="sm" className="absolute right-4 bottom-0 h-6" disabled>已添加</Button>
                                                        : <Button size="sm" className="absolute right-4 bottom-0 h-6" onClick={() => onSelect(el)}>添加</Button>
                                                    }
                                                </div>
                                            ))}
                                        </div>
                                    </AccordionContent>
                                </AccordionItem>
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
