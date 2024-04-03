import SkillSheet from "@/components/bs-comp/sheets/SkillSheet";
import ToolsSheet from "@/components/bs-comp/sheets/ToolsSheet";
import { TitleIconBg } from "@/components/bs-comp/cardComponent";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/bs-ui/accordion";
import { Button } from "@/components/bs-ui/button";
import { InputList, Textarea } from "@/components/bs-ui/input";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";
import { useAssistantStore } from "@/store/assistantStore";
import { MinusCircledIcon, PlusCircledIcon, PlusIcon, QuestionMarkCircledIcon, ReloadIcon } from "@radix-ui/react-icons";
import { Link } from "react-router-dom";
import KnowledgeBaseMulti from "./KnowledgeBaseMulti";
import ModelSelect from "./ModelSelect";
import Temperature from "./Temperature";

export default function Setting() {

    const { assistantState, dispatchAssistant } = useAssistantStore()
    console.log('assistantState :>> ', assistantState);

    return <div className="w-[50%] h-full overflow-y-auto scrollbar-hide">
        <h1 className="text-sm text-muted-foreground border leading-8 indent-4 bg-gray-50">基础配置</h1>
        <Accordion type="multiple" className="w-full">
            {/* 基础配置 */}
            <AccordionItem value="item-1">
                <AccordionTrigger><span>AI模型配置</span></AccordionTrigger>
                <AccordionContent className="py-2">
                    <div className="px-6 mb-4">
                        <label htmlFor="model" className="bisheng-label">模型</label>
                        <ModelSelect
                            value={assistantState.model_name}
                            onChange={(val) => dispatchAssistant('setting', { model_name: val })}
                        />
                    </div>
                    <div className="px-6 mb-4">
                        <label htmlFor="slider" className="bisheng-label">温度</label>
                        <Temperature
                            value={assistantState.temperature}
                            onChange={(val) => dispatchAssistant('setting', { temperature: val })}
                        ></Temperature>
                    </div>
                </AccordionContent>
            </AccordionItem>
            {/* 开场引导 */}
            <AccordionItem value="item-2">
                <AccordionTrigger><span>开场引导</span></AccordionTrigger>
                <AccordionContent className="py-2">
                    <div className="px-6 mb-4" >
                        <label htmlFor="open" className="bisheng-label">开场白</label>
                        <Textarea name="open"
                            className="mt-2 min-h-[34px]"
                            style={{ height: 56 }}
                            placeholder="助手将在每次对话开始时发送此信息，支持markdown格式"
                            value={assistantState.guide_word}
                            onChange={(e) => dispatchAssistant('setting', { guide_word: e.target.value })}
                        ></Textarea>
                        {assistantState.guide_word.length > 1000 && <p className="bisheng-tip mt-1">提示词最多为1000个字符</p>}
                    </div>
                    <div className="px-6 mb-4" >
                        <label htmlFor="open" className="bisheng-label flex gap-1">
                            引导词
                            <TooltipProvider delayDuration={200}>
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <QuestionMarkCircledIcon />
                                    </TooltipTrigger>
                                    <TooltipContent>
                                        <p>为用户提供推荐问题，引导用户提问，超过3个时将随机选取3个</p>
                                    </TooltipContent>
                                </Tooltip>
                            </TooltipProvider>
                        </label>
                        <InputList
                            value={assistantState.guide_question}
                            onChange={(list) => {
                                dispatchAssistant('setting', { guide_question: list })
                            }
                            }
                            placeholder="请输入引导问题"
                        ></InputList>
                    </div>
                </AccordionContent>
            </AccordionItem>
        </Accordion>
        <h1 className="text-sm text-muted-foreground border-b leading-8 indent-4 bg-gray-50">知识</h1>
        <Accordion type="multiple" className="w-full">
            {/* 知识库 */}
            <AccordionItem value="item-1">
                <AccordionTrigger>
                    <div className="flex flex-1 justify-between items-center">
                        <span>知识库</span>
                        {/* <Popover>
                            <PopoverTrigger asChild className="group">
                                <Button variant="link" size="sm"><TriangleRightIcon className="group-data-[state=open]:rotate-90" /> 自动调用 </Button>
                            </PopoverTrigger>
                            <PopoverContent className="w-[560px]">
                                <div className="flex justify-between">
                                    <label htmlFor="model" className="bisheng-label">调用方式</label>
                                    <div>
                                        <RadioCard checked={false} title={'自动调用'} description="每轮对话都会对添加的知识库进行检索召回。" calssName="mb-4"></RadioCard>
                                        <RadioCard checked title={'按需调用'} description='在助手画像（提示词）中提示调用RecallKnowledge（可复制）方法，在有需要时才对知识库进行检索。' calssName="mt-4"></RadioCard>
                                    </div>
                                </div>
                            </PopoverContent>
                        </Popover> */}
                    </div>
                </AccordionTrigger>
                <AccordionContent className="py-2">
                    <div className="px-6 mb-4">
                        <div className="flex gap-4">
                            <KnowledgeBaseMulti
                                value={assistantState.knowledge_list}
                                onChange={(vals) => dispatchAssistant('setting', { knowledge_list: vals })}>
                                {
                                    (reload) => <div className="flex justify-between">
                                        <Link to={'/filelib'} target="_blank">
                                            <Button variant="link"><PlusCircledIcon className="mr-1" /> 新建知识库</Button>
                                        </Link>
                                        <Button variant="link" onClick={reload}><ReloadIcon className="mr-1" /> 刷新</Button>
                                    </div>
                                }
                            </KnowledgeBaseMulti>
                        </div>
                    </div>
                </AccordionContent>
            </AccordionItem>
        </Accordion>
        <h1 className="text-sm text-muted-foreground border-b leading-8 indent-4 bg-gray-50">能力</h1>
        <Accordion type="multiple" className="w-full">
            {/* 工具 */}
            <AccordionItem value="item-1">
                <AccordionTrigger>
                    <div className="flex flex-1 justify-between items-center">
                        <span>工具</span>
                        <ToolsSheet
                            select={assistantState.tool_list}
                            onSelect={(tool) => dispatchAssistant('setting', { tool_list: [...assistantState.tool_list, tool] })}>
                            <PlusIcon className="text-primary hover:text-primary/80 mr-2" onClick={e => e.stopPropagation()}></PlusIcon>
                        </ToolsSheet>
                    </div>
                </AccordionTrigger>
                <AccordionContent>
                    <div className="px-4">
                        {
                            assistantState.tool_list.map(tool => (
                                <div key={tool.id} className="group flex justify-between items-center mt-2 cursor-pointer">
                                    <div className="flex gap-2 items-center">
                                        <TitleIconBg id={tool.id} className="w-7 h-7"></TitleIconBg>
                                        <p className="text-sm">{tool.name}</p>
                                    </div>
                                    <MinusCircledIcon
                                        className="group-hover:block hidden text-primary"
                                        onClick={() => dispatchAssistant('setting', {
                                            tool_list: assistantState.tool_list.filter(t => t.id !== tool.id)
                                        })}
                                    />
                                </div>
                            ))
                        }
                    </div>
                </AccordionContent>
            </AccordionItem>
            {/* 技能 */}
            <AccordionItem value="item-2">
                <AccordionTrigger>
                    <div className="flex flex-1 justify-between items-center">
                        <span className="flex items-center gap-1">
                            <span>技能</span>
                            <TooltipProvider delayDuration={200}>
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <QuestionMarkCircledIcon />
                                    </TooltipTrigger>
                                    <TooltipContent>
                                        <p>通过可视化界面实现复杂和稳定的业务流程编排，例如项目计划和报告分析</p>
                                    </TooltipContent>
                                </Tooltip>
                            </TooltipProvider>
                        </span>
                        <SkillSheet
                            select={assistantState.flow_list}
                            onSelect={(flow) => dispatchAssistant('setting', { flow_list: [...assistantState.flow_list, flow] })}>
                            <PlusIcon className="text-primary hover:text-primary/80 mr-2" onClick={e => e.stopPropagation()}></PlusIcon>
                        </SkillSheet>
                    </div>
                </AccordionTrigger>
                <AccordionContent>
                    <div className="px-4">
                        {
                            assistantState.flow_list.map(flow => (
                                <div key={flow.id} className="group flex justify-between items-center mt-2 cursor-pointer">
                                    <div className="flex gap-2 items-center">
                                        <TitleIconBg id={flow.id} className="w-7 h-7"></TitleIconBg>
                                        <p className="text-sm">{flow.name}</p>
                                    </div>
                                    <MinusCircledIcon
                                        className="group-hover:block hidden text-primary"
                                        onClick={() => dispatchAssistant('setting', {
                                            flow_list: assistantState.flow_list.filter(t => t.id !== flow.id)
                                        })}
                                    />
                                </div>
                            ))
                        }
                    </div>
                </AccordionContent>
            </AccordionItem>
        </Accordion>
    </div >
};
