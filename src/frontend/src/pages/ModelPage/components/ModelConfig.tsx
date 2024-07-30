import ShadTooltip from "@/components/ShadTooltipComponent";
import { ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { Input } from "@/components/bs-ui/input";
import { Button } from "@/components/bs-ui/button";
import { Switch } from "@/components/bs-ui/switch";
import { Trash2Icon } from "lucide-react";
import { PlusIcon } from "@radix-ui/react-icons";
import { useState } from "react";

function ModelItem() {
    return <div className="w-full border rounded-sm p-4">
        <div className="flex items-center justify-between">
            <span className="text-2xl">模型1</span>
            <Trash2Icon className="w-[20px] cursor-pointer text-gray-500 h-[20px]"/>
        </div>
        <div className="space-y-2 mt-2">
            <div>
                <span>模型名称</span>
                <Input></Input>
            </div>
            <div>
                <span>模型类型</span>
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
        </div>
    </div>
}

export default function ModelConfig({ id, onBack }) {
    console.log(id) // id为-1说明是添加模型，否则是模型配置
    const { t } = useTranslation()
    const [models, setModels] = useState([
        {id:1, name:'模型1', type:'xxx'}
    ])
    const [select, setSelect] = useState('')
    const [limit, setLimit] = useState(false)

    const handleSelect = (value) => {
        console.log(value)
        setSelect('OpenAI')
    }

    const handleAddModel = () => {

    }

    return <div className="w-full">
        <div className="flex ml-6 items-center gap-x-3">
            <ShadTooltip content={t('back')} side="right">
                <button className="extra-side-bar-buttons w-[36px]" onClick={() => onBack()}>
                    <ArrowLeft strokeWidth={1.5} className="side-bar-button-size" />
                </button>
            </ShadTooltip>
            <span>{id === -1 ? '添加模型' : '模型配置'}</span>
        </div>
        <div className="w-[50%] flex flex-col gap-y-2 m-auto mt-5">
            <div>
                <span>服务提供方</span>
                <Select onValueChange={handleSelect}>
                    <SelectTrigger>
                        <SelectValue placeholder=""/>
                    </SelectTrigger>
                    <SelectContent>
                        <SelectGroup>
                            <SelectItem value="1">OpenAI</SelectItem>
                        </SelectGroup>
                    </SelectContent>
                </Select>
            </div>
            <div>
                <span>服务提供方名称</span>
                <Input value={select}></Input>
            </div>
            <div>
                <span>{select} API Base</span>
                <Input></Input>
            </div>
            <div>
                <span>{select} proxy</span>
                <Input></Input>
            </div>
            <div>
                <span>API Key</span>
                <Input></Input>
            </div>
            <div className="mt-2">
                <div className="flex items-center gap-x-6">
                    <span>单日调用次数上限</span>
                    <Switch defaultChecked={false} onCheckedChange={(val) => setLimit(val)}/>
                    <div className={`flex items-center gap-x-2 ${limit ? 'opacity-100' : 'opacity-0'}`}>
                        <Input type="number" className={`w-[100px]`}></Input>
                        <span>次/天</span>
                    </div>
                </div>
            </div>
            <div className="flex mt-2">
                <div className="mr-5">模型：</div>
                <div className="w-[92%]">
                    {
                        models.map(m => <ModelItem />)
                    }
                    <div onClick={handleAddModel} className="border-[2px] hover:bg-gray-100 h-[40px] cursor-pointer mt-4 flex justify-center rounded-md">
                        <div className="flex justify-center items-center">
                            <PlusIcon className="size-6 text-blue-500"/>
                            <span>添加模型</span>
                        </div>
                    </div>
                </div>
            </div>
            <div className="space-x-6 text-right">
                <Button variant="outline">取消</Button>
                <Button disabled>保存</Button>
            </div>
        </div>
    </div>
}