import { Button } from "@/components/bs-ui/button";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { QuestionMarkCircledIcon } from "@radix-ui/react-icons";
import Cascader from "@/components/bs-ui/select/cascader";
import { useState } from "react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";

export default function KnowledgeModel({ onBack }) {
    const [options, setOptions] = useState([
        {value:'01', label:'LLM'}
    ])

    return <div className="gap-y-5 flex flex-col mt-16">
        <div>
            <span>知识库默认embedding模型</span>
            <Cascader options={options} onChange={() => {}}></Cascader>
        </div>
        <div>
            <div className="flex items-center space-x-2">
                <span>知识库溯源模型</span>
                <TooltipProvider delayDuration={500}>
                    <Tooltip>
                        <TooltipTrigger>
                            <QuestionMarkCircledIcon />
                        </TooltipTrigger>
                        <TooltipContent>
                            <span>用于知识库问答溯源，使用 LLM 自动从答案中提取关键词，来帮助用户快速定位到答案的可能来源段落，如果这里没有配置，则会使用 jieba 分词来输出答案中的关键词。</span>
                        </TooltipContent>
                    </Tooltip>
                </TooltipProvider>
            </div>
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
        <div>
            <div className="flex items-center space-x-2">
                <span>文档知识库总结模型</span>
                <TooltipProvider delayDuration={500}>
                    <Tooltip>
                        <TooltipTrigger>
                            <QuestionMarkCircledIcon />
                        </TooltipTrigger>
                        <TooltipContent>
                            <span>将文档内容总结为一个标题，然后将标题和chunk合并存储到向量库内, 不配置则不总结文档。</span>
                        </TooltipContent>
                    </Tooltip>
                </TooltipProvider>
            </div>
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
        <div>
        <div className="flex items-center space-x-2">
                <span>QA知识库相似问模型</span>
                <TooltipProvider delayDuration={500}>
                    <Tooltip>
                        <TooltipTrigger>
                            <QuestionMarkCircledIcon />
                        </TooltipTrigger>
                        <TooltipContent>
                            <span>用于生成 QA 知识库中的相似问题。</span>
                        </TooltipContent>
                    </Tooltip>
                </TooltipProvider>
            </div>
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
        <div className="mt-10 text-center space-x-6">
            <Button variant="outline" onClick={() => onBack()}>取消</Button>
            <Button>保存</Button>
        </div>
    </div>
}