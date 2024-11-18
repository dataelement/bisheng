import { TitleIconBg } from "@/components/bs-comp/cardComponent";
import { ToolIcon } from "@/components/bs-icons";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/bs-ui/accordion";
import { Button } from "@/components/bs-ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";
import { getAssistantToolsApi } from "@/controllers/API/assistant";
import { getWorkflowNodeTemplate } from "@/controllers/API/workflow";
import { getToolTree } from "@/util/flowUtils";
import { ListVideo } from "lucide-react";
import { useMemo, useState } from "react";
import { useQuery } from "react-query";
import NodeLogo from "./FlowNode/NodeLogo";

export default function Sidebar({ dropdown = false, onInitStartNode = (node: any) => { }, onClick = (k) => { } }) {
    const { data: tempData, refetch } = useQuery({
        queryKey: "QueryWorkFlowTempKey",
        queryFn: () => getWorkflowNodeTemplate()
    });

    const getNodeDataByTemp = (temp) => {
        return {
            type: temp.type,
            name: temp.name,
            icon: <NodeLogo type={temp.type} />,
            desc: temp.description
        }
    }

    const nodeTemps = useMemo(() => {
        if (!tempData) return []
        return tempData.reduce((list, temp) => {
            const newNode = getNodeDataByTemp(temp)
            temp.type === 'start' ? onInitStartNode(temp) : list.push(newNode)
            return list
        }, [])
    }, [tempData])

    // tool
    const { data: toolTempData } = useQuery({
        queryKey: "QueryToolsKey",
        queryFn: () => getAssistantToolsApi('all')
    });

    const toolTemps = useMemo(() => {
        if (!toolTempData) return []
        return toolTempData.reduce((list, temp) => {
            // 这几个产品说先不用
            if (['时间', '计算器', '代码执行器'].includes(temp.name)) return list
            list.push(getToolTree(temp))
            return list
        }, [])
    }, [toolTempData])

    const [expand, setExpand] = useState(true)

    function onDragStart(
        event: React.DragEvent<any>,
        data: { type: string; node?: any }
    ) {
        // start drag event
        var crt = event.currentTarget.cloneNode(true);
        crt.style.position = "absolute";
        crt.style.width = "238px";
        crt.style.top = "-500px"; // 移出可视区
        crt.style.left = "-500px";
        crt.classList.add("cursor-dragging");
        document.body.appendChild(crt);
        event.dataTransfer.setDragImage(crt, 10, 10); // 影子
        event.dataTransfer.setData("flownodedata", JSON.stringify(data));
    }

    return <div className={`${dropdown ? 'relative' : 'absolute'} max-w-56 z-40 h-full transition-transform ${expand ? 'p-2' : 'py-2 translate-x-[-200px]'}`}>
        <div className="bg-background rounded-2xl shadow-md h-full p-2">
            {/* tab */}
            <Tabs defaultValue="base" className="h-full">
                <div className="flex gap-1">
                    <TabsList className="grid flex-1 grid-cols-2">
                        <TabsTrigger value="base">基础节点</TabsTrigger>
                        <TabsTrigger value="tool">工具节点</TabsTrigger>
                    </TabsList>
                    {!dropdown && <Button size="icon" variant="secondary" className={`${expand ? ' right-[-30px]' : 'right-[-46px]'} absolute bg-[#fff] top-2 rounded-full`} onClick={() => setExpand(!expand)}>
                        <ListVideo className={`size-5 ${expand ? 'rotate-180' : ''}`} />
                    </Button>}
                </div>
                {/* base */}
                <TabsContent value="base">
                    <TooltipProvider delayDuration={100}>
                        {
                            nodeTemps.map((item, index) =>
                                <Tooltip key={item.type}>
                                    <TooltipTrigger className="block w-full">
                                        <div key={item.type}
                                            className={`flex gap-2 items-center p-2 cursor-pointer border border-transparent rounded-md hover:border-gray-200`}
                                            onMouseEnter={(event) => {
                                                // 如果正在拖拽，不移除hover样式
                                                if (!event.currentTarget.classList.contains('border-gray-200')) {
                                                    event.currentTarget.classList.add('bg-muted');
                                                }
                                            }}
                                            onMouseLeave={(event) => {
                                                event.currentTarget.classList.remove('bg-muted');
                                            }}
                                            draggable={!dropdown}
                                            onDragStart={(event) => {
                                                onDragStart(event, { type: item.type, node: tempData.find(tmp => tmp.type === item.type) })
                                            }}
                                            onDragEnd={(event) => {
                                                document.body.removeChild(
                                                    document.getElementsByClassName(
                                                        "cursor-dragging"
                                                    )[0]
                                                );
                                            }}
                                            onClick={() => dropdown && onClick(item.type)}
                                        >
                                            {item.icon}
                                            <span className="text-sm">{item.name}</span>
                                        </div>
                                    </TooltipTrigger>
                                    <TooltipContent side="right">
                                        <div className="max-w-96 text-left break-all whitespace-normal">{item.desc}</div>
                                    </TooltipContent>
                                </Tooltip>
                            )
                        }
                    </TooltipProvider>
                </TabsContent>
                {/* tool */}
                <TabsContent value="tool" className="overflow-y-auto h-[calc(100vh-10rem)]">
                    <Accordion type="multiple" className="w-full">
                        <TooltipProvider delayDuration={100}>
                            {toolTemps.map((temp, index) =>
                                <AccordionItem key={temp.name} value={temp.name + index} className="border-none">
                                    <AccordionTrigger className="py-2 bisheng-label">{temp.name}</AccordionTrigger>
                                    <AccordionContent className="pb-2">
                                        {
                                            temp.children.map(el =>
                                                <Tooltip key={el.name}>
                                                    <TooltipTrigger className="block w-full">
                                                        <div key={el.name}
                                                            className={`flex gap-2 items-center p-2 cursor-pointer border border-transparent rounded-md hover:border-gray-200`}
                                                            onMouseEnter={(event) => {
                                                                if (!event.currentTarget.classList.contains('border-gray-200')) {
                                                                    event.currentTarget.classList.add('bg-muted');
                                                                }
                                                            }}
                                                            onMouseLeave={(event) => {
                                                                event.currentTarget.classList.remove('bg-muted');
                                                            }}
                                                            draggable={!dropdown}
                                                            onDragStart={(event) => {
                                                                onDragStart(event, { type: el.type, node: el })
                                                            }}
                                                            onDragEnd={(event) => {
                                                                document.body.removeChild(
                                                                    document.getElementsByClassName(
                                                                        "cursor-dragging"
                                                                    )[0]
                                                                );
                                                            }}
                                                        // onClick={() => dropdown && onClick(el.type)}
                                                        >
                                                            <NodeLogo type="tool" colorStr={el.name} />
                                                            <span className="text-sm truncate">{el.name}</span>
                                                        </div>
                                                    </TooltipTrigger>
                                                    <TooltipContent side="right">
                                                        <div className="max-w-96 text-left break-all whitespace-normal">{el.description}</div>
                                                    </TooltipContent>
                                                </Tooltip>
                                            )
                                        }
                                    </AccordionContent>
                                </AccordionItem>
                            )}
                        </TooltipProvider>
                    </Accordion>
                    {

                    }
                </TabsContent>
            </Tabs>
            {/* 搜索 */}
            {/* <div className="side-bar-search-div-placement">
            <input type="text" name="search" id="search" placeholder={t('flow.searchComponent')} className="input-search rounded-full"
                onChange={(e) => {
                    handleSearchInput(e.target.value);
                    setSearch(e.target.value);
                }}
            />
            <div className="search-icon">
                <Search size={20} strokeWidth={1.5} className="" />
            </div>
        </div> */}
        </div>
    </div >
};