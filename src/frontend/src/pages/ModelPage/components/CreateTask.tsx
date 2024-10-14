import { HelpCircle } from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
import { Button } from "../../../components/bs-ui/button";
import {
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectTrigger,
    SelectValue
} from "../../../components/bs-ui/select";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../../../components/bs-ui/tooltip";

import { useTranslation } from "react-i18next";
import { Input } from "../../../components/bs-ui/input";
import { Label } from "../../../components/bs-ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../../components/bs-ui/table";
import { RadioGroup, RadioGroupItem } from "../../../components/bs-ui/radio-group";
import { alertContext } from "../../../contexts/alertContext";
import { getFTServicesApi, getServicesApi } from "../../../controllers/API";
import { createTaskApi } from "../../../controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import Combobox from "./Combobox";
import CreateTaskList from "./CreateTaskList";

export default function CreateTask({ rtClick, gpuClick, onCancel, onCreate }) {
    const { t } = useTranslation('model')
    const defaultTable = [
        { name: 'gpus', value: '', desc: t('finetune.gpuDesc') },
        { name: 'val_ratio', value: '0.1', desc: t('finetune.valRatioDesc') },
        { name: 'per_device_train_batch_size', value: '1', desc: t('finetune.batchSizeDesc') },
        { name: 'learning_rate', value: '0.00005', desc: t('finetune.learningRateDesc') },
        { name: 'num_train_epochs', value: '3', desc: t('finetune.numEpochsDesc') },
        { name: 'max_seq_len', value: '8192', desc: t('finetune.maxSeqLenDesc') },
        { name: 'cpu_load', value: 'false', desc: t('finetune.cpuLoadDesc') },
    ]

    const [table] = useState(defaultTable)
    const { setErrorData } = useContext(alertContext);

    // 表单数据
    const resultRef = useRef({
        method: 'full',
        server: '',
        base_model: '',
        model_name: '',
        extra_params:
            defaultTable.reduce((res, el) => {
                res[el.name] = el.value
                return res
            }, {})
    })

    const { services, models, selectService } = useOptions()
    const handleRtChange = async (val) => {
        resultRef.current['server'] = val
        selectService(val)
    }


    const [loading, setLoading] = useState(false)
    const handleCreate = async () => {
        // 数据校验
        const errors = []
        if (!resultRef.current.server) errors.push(t('finetune.selectRTService'))
        if (!resultRef.current.base_model) errors.push(t('finetune.selectBaseModel'))
        if (!/^(?=.*[a-zA-Z])(?=.*\d)?[a-zA-Z\d_-]+$/.test(resultRef.current.model_name)) errors.push(t('finetune.enterModelName'))
        if (errors.length) return setErrorData({ title: '', list: errors });
        // 合并数据
        console.log('object :>> ', resultRef.current);
        setLoading(true)
        // api
        const res = await captureAndAlertRequestErrorHoc(createTaskApi(resultRef.current))
        setLoading(false)
        if (!res) return

        onCreate(res.id)
    }

    return <div className="pt-2 h-[calc(100vh-162px)] px-2 overflow-y-auto">
        <div className="border-b pb-2 flex justify-between items-center">
            <h1 className="">{t('finetune.createTrainingTask')}</h1>
            {/* <Button variant="black" onClick={rtClick}>FT服务管理</Button> */}
            <Button variant="black" onClick={rtClick}>{t('finetune.rtServiceManagement')}</Button>
        </div>
        {/* base */}
        <div className="border-b pb-4">
            <div className="flex gap-4 flex-col mt-4">
                <small className="text-sm font-medium leading-none text-gray-500 flex gap-2 items-center">
                    <span>{t('finetune.rtService')}</span>
                    {/* <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger><HelpCircle size={18} /></TooltipTrigger>
                            <TooltipContent>
                                <p>{t('finetune.rtServiceTooltip')}</p>
                            </TooltipContent>
                        </Tooltip>
                    </TooltipProvider> */}
                </small>
                <div className="flex gap-4 items-center">
                    <Select onValueChange={handleRtChange}>
                        <SelectTrigger className="w-[280px]">
                            <SelectValue placeholder="" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectGroup>
                                {
                                    services.map(service => <SelectItem key={service.id} value={service.id}>{service.name}</SelectItem>)
                                }
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                    <Button size="sm" onClick={gpuClick}>{t('finetune.gpuResourceUsage')}</Button>
                </div>
            </div>
            {/* datas */}
            <div className="flex gap-4 flex-col mt-4">
                <small className="text-sm font-medium leading-none text-gray-500">{t('finetune.baseModel')}</small>
                <Combobox
                    options={models}
                    labelKey="model"
                    valueKey="id"
                    onChange={(val) => resultRef.current['base_model'] = val}
                ></Combobox>
            </div>
            <div className="flex gap-4 flex-col mt-4">
                <small className="text-sm font-medium leading-none text-gray-500">{t('finetune.finetuneModelName')}</small>
                <Input maxLength={50} className="max-w-[400px]" onChange={(e) => resultRef.current['model_name'] = e.target.value}></Input>
            </div>
        </div>
        {/* datas */}
        <div className="border-b pb-4">
            <div className="flex gap-4 flex-col mt-4">
                <small className="text-sm font-medium leading-none text-gray-500">{t('finetune.dataset')}</small>
                <CreateTaskList onChange={(key, data) => resultRef.current[key] = data}></CreateTaskList>
            </div>
        </div>
        {/* table */}
        <div className="border-b pb-4">
            <div className="flex gap-4 flex-col mt-4">
                <small className="text-sm font-medium leading-none text-gray-500">{t('finetune.trainingMethod')}</small>
                <div className="mt-1">
                    <RadioGroup defaultValue="full" className="flex gap-6" onValueChange={(val) => resultRef.current['method'] = val}>
                        <div className="flex items-center space-x-2">
                            <RadioGroupItem value="full" id="r1" />
                            <Label htmlFor="r1">{t('finetune.fullFineTune')}</Label>
                        </div>
                        <div className="flex items-center space-x-2">
                            <RadioGroupItem value="freeze" id="r2" />
                            <Label htmlFor="r2">{t('finetune.freeze')}</Label>
                        </div>
                        <div className="flex items-center space-x-2">
                            <RadioGroupItem value="lora" id="r3" />
                            <Label htmlFor="r3">{t('finetune.lora')}</Label>
                        </div>
                    </RadioGroup>
                </div>
            </div>

            <div className="flex gap-4 flex-col mt-4">
                <small className="text-sm font-medium leading-none text-gray-500 flex gap-2 items-center">
                    <span>{t('finetune.parameterConfiguration')}</span>
                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger><HelpCircle size={16} /></TooltipTrigger>
                            <TooltipContent>
                                <p>{t('finetune.parameterConfigurationTooltip')}</p>
                            </TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                </small>
                <div>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className="w-[100px]">{t('finetune.parameter')}</TableHead>
                                <TableHead>{t('finetune.quantity')}</TableHead>
                                <TableHead>{t('finetune.description')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {
                                table.map((item, index) =>
                                    <TableRow key={index}>
                                        <TableCell className="font-medium">{item.name}</TableCell>
                                        <TableCell>
                                            <Input className="text-sm w-[180px]" defaultValue={item.value} onChange={(e) => resultRef.current['extra_params'][item.name] = e.target.value}></Input>
                                        </TableCell>
                                        <TableCell>{item.desc}</TableCell>
                                    </TableRow>
                                )
                            }
                        </TableBody>
                    </Table>
                </div>
            </div>
        </div>
        <div className="mt-6 flex gap-6">
            <Button disabled={loading} className="h-10 px-12" onClick={handleCreate}>{t('bs:create')}</Button>
            <Button disabled={loading} className="h-10 px-12" variant="outline" onClick={onCancel}>{t('bs:cancel')}</Button>
        </div>
    </div>
};

const useOptions = () => {
    // rts
    const [services, setServices] = useState([])
    const [models, setModels] = useState([])

    useEffect(() => {
        getServicesApi().then(res => {
            setServices(res.map(el => ({
                id: el.id,
                name: el.server,
                url: el.endpoint
            })))
        })
    }, [])

    const selectService = async (val) => {
        const servceId = services.find(item => item.id === val)?.id
        const res = await getFTServicesApi(servceId)
        // setModels(res)
        setModels(res.filter(item => item.sft_support))
    }

    return { services, models, selectService }
}