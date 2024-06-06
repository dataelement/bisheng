import { Button } from "@/components/bs-ui/button";
import { Label } from "@/components/bs-ui/label";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio";
import MultiSelect from "@/components/bs-ui/select/multi";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";
import { getAllUsersApi, getUserGroupAssistApi, getUserGroupDetail, getUserGroupSkillApi, saveUserGroup } from "@/controllers/API/user";
import { useTable } from "@/util/hook";
import { QuestionMarkCircledIcon } from "@radix-ui/react-icons";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Input, SearchInput } from "../../../components/bs-ui/input";

function FlowRadio({limit, onChange}) {
    const { t } = useTranslation()
    const [number, setNumber] = useState(10)
    const handleInput = (e) => {
        setNumber(parseFloat(e.target.value))
    }

    return <div>
        <RadioGroup className="flex space-x-2 h-[20px]" value={limit ? 'true' : 'false'}
        onValueChange={(value) => onChange(value === 'true')}>
            <div>
                <Label className="flex justify-center">
                    <RadioGroupItem className="mr-2" value="false"/>{t('system.unlimited')}
                </Label>
            </div>
            <div>
                <Label className="flex justify-center">
                    <RadioGroupItem className="mr-2" value="true"/>{t('system.limit')}
                </Label>
            </div>
            {limit && <div>
                <Label>
                    <p className="mt-[-3px]">
                        {t('system.maximum')}<Input type="number" value={number} className="inline h-5 w-[70px]" 
                        onChange={handleInput}/>{t('system.perMinute')}
                    </p>
                </Label>
            </div>}
        </RadioGroup>
    </div>
}

function FlowControl({name, label}) {
    const { t } = useTranslation()
    const { page, pageSize, data, total, setPage, search } = useTable({ pageSize: 10 }, (params) =>
        label === '助手流量控制' ? getUserGroupAssistApi() : getUserGroupSkillApi()
    ) // search函数触发会重新执行回调函数，列表更新需要api参数设计
    const [items, setItems] = useState(data)
    const handleChange = (value, id) => {
        const newItems = items.map((i:any) => {
            return i.id === id ? {...i,flowCtrl:value} : i
        })
        setItems(newItems)
    }
    const handleSearch = (e) => {
        search(e.target.value)
    }
    useEffect(() => {
        data && setItems(data)
    },[data])

    return <>
        <div className="flex items-center mb-4 justify-between">
            <div className="flex items-center space-x-2">
                <p className="text-xl font-bold">{label}</p>
                <TooltipProvider>
                    <Tooltip>
                        <TooltipTrigger>
                            <QuestionMarkCircledIcon />
                        </TooltipTrigger>
                        <TooltipContent>
                            <p>{t('system.iconHover')}</p>
                        </TooltipContent>
                    </Tooltip>
                </TooltipProvider>
            </div>
            <SearchInput placeholder={t('build.assistantName')} onChange={handleSearch}/>
        </div>
        <div className="rounded-[5px]">
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead>{name}</TableHead>
                        <TableHead>{t('system.createdBy')}</TableHead>
                        <TableHead className="flex justify-evenly items-center">{t('system.flowCtrlStrategy')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {items.map((i:any) => (<TableRow key={i.id}>
                        <TableCell>{i.name}</TableCell>
                        <TableCell>{i.createdBy}</TableCell>
                        <TableCell className="flex justify-evenly items-center pt-[15px]">
                            <FlowRadio limit={i.flowCtrl} onChange={(val) => handleChange(val,i.id)}></FlowRadio>
                        </TableCell>
                    </TableRow>))}
                </TableBody>
            </Table>
            <AutoPagination className="m-0 mt-4 w-auto justify-end" 
            page={page} pageSize={pageSize} total={total}
            onChange={setPage}
            />
        </div>
    </>
}

export default function EditUserGroup({id, name, onBeforeChange, onChange}) {
    const { t } = useTranslation()
    const { toast } = useToast() // 类似于alert

    const [form, setForm] = useState({
        groupName: name,
        adminUser:'',
        groupLimit:null,
        adminUserId: "",
        assistantList: "",
        skillList: ""
    })
    const [options, setOptions] = useState([])
    const [selected, setSelected] = useState([])
    const [assistants, setAssistants] = useState([]) // 助手流量
    const [skills, setSkills] = useState([]) // 技能流量

    const handleSave = () => {
        if (!form.groupName.length || form.groupName.length > 30) {
            setForm({...form, groupName:name})
            return toast({
                title: t('prompt'),
                description: [t('system.roleNameRequired'),t('system.groupNamePrompt')],
                variant: 'error'
            });
        }
        const flag = onBeforeChange(form.groupName)
        if(flag) {
            setForm({...form, groupName:''})
            return toast({title: t('prompt'), description: t('system.groupNameExists'), variant: 'error'});
        }
        saveUserGroup(form) // 保存
        onChange()
    }
    const arrayMap = (arrId, arrName) => {
        return arrId.map((i,index) => ({id:i, name:arrName[index]}))
    }

    useEffect(() => { // 初始化数据
        async function init() {
            const data = (await getAllUsersApi()).data
            const admin = data.filter(d => d.name === 'admin')
            const assistData = (await getUserGroupAssistApi()).data
            const skillData = (await getUserGroupSkillApi()).data
            if(!id) {
                setSelected(admin)
            } else {
                const userGroup = (await getUserGroupDetail(id)).data
                setForm(userGroup)
                setSelected([...admin, ...arrayMap(userGroup.adminUserId.split(','), userGroup.adminUser.split(','))])
            }
            setOptions(data)
            setAssistants(assistData)
            setSkills(skillData)
        }
        init()
    },[])

    return <div className="max-w-[600px] mx-auto pt-4 h-[calc(100vh-136px)] overflow-y-auto pb-10 scrollbar-hide">
        <div className="font-bold mt-4">
            <p className="text-xl mb-4">{t('system.userGroupName')}</p>
            <Input placeholder={t('system.userGroupName')} value={form.groupName} onChange={(e) => setForm({ ...form, groupName: e.target.value })} maxLength={30}></Input>
        </div>
        <div className="font-bold mt-12">
            <p className="text-xl mb-4">{t('system.admins')}</p>
            <div className="">
                <MultiSelect className=" w-full" options={options.map(o => {
                    return {
                        label:o.name,
                        value:o.id
                    }
                })} value={selected.map(s => s.id.toString())} lockedValues={['1']}
                onChange={(values) => {
                    setSelected(options.filter(o => {
                        return values.includes(o.id.toString())
                    }))
                }}></MultiSelect>
            </div>
        </div>
        <div className="font-bold mt-12">
            <p className="text-xl mb-4">{t('system.flowControl')}</p>
            <FlowRadio limit={form.groupLimit} onChange={(f) => setForm({...form, groupLimit:f})}></FlowRadio>
        </div>
        <div className="mt-12">
            <FlowControl name={t('build.assistantName')} label={t('system.AssistantFlowCtrl')}></FlowControl>
        </div>
        <div className="mt-12 mb-20">
            <FlowControl name={t('skills.skillName')} label={t('system.SkillFlowCtrl')}></FlowControl>
        </div>
        <div className="flex justify-center items-center absolute bottom-0 w-[600px] h-[8vh] gap-4 mt-[100px] bg-[white]">
            <Button variant="outline" className="px-16" onClick={onChange}>{t('cancel')}</Button>
            <Button className="px-16" onClick={handleSave}>{t('save')}</Button>
        </div>
    </div>
}