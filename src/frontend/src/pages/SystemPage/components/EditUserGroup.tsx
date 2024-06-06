import { useContext, useEffect, useRef, useState } from "react"
import { Input, SearchInput } from "../../../components/bs-ui/input";
import MultiSelect from "@/components/bs-ui/select/multi"
import { useTranslation } from "react-i18next"
import { getAllUsersApi } from "@/controllers/API/user";
import FlowRadio from "@/components/bs-ui/radio/flowRadio";
import { QuestionCircleIcon } from "@/components/bs-icons/questionCircle";
import { Button } from "@/components/bs-ui/button";
import FlowControl from "@/components/bs-ui/table/flowCtrl";
import { Tooltip, TooltipProvider, TooltipTrigger, TooltipContent } from "@/components/bs-ui/tooltip";
import { alertContext } from "@/contexts/alertContext";

export default function EditUserGroup({id, name, admins, limit, onBeforeChange, onChange}) {
    const { t } = useTranslation()
    const { errorData, setErrorData } = useContext(alertContext)

    const [form, setForm] = useState({
        name,
        admins:[],
        flowControl:limit
    })
    const [options, setOptions] = useState([])
    const [selected, setSelected] = useState([])
    const [assistants, setAssistants] = useState([]) // 助手流量
    const [skills, setSkills] = useState([]) // 技能流量

    const assisRef = useRef([]) // 数据暂存
    const skillRef = useRef([])
    const assisSearch = (e) => {
        const key = e.target.value
    }
    const skillSearch = (e) => {
        const key = e.target.value
    }

    const getFlowCtrl = (flag) => {
        setForm({...form, flowControl:flag})
    }
    const handleSave = () => {
        if (!form.name.length || form.name.length > 30) {
            return setErrorData({
                title: t('prompt'),
                list: [t('system.roleNameRequired'), t('system.roleNamePrompt')],
            });
        }
        const flag = onBeforeChange(form.name)
        if(flag) {
            setErrorData({
                title: t('prompt'),
                list: [t('system.roleNameExists')]
            })
        }
        onChange()
    }

    useEffect(() => { // 初始化数据
        async function init() {
            let data = (await getAllUsersApi()).data
            const admin = data.filter(d => d.name === 'admin')
            if(!id) {
                setSelected(admin)
            } else {
                setSelected([...admin, ...admins])
            }
            setOptions(data)
        }
        init()
    },[])

    return <div className="max-w-[600px] mx-auto pt-4 h-[calc(100vh-136px)] overflow-y-auto pb-10 scrollbar-hide">
        <div className="font-bold mt-4">
            <p className="text-xl mb-4">{t('system.userGroupName')}</p>
            <Input placeholder={t('system.userGroupName')} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} maxLength={30}></Input>
        </div>
        <div className="font-bold mt-4">
            <p className="text-xl mb-4">{t('system.admins')}</p>
            <div className="">
                <MultiSelect className=" w-full" options={options.map(o => {
                    return {
                        label:o.name,
                        value:o.id
                    }
                })} value={selected.map(s => {
                    return s.id
                })} lockedValues={["01"]}
                onChange={(values) => {
                    setSelected(options.filter(o => {
                        return values.includes(o.id.toString())
                    }))
                }}></MultiSelect>
            </div>
        </div>
        <div className="font-bold mt-4">
            <p className="text-xl mb-4">{t('system.flowControl')}</p>
            <FlowRadio limit={form.flowControl} onChange={getFlowCtrl}></FlowRadio>
        </div>
        <div className="mt-4">
            <div className="flex items-center mb-4 justify-between">
                <div className="flex items-center space-x-2">
                    <p className="text-xl font-bold">{t('system.AssistantFlowCtrl')}</p>
                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger>
                                <QuestionCircleIcon />
                            </TooltipTrigger>
                            <TooltipContent>
                                <p>{t('system.iconHover')}</p>
                            </TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                </div>
                <SearchInput placeholder={t('build.assistantName')} onChange={assisSearch}></SearchInput>
            </div>
            <FlowControl name={t('build.assistantName')}></FlowControl>
        </div>
        <div className="mt-4">
            <div className="flex items-center mb-4 justify-between">
                <div className="flex items-center space-x-2">
                    <p className="text-xl font-bold">{t('system.SkillFlowCtrl')}</p>
                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger>
                                <QuestionCircleIcon />
                            </TooltipTrigger>
                            <TooltipContent>
                                <p>{t('system.iconHover')}</p>
                            </TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                </div>
                <SearchInput placeholder={t('skills.skillName')} onChange={skillSearch}></SearchInput>
            </div>
            <FlowControl name={t('skills.skillName')}></FlowControl>
        </div>
        <div className=" sticky bottom-0 flex justify-center gap-4 mt-16">
            <Button variant="outline" className="px-16" onClick={onChange}>{t('cancel')}</Button>
            <Button className="px-16" onClick={handleSave}>{t('save')}</Button>
        </div>
    </div>
}