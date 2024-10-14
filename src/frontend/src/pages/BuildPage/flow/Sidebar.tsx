import { Button } from "@/components/bs-ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";
import { Code, Keyboard, ListVideo, SprayCan } from "lucide-react";
import { useState } from "react";

export default function Sidebar({ dropdown = false, onClick = (k) => { } }) {

    const nodeTemps = [
        {
            type: 'input',
            name: '输入',
            icon: <Keyboard className="size-5 text-green-500" />,
            desc: '输入节点，用于输入文本'
        },
        {
            type: 'output',
            name: '输出',
            icon: <SprayCan className="size-5" />,
            desc: '输出节点，用于输出文本'
        },
        {
            type: 'knowledge',
            name: '知识库检索增强生成',
            icon: <SprayCan className="size-5" />,
            desc: '知识库检索增强生成节点，用于知识库检索增强生成'
        },
        {
            type: 'code',
            name: '代码',
            icon: <Code className="size-5 text-primary" />,
            desc: '代码节点，用于代码生成'
        },
        {
            type: 'end',
            name: '结束',
            icon: <SprayCan className="size-5" />,
            desc: '结束节点，用于结束流程'
        },
    ]

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

    return <div className={`${dropdown ? 'relative' : 'absolute border-r'} max-w-56 z-50 bg-background h-full transition-transform ${expand ? 'p-2' : 'py-2 translate-x-[-200px]'}`}>
        {/* tab */}
        <Tabs defaultValue="account" className="">
            <div className="flex gap-2">
                <TabsList className="grid flex-1 grid-cols-2">
                    <TabsTrigger value="account">基础节点</TabsTrigger>
                    <TabsTrigger value="password">工具节点</TabsTrigger>
                </TabsList>
                {!dropdown && <Button size="icon" variant="ghost" className={expand ? '' : 'absolute right-[-66px] top-2'} onClick={() => setExpand(!expand)}>
                    <ListVideo className={`size-5 ${expand ? 'rotate-180' : ''}`} />
                </Button>}
            </div>
            <TabsContent value="account">
                <TooltipProvider delayDuration={100}>
                    {
                        nodeTemps.map((item, index) =>
                            <Tooltip key={item.type}>
                                <TooltipTrigger className="block w-full">
                                    <div key={item.type}
                                        className="flex gap-2 items-center p-2 cursor-pointer border border-transparent rounded-md hover:border-gray-200"
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
                                            onDragStart(event, { type: 'hahaha' })
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
            <TabsContent value="password">

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
};
