import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { QuestionMarkCircledIcon } from "@radix-ui/react-icons";
import { Trash2Icon } from "lucide-react";
import { Input } from "@/components/bs-ui/input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Button } from "@/components/bs-ui/button";
import { PlusIcon } from "@radix-ui/react-icons"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";

export default function AssisModel({ onBack }) {
    return <div className="w-[70vw]">
        <div>
            <span className="text-xl">助手推理模型</span>
            <div className="mt-6">
                <div className="grid grid-cols-6 mb-4">
                    <span>模型</span>
                    <div className="flex items-center space-x-2">
                        <span>助手执行模式</span>
                        <TooltipProvider delayDuration={500}>
                            <Tooltip>
                                <TooltipTrigger>
                                    <QuestionMarkCircledIcon />
                                </TooltipTrigger>
                                <TooltipContent>
                                    <span>模型支持OpenAI function call 格式接口协议时，建议选择 function call 模式</span>
                                </TooltipContent>
                            </Tooltip>
                        </TooltipProvider>
                    </div>
                    <div className="flex items-center space-x-2">
                        <span>助手知识库检索最大字符数</span>
                        <TooltipProvider delayDuration={500}>
                            <Tooltip>
                                <TooltipTrigger>
                                    <QuestionMarkCircledIcon />
                                </TooltipTrigger>
                                <TooltipContent>
                                    <span>传给模型的最大字符数，超过会自动截断，可根据模型最大上下文长度灵活调整</span>
                                </TooltipContent>
                            </Tooltip>
                        </TooltipProvider>
                    </div>
                    <div className="flex items-center space-x-2">
                        <span>检索后是否重排</span>
                        <TooltipProvider delayDuration={500}>
                            <Tooltip>
                                <TooltipTrigger>
                                    <QuestionMarkCircledIcon />
                                </TooltipTrigger>
                                <TooltipContent>
                                    <span>是否将检索得到的chunk重新排序</span>
                                </TooltipContent>
                            </Tooltip>
                        </TooltipProvider>
                    </div>
                    <span className="text-center">设为默认模式</span>
                    <div></div>
                </div>
                <div className="grid grid-cols-6">
                    <div className=" pr-2">
                        <Select>
                            <SelectTrigger>
                                <SelectValue placeholder=""/>
                            </SelectTrigger>
                            <SelectContent>
                                <SelectGroup>
                                    {/* <SelectItem></SelectItem> */}
                                </SelectGroup>
                            </SelectContent>
                        </Select>
                    </div>
                    <div className=" pr-2">
                        <Select>
                            <SelectTrigger>
                                <SelectValue placeholder=""/>
                            </SelectTrigger>
                            <SelectContent>
                                <SelectGroup>
                                    {/* <SelectItem></SelectItem> */}
                                </SelectGroup>
                            </SelectContent>
                        </Select>
                    </div>
                    <div className="pr-2">
                        <Input></Input>
                    </div>
                    <div className=" pr-2">
                        <Select>
                            <SelectTrigger>
                                <SelectValue placeholder=""/>
                            </SelectTrigger>
                            <SelectContent>
                                <SelectGroup>
                                    {/* <SelectItem></SelectItem> */}
                                </SelectGroup>
                            </SelectContent>
                        </Select>
                    </div>
                    <div className="m-auto">
                        <RadioGroup>
                            <RadioGroupItem value="1"></RadioGroupItem>
                        </RadioGroup>
                    </div>
                    <div className="m-auto">
                        <Trash2Icon className="text-gray-500 cursor-pointer"/>
                    </div>
                </div>
                <Button variant="outline" size="icon" className="mt-4">
                    <PlusIcon></PlusIcon>
                </Button>
            </div>
        </div>
        <div className="mt-10">
            <span className="text-xl">助手画像自动优化模型</span>
            <Select>
                <SelectTrigger className="w-[250px]">
                    <SelectValue placeholder=""/>
                </SelectTrigger>
                <SelectContent>
                    <SelectGroup>
                        {/* <SelectItem></SelectItem> */}
                    </SelectGroup>
                </SelectContent>
            </Select>
        </div>
        <div className="mt-10 text-center space-x-6">
            <Button variant="outline" onClick={() => onBack()}>取消</Button>
            <Button>保存</Button>
        </div>
    </div>
}