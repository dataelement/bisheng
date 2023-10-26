
import { CopyPlus, Trash2 } from "lucide-react"
import { useContext, useState } from "react"
import { useTranslation } from "react-i18next"
import { Link } from "react-router-dom"
import { Button } from "../../../components/ui/button"
import {
    Card,
    CardDescription,
    CardHeader,
    CardTitle
} from "../../../components/ui/card"
import { Switch } from "../../../components/ui/switch"
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "../../../components/ui/tooltip"
import { alertContext } from "../../../contexts/alertContext"
import { updataOnlineState } from "../../../controllers/API"
import { FlowType } from "../../../types/flow"
import { gradients } from "../../../utils"

interface IProps {
    data: FlowType,
    isAdmin: boolean,
    edit: boolean,
    onDelete: () => void,
    onCreate: (flow: FlowType) => void
}

export default function CardItem({ data, isAdmin, edit = false, onDelete, onCreate }: IProps) {
    const { setErrorData, setSuccessData } = useContext(alertContext);
    const [open, setOpen] = useState(data.status === 2)
    const { t } = useTranslation()

    const handleChange = (bln) => {
        updataOnlineState(data.id, data, bln).then(res => {
            setOpen(bln)
            data.status = bln ? 2 : 1
        }).catch(e => {
            setErrorData({
                title: t('skills.onlineFailure'),
                list: [e.response.data.detail],
            });
        })
    }

    return <Card className="w-[300px] mr-4 mb-4 overflow-hidden custom-card relative pb-8">
        <CardHeader className="pb-0">
            <div className={"absolute bg-slate-600 rounded-full w-[100px] h-[100px] left-[-50px] -bottom-8 " + gradients[parseInt(data.id, 16) % gradients.length]}></div>
            {edit && <div className="absolute flex items-center space-x-2 right-2 top-2">
                <TooltipProvider>
                    <Tooltip>
                        <TooltipTrigger><Switch checked={open} onCheckedChange={handleChange} /></TooltipTrigger>
                        <TooltipContent><p>{open ? t('offline') : t('online')}</p></TooltipContent>
                    </Tooltip>
                </TooltipProvider>
            </div>}
            <CardTitle className="pl-[40px] box-content w-[180px]">{data.name}</CardTitle>
            <CardDescription className="pl-[50px]">{data.description}</CardDescription>
            {data.user_name && <p className="absolute left-4 bottom-2 pl-[50px] text-xs text-gray-400">{t('skills.createdBy')}： {data.user_name}</p>}
            {edit ? <div className="custom-card-btn absolute right-4 bottom-2 flex gap-2 items-center bg-[#fff] dark:bg-gray-800 pl-4">
                {!open && <Link to={"/skill/" + data.id}><Button type="submit" className="custom-card-btn h-5 text-xs transition-all bg-gray-500 py-0 block" >{t('edit')}</Button></Link>}
                {isAdmin && <button onClick={() => onCreate(data)}><CopyPlus className="card-component-delete-icon"></CopyPlus></button>}
                <button className="" onClick={onDelete}> <Trash2 className="card-component-delete-icon" /> </button>
            </div> :
                <Button type="submit" className="custom-card-btn absolute right-4 bottom-2 h-5 text-xs transition-all bg-gray-500" >{t('add')}</Button>}
        </CardHeader>
    </Card>
};
