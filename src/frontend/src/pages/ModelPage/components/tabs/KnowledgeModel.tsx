import { Button } from "@/components/bs-ui/button";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { QuestionMarkCircledIcon } from "@radix-ui/react-icons";
import Cascader from "@/components/bs-ui/select/cascader";
import { useState } from "react";

export default function KnowledgeModel({ onBack }) {
    const [options, setOptions] = useState([])

    return <div className="gap-y-5 flex flex-col mt-16">
        <div>
            <span>知识库默认embedding模型</span>
            <Cascader options={options} onChange={() => {}}></Cascader>
        </div>
        <div>
            <div className="flex items-center space-x-2">
                <span>知识库溯源模型</span>
                <QuestionMarkCircledIcon />
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
                <span>知识库文档总结模型</span>
                <QuestionMarkCircledIcon />
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