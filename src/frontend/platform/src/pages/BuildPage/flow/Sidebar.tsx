// @ts-strict-ignore
import { Button } from '@bisheng/ui';
import { Accordion,AccordionContent,AccordionItem,AccordionTrigger } from "@/components/bs-ui/accordion";

import { Tooltip as SharedTooltip,Tabs } from "@bisheng/ui";

import { getToolsApi } from "@/controllers/API/tools";
import { getWorkflowNodeTemplate } from "@/controllers/API/workflow";
import { getToolTree } from "@/util/flowUtils";
import { cloneDeep } from "lodash-es";
import { ListVideo } from "lucide-react";
import { useMemo,useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "react-query";
import NodeLogo from "./FlowNode/NodeLogo";

const ToolItem = ({ temp, index, dropdown, onDragStart, onClick }) => {
    const { t } = useTranslation('tool');
    const sortData = useMemo(() => {
        const { children, is_preset } = temp;
        if (children) {
            return is_preset === 2 ? children.sort((a, b) => a.id - b.id) : children;
        }
        return [];
    }, [temp.children]);

    return <AccordionItem key={temp.name} value={temp.name + index} className="border-none">
        <AccordionTrigger className="py-2 bisheng-label">
            <span className="break-all text-left">{temp.is_preset === 1 ? t(`categories.${temp.name}.name`) : temp.name}</span>
        </AccordionTrigger>
        <AccordionContent className="pb-2">
            {
                sortData.map(el =>
                    <SharedTooltip key={el.name} side="right" disabled={!(el.description)} content={(el.description) ? <><div className="max-w-96 text-left break-all whitespace-normal">{temp.is_preset === 1 ? t(`tools.${el.tool_key}.desc`) : el.description}</div></> : null}><span tabIndex={0} className="block w-full"><div key={el.name}
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
                                    onDragStart(event, { type: el.type, node: { ...el, is_preset: temp.is_preset === 1 } })
                                }}
                                onDragEnd={(event) => {
                                    document.body.removeChild(
                                        document.getElementsByClassName(
                                            "cursor-dragging"
                                        )[0]
                                    );
                                }}
                                onClick={() => {
                                    if (!dropdown) return
                                    onClick(el.type, el.tool_key)
                                }}
                            >
                                <NodeLogo type="tool" colorStr={el.name} />
                                <span className="text-sm truncate">{temp.is_preset === 1 ? t(`tools.${el.tool_key}.name`) : el.name}</span>
                            </div></span></SharedTooltip>
                )
            }
        </AccordionContent>
    </AccordionItem>
}

