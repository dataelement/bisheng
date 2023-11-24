
import { Trash2 } from "lucide-react"
import { useContext, useState } from "react"
import { useTranslation } from "react-i18next"
import {
    Card,
    CardDescription,
    CardHeader,
    CardTitle
} from "../../../components/ui/card"
import { alertContext } from "../../../contexts/alertContext"
import { updataOnlineState } from "../../../controllers/API"
import { FlowType } from "../../../types/flow"
import { gradients } from "../../../utils"

export default function TempItem({ data, onDelete }: { data: FlowType, onDelete: () => void }) {
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
            <CardTitle className="pl-[40px] box-content w-[180px]">{data.name}</CardTitle>
            <CardDescription className="pl-[50px]">{data.description}</CardDescription>
            {data.user_name && <p className="absolute left-4 bottom-2 pl-[50px] text-xs text-gray-400">{t('skills.createdBy')}： {data.user_name}</p>}
            <div className="absolute right-4 bottom-2 flex gap-2 items-center">
                <button className="" onClick={onDelete}> <Trash2 className="card-component-delete-icon" /> </button>
            </div>
        </CardHeader>
        {/* <CardContent></CardContent>
        <CardFooter></CardFooter> */}
    </Card>
};
