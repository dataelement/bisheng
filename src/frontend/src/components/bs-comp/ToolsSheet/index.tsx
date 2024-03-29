import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/bs-ui/accordion";
import { Button } from "@/components/bs-ui/button";
import { SearchInput } from "@/components/bs-ui/input";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/bs-ui/sheet";
import { readFileLibDatabase } from "@/controllers/API";
import { useTable } from "@/util/hook";
import { useState } from "react";
import { TitleIconBg } from "../cardComponent";

export default function ToolsSheet({ select, onSelect, children }) {

    const [keyword, setKeyword] = useState('')
    const { data, search } = useTable<any>({}, (params) =>
        readFileLibDatabase(params.page, params.pageSize, params.keyword)
    )

    const handleSearch = (e) => {
        const { value } = e.target
        setKeyword(value)
        search(value)
    }

    return <Sheet>
        <SheetTrigger asChild>
            {children}
        </SheetTrigger>
        <SheetContent className="w-[1000px] sm:max-w-[1000px] bg-gray-100">
            <div className="flex h-full">
                <div className="w-fit pr-6">
                    <SheetTitle>添加工具</SheetTitle>
                    <SearchInput placeholder="搜索" className="mt-6" onChange={handleSearch} />
                </div>
                <div className="flex-1 bg-[#fff] p-6 h-full overflow-auto scrollbar-hide">
                    <Accordion type="single" collapsible className="w-full">
                        {
                            data.length ? data.map(el => (
                                <AccordionItem key={el.id} value={el.id} className="data-[state=open]:border-2 data-[state=open]:border-primary/20 data-[state=open]:rounded-md">
                                    <AccordionTrigger>
                                        <div className="flex gap-2 text-start">
                                            <TitleIconBg className="w-9 h-9" id={el.id} />
                                            <div>
                                                <p className="text-sm font-medium leading-none">{el.name}</p>
                                                <p className="text-sm text-muted-foreground mt-2">{el.description}</p>
                                            </div>
                                        </div>
                                    </AccordionTrigger>
                                    <AccordionContent className="py-2">
                                        <div className="px-6 mb-4">
                                            <div className="relative hover:bg-gray-100 p-4 rounded-sm  border-t">
                                                <h1 className="text-sm font-medium leading-none">名称</h1>
                                                <p className="text-sm text-muted-foreground mt-2">描述</p>
                                                <p className="text-sm text-muted-foreground mt-2">参数: <span>参数 1</span><span>参数 2</span></p>
                                                {select.some(_ => _.id === el.id) ?
                                                    <Button size="sm" className="absolute right-4 bottom-4 h-6" disabled>已添加</Button>
                                                    : <Button size="sm" className="absolute right-4 bottom-4 h-6" onClick={() => onSelect(el)}>添加</Button>
                                                }
                                            </div>
                                            <div className="relative hover:bg-gray-100 p-4 rounded-sm  border-t">
                                                <h1 className="text-sm font-medium leading-none">名称</h1>
                                                <p className="text-sm text-muted-foreground mt-2">描述</p>
                                                <p className="text-sm text-muted-foreground mt-2">参数: <span>参数 1</span><span>参数 2</span></p>
                                                {select.some(_ => _.id === el.id) ?
                                                    <Button size="sm" className="absolute right-4 bottom-4 h-6" disabled>已添加</Button>
                                                    : <Button size="sm" className="absolute right-4 bottom-4 h-6" onClick={() => onSelect(el)}>添加</Button>
                                                }
                                            </div>
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
