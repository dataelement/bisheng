import { Button } from "@/components/bs-ui/button"
import { SettingIcon } from "@/components/bs-icons"
import { useContext, useState } from "react"
import { userContext } from "@/contexts/userContext"
import { useTranslation } from "react-i18next"
import { PlusCircledIcon } from "@radix-ui/react-icons"
import { MinusCircledIcon } from "@radix-ui/react-icons"
import { QuestionMarkCircledIcon } from "@radix-ui/react-icons"
import { Switch } from "@/components/bs-ui/switch"
import ModelConfig from "./components/ModelConfig"
import SystemModelConfig from "./components/SystemModelConfig"

function CustomTableRow({ data, index, user, onModel }) {
    const { t } = useTranslation()
    const [expand, setExpand] = useState(false)
    const [models, setModels] = useState([
        { id:1, name:'deepseek', type:'LLM', disable:false, online:true },
        { id:2, name:'M3E', type:'Embedding', disable:true, online:true },
        { id:3, name:'OpenAI', type:'LLM', disable:false, online:false },
    ])

    const handleCheck = (bool, id) => {
        setModels(pre => pre.map(m => m.id === id ? {...m, online:bool} : m))
    }

    return <div>
        <div className={`grid grid-cols-2 items-center hover:bg-[#EBF0FF] ${index % 2 === 0 ? 'bg-[#FBFBFB]' : 'bg-[#F4F5F8]'} mt-1 mx-2 h-[52px] rounded-sm`}>
            <div className="ml-3 flex items-center gap-x-3">
                {
                    expand ? <MinusCircledIcon className="cursor-pointer" onClick={() => setExpand(false)}/> : <PlusCircledIcon onClick={() => setExpand(true)} className="cursor-pointer"/>
                }
                {data.name}
            </div>
            <div className="text-right mr-3">
                <Button variant="link" onClick={() => onModel(data.id)}
                    disabled={user.role !== 'admin'} 
                    className={`link px-0 pl-6`}>
                        {t('model.modelConfiguration')}
                </Button>
            </div>
        </div>
        {
            expand && <div className="w-[80%] m-auto border-collapse">
                <table className="w-full border-collapse">
                    <thead>
                        <tr className="grid grid-cols-4 border text-center">
                            <td className="border-x">模型名称</td>
                            <td className="border-x">模型类型</td>
                            <td className="border-x">状态</td>
                            <td className="border-x">上下线操作</td>
                        </tr>
                    </thead>
                    <tbody>
                        {
                            models.map(m => <tr className="grid grid-cols-4 text-center border" key={m.id}>
                                <td className="border-x">{m.name}</td>
                                <td className="border-x">{m.type}</td>
                                <td className="border-x">
                                    <span className={m.disable ? 'text-green-500' : 'text-orange-500'}>
                                        {m.disable ? '可用' : '异常'}
                                    </span>
                                    {!m.disable && <QuestionMarkCircledIcon className="ml-1 inline-block" />}
                                </td>
                                <td className="border-x">
                                    <Switch disabled={user.role !== 'admin'} checked={m.online} onCheckedChange={(bool) => handleCheck(bool, m.id)} />
                                </td>
                            </tr>) 
                        }
                    </tbody>
                </table>
            </div>
        }
    </div>
}

export default function Management() {
    const { t } = useTranslation()
    const init = [
        {id:1, name:'测试数据一'},
        {id:2, name:'测试数据二'},
        {id:3, name:'测试数据三'},
        {id:4, name:'测试数据四'}
    ]
    const [data, setData] = useState(init)
    const { user } = useContext(userContext)
    const [modelId, setModelId] = useState(null)
    const [systemModel, setSystemModel] = useState(false)

    if(modelId) return <ModelConfig id={modelId} onBack={() => setModelId(null)} />

    if(systemModel) return <SystemModelConfig onBack={() => setSystemModel(false)}/>

    return <div className="bg-background-login h-full">
        <div className="flex justify-end">
            { user.role === 'admin' && <Button onClick={() => setSystemModel(true)} variant="outline" className="mr-6">
                <SettingIcon />
                系统模型设置
            </Button> }
            { user.role === 'admin' && <Button onClick={() => setModelId(-1)} className="bg-slate-950 mr-6">添加模型</Button> }
            <Button className="mr-6">刷新</Button>
        </div>
        <div className="h-[85%]">
            <div className="flex justify-between items-center mb-3 mt-5 text-slate-500">
                <span className="ml-5">服务提供方</span>
                <span className="mr-5">操作</span>
            </div>
            <div className="overflow-y-auto pb-20">
                {
                    data.map((d, index) => <CustomTableRow onModel={(id) => setModelId(id)} user={user} data={d} index={index} key={d.id}/>)
                }
            </div>
        </div>
        <div className="text-gray-500 bg-background-login">
            <p className=" text-sm">{t('model.modelCollectionCaption')}.</p>
        </div>
    </div>
}