export default function Sidebar({ dropdown = false, disabledNodes = [], onInitStartNode = (node: any) => { }, onClick = (k) => { } }) {
    const { t } = useTranslation('flow')
    const { data: tempData, refetch } = useQuery({
        queryKey: "QueryWorkFlowTempKey",
        queryFn: () => getWorkflowNodeTemplate(),
        cacheTime: 0
    });

    const getNodeDataByTemp = (temp) => {
        return {
            type: temp.type,
            name: t(`node.${temp.type}.name`),
            icon: <NodeLogo type={temp.type} />,
            desc: t(`node.${temp.type}.description`)
        }
    }

    // 先刷新mcp服务接口
    // const [loading, setLoading] = useState(true)
    // const onecRef = useRef(false)
    const handleLoadTools = async (val) => {
        // if (val !== 'tool' || onecRef.current) return
        // setLoading(true)
        // onecRef.current = true
        // try {
        //     await refreshAssistantMcpApi()
        // } catch (error) {
        //     console.error(error)
        // }
        // refetch()
        // setLoading(false)
    }

    const nodeTemps = useMemo(() => {
        if (!tempData) return []
        // TODO 追加MCP工具
        return tempData.reduce((list, temp) => {
            if (disabledNodes.includes(temp.type)) return list
            const newNode = getNodeDataByTemp(temp)
            temp.type === 'start' ? onInitStartNode(cloneDeep(temp)) : list.push(newNode)
            return list
        }, [])
    }, [tempData, disabledNodes])


    // tool
    const { data: toolTempData } = useQuery({
        queryKey: "QueryToolsKey",
        queryFn: () => getToolsApi('all'),
        cacheTime: 0
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
    const [activeTab, setActiveTab] = useState('base')

    function onDragStart(
        event: React.DragEvent<any>,
        data: { type: string; node?: any }
    ) {
        // start drag event
        const crt = event.currentTarget.cloneNode(true);
        crt.style.position = "absolute";
        crt.style.width = "238px";
        crt.style.top = "-500px"; // 移出可视区
        crt.style.left = "-500px";
        crt.classList.add("cursor-dragging");
        document.body.appendChild(crt);
        event.dataTransfer.setDragImage(crt, 10, 10); // 影子
        event.dataTransfer.setData("flownodedata", JSON.stringify(data));
    }

    return <div className={`${dropdown ? 'relative' : 'absolute'} max-w-60 z-40 h-full transition-transform ${expand ? 'p-2' : 'py-2 translate-x-[-200px]'}`}>
        <div className="bg-background rounded-2xl shadow-md h-full p-2">
            {/* tab */}
            <div className="h-full">
                <div className="flex gap-1">
                    <Tabs activeKey={activeTab} onChange={value => { setActiveTab(value); handleLoadTools(value) }} items={[
                        { key: 'base', label: t('basicNodes') },
                        { key: 'tool', label: t('toolNodes') },
                    ]} />
                    {!dropdown && <Button size="medium" variant="filled" className={`${expand ? ' right-[-30px]' : 'right-[-46px]'} absolute bg-[#fff] dark:bg-gray-950 top-2 rounded-full size-8`} onClick={() => setExpand(!expand)} color="default" iconOnly>
                        <ListVideo className={`size-4 ${expand ? 'rotate-180' : ''}`} />
                    </Button>}
                </div>
                {/* base */}
                {activeTab === 'base' && <div>
                    <>{
                            nodeTemps.map((item, index) =>
                                <SharedTooltip key={item.type} side="right" content={<><div className="max-w-96 text-left break-all whitespace-normal">{item.desc}</div></>}><span tabIndex={0} className="block w-full"><div key={item.type}
                                            className={`flex gap-2 items-center p-2 cursor-pointer border border-transparent rounded-md hover:border-gray-200 dark:hover:border-gray-800`}
                                            onMouseEnter={(event) => {
                                                // 如果正在拖拽，不移除hover样式
                                                event.stopPropagation()
                                                if (!event.currentTarget.classList.contains('border-gray-200')) {
                                                    event.currentTarget.classList.add('bg-muted');
                                                }
                                            }}
                                            onMouseLeave={(event) => {
                                                event.stopPropagation()
                                                event.currentTarget.classList.remove('bg-muted');
                                            }}
                                            draggable={!dropdown}
                                            onDragStart={(event) => {
                                                event.stopPropagation()
                                                event.dataTransfer.setData("application/my-app-internal", "true"); // 防止触发拖拽上传
                                                onDragStart(event, { type: item.type, node: tempData.find(tmp => tmp.type === item.type) })
                                            }}
                                            onDragEnd={(event) => {
                                                document.body.removeChild(
                                                    document.getElementsByClassName(
                                                        "cursor-dragging"
                                                    )[0]
                                                );
                                            }}
                                            onClick={() => dropdown && onClick({ type: item.type, node: tempData.find(tmp => tmp.type === item.type) })}
                                        >
                                            {item.icon}
                                            <span className="text-sm text-left">{item.name}</span>
                                        </div></span></SharedTooltip>
                            )
                        }</>
                </div>}
                {/* tool */}
                {activeTab === 'tool' && <div className="nowheel overflow-y-auto h-[calc(100vh-10rem)] max-w-44 relative">
                    <Accordion type="multiple" className="w-full">
                        <>{toolTemps.map((temp, index) =>
                                <ToolItem
                                    key={temp.id}
                                    temp={temp}
                                    index={index}
                                    dropdown={dropdown}
                                    onDragStart={onDragStart}
                                    onClick={(type, tool_key) => {
                                        let node = null
                                        toolTemps.some((temp) => {
                                            node = temp.children.find(node => node.tool_key === tool_key)
                                            return node
                                        })
                                        onClick({ type, node })
                                    }}
                                />
                            )}</>
                    </Accordion>
                </div>}
            </div>
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