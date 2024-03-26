import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/bs-ui/accordion";
import { Button, ButtonNumber } from "@/components/bs-ui/button";
import { Input, InputList, Textarea } from "@/components/bs-ui/input";
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectScrollUpButton, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { Slider } from "@/components/bs-ui/slider";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";
import { QuestionMarkCircledIcon } from "@radix-ui/react-icons";
import { PlusIcon } from "lucide-react";
import React from "react";

export default function Setting(params) {

    return <div className="w-[50%]">
        <h1 className="text-sm text-muted-foreground border leading-8 indent-4">基础配置</h1>
        <Accordion type="multiple" className="w-full">
            <AccordionItem value="item-1">
                <AccordionTrigger>AI模型配置</AccordionTrigger>
                <AccordionContent className="py-2">
                    <div className="px-6 mb-4">
                        <label htmlFor="model" className="bisheng-label">模型</label>
                        <Select name="model" required>
                            <SelectTrigger className="mt-2">
                                <SelectValue placeholder="选择一个模型" ></SelectValue>
                            </SelectTrigger>
                            <SelectContent>
                                <Input></Input>
                                <SelectGroup>
                                    <SelectLabel>123</SelectLabel>
                                    <SelectItem value="apple">Apple</SelectItem>
                                    <SelectItem value="banana">Banana</SelectItem>
                                    <SelectItem value="blueberry">Blueberry</SelectItem>
                                    <SelectItem value="grapes">Grapes</SelectItem>
                                    <SelectItem value="pineapple">Pineapple</SelectItem>
                                </SelectGroup>
                                <div><Button variant="link">refresh</Button></div>
                            </SelectContent>
                        </Select>
                    </div>
                    <div className="px-6 mb-4">
                        <label htmlFor="slider" className="bisheng-label">温度</label>
                        <div className="flex gap-4 mt-2">
                            <Slider
                                name="slider"
                                defaultValue={[0.5]}
                                max={10}
                                step={0.1}
                            // {...props}
                            />
                            <ButtonNumber
                                defaultValue={0.5}
                                max={10}
                                min={0}
                                step={0.2}
                                onChange={(num) => console.log(num)}
                            />
                        </div>
                    </div>
                </AccordionContent>
            </AccordionItem>
            <AccordionItem value="item-2">
                <AccordionTrigger>开场引导</AccordionTrigger>
                <AccordionContent className="py-2">
                    <div className="px-6 mb-4" >
                        <label htmlFor="open" className="bisheng-label">开场白</label>
                        <Textarea name="open" className="mt-2 min-h-[34px]" style={{ height: 34 }} placeholder="助手将在每次对话开始时发送此信息，支持markdown格式"></Textarea>
                        <p className="bisheng-tip mt-1">提示词最多为1000个字符</p>
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
                        <InputList defaultValue={['', '']} onChange={(list) => console.log('list :>> ', list)} placeholder="请输入引导问题"></InputList>
                    </div>
                </AccordionContent>
            </AccordionItem>
        </Accordion>
        <h1 className="text-sm text-muted-foreground border leading-8 indent-4">知识</h1>
        <Accordion type="multiple" className="w-full">
            <AccordionItem value="item-1">
                <AccordionTrigger>知识库</AccordionTrigger>
                <AccordionContent>
                    Yes. It adheres to the WAI-ARIA design pattern.
                </AccordionContent>
            </AccordionItem>
        </Accordion>
        <h1 className="text-sm text-muted-foreground border leading-8 indent-4">能力</h1>
        <Accordion type="multiple" className="w-full">
            <AccordionItem value="item-1">
                <AccordionTrigger>
                    <div className="flex flex-1 justify-between items-center">
                        <span>工具</span>
                        <PlusIcon size={16} className="text-primary hover:text-primary/80 mr-2"></PlusIcon>
                    </div>
                </AccordionTrigger>
                <AccordionContent>
                    Yes. It adheres to the WAI-ARIA design pattern.
                </AccordionContent>
            </AccordionItem>
            <AccordionItem value="item-2">
                <AccordionTrigger>
                    <div className="flex flex-1 justify-between items-center">
                        <span>技能</span>
                        <PlusIcon size={16} className="text-primary hover:text-primary/80 mr-2"></PlusIcon>
                    </div>
                </AccordionTrigger>
                <AccordionContent>
                    Yes. It comes with default styles that matches the other
                    components&apos; aesthetic.
                </AccordionContent>
            </AccordionItem>
        </Accordion>
    </div>
};
