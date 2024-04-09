import { useState } from "react";
import { readOnlineFlows } from "../../../controllers/API/flow";
import { FlowType } from "../../../types/flow";
import { useTable } from "../../../util/hook";
import { Button } from "../../bs-ui/button";
import { SearchInput } from "../../bs-ui/input";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "../../bs-ui/sheet";
import CardComponent from "../cardComponent";

export default function SkillSheet({ select, children, onSelect }) {

    const [keyword, setKeyword] = useState('')
    const { data: onlineFlows, loading, search } = useTable<FlowType>({}, (param) =>
        readOnlineFlows(param.page, param.keyword).then(res => {
            return res
        })
    )

    const handleSearch = (e) => {
        const { value } = e.target
        setKeyword(value)
        search(value)
    }

    const toCreateFlow = () => {
        window.open('/build/skills')
    }

    return <Sheet>
        <SheetTrigger asChild>
            {children}
        </SheetTrigger>
        <SheetContent className="sm:min-w-[966px] bg-gray-100">
            <div className="flex h-full" onClick={e => e.stopPropagation()}>
                <div className="w-fit pr-6">
                    <SheetTitle>添加技能</SheetTitle>
                    <SearchInput value={keyword} placeholder="搜索" className="my-6" onChange={handleSearch} />
                    <Button className="w-full" onClick={toCreateFlow} >创建技能</Button>
                </div>
                <div className="flex-1 bg-[#fff] p-6 h-full flex flex-wrap gap-1 overflow-y-auto scrollbar-hide content-start min-w-[696px]">
                    {
                        onlineFlows[0] ? onlineFlows.map((flow, i) => (
                            <CardComponent key={i}
                                id={i + 1}
                                data={flow}
                                title={flow.name}
                                description={flow.description}
                                type="sheet"
                                footer={(
                                    <div className="flex justify-end">
                                        {select.some(_ => _.id === flow.id) ?
                                            <Button size="sm" className="h-6" disabled>已添加</Button>
                                            : <Button size="sm" className="h-6" onClick={() => onSelect(flow)}>添加</Button>
                                        }
                                    </div>
                                )}
                            />
                        )) : <div className="flex flex-col items-center justify-center pt-40 w-full">
                            <p className="text-sm text-muted-foreground mb-3">空空如也</p>
                            <Button className="w-[200px]" onClick={toCreateFlow}>创建技能</Button>
                        </div>
                    }
                </div>
            </div>
        </SheetContent>
    </Sheet>
};

