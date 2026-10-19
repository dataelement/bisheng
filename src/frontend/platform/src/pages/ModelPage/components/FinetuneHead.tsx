// @ts-strict-ignore
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../../components/bs-ui/button";
import { SearchInput } from "../../../components/bs-ui/input";
import {
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectTrigger,
    SelectValue
} from "../../../components/bs-ui/select";
import { Segmented } from "@bisheng/ui";
import { getAllServicesApi } from "../../../controllers/API";
import { useDebounce } from "../../../util/hook";

interface IProps {
    onSearch: (searchkey) => void,
    onFilter: ({ type, rt }) => void,
    rtClick: () => void,
    onCreate: () => void,
}
export default function FinetuneHead({ onSearch, onFilter, rtClick, onCreate }: IProps) {
    const { t } = useTranslation()

    const [type, setType] = useState('all')
    const [rt, setRt] = useState('all')
    const inputRef = useRef(null)

    const handleTypeChange = (val) => {
        setType(val)
        onFilter({ type: val, rt })
    }

    const handleRtChange = (val) => {
        setRt(val)
        onFilter({ type, rt: val })
    }

    // rts
    const [services, setServices] = useState([])
    useEffect(() => {
        getAllServicesApi().then(res => {
            setServices(res.map(el => ({
                id: el.id,
                name: el.server_name
            })))
        })

        onFilter({ type, rt })
    }, [])

    const handleSearch = () => {
        onSearch(inputRef.current.value)
    }

    return <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b ml-2">
        <div className="flex flex-wrap items-center gap-4">
            <Segmented className="shrink-0" value={type} onChange={handleTypeChange} options={[
                { value: 'all', label: t('finetune.all') },
                { value: '4', label: t('finetune.successful') },
                { value: '1', label: t('finetune.inProgress') },
                { value: '2', label: t('finetune.failedAborted') },
            ]} />
            <Select defaultValue={rt} onValueChange={handleRtChange}>
                <SelectTrigger className="w-[180px] shrink-0">
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    <SelectGroup>
                        <SelectItem value="all">{t('finetune.all')}</SelectItem>
                        {
                            services.filter(service => service.id != null && String(service.id) !== "").map(service => <SelectItem key={service.id} value={String(service.id)}>{service.name}</SelectItem>)
                        }
                    </SelectGroup>
                </SelectContent>
            </Select>
            <SearchInput boxClassName="w-56 shrink-0" ref={inputRef} placeholder={t('finetune.modelName')} onChange={useDebounce(handleSearch, 600, false)}></SearchInput>
        </div>
        <div className="flex flex-wrap items-center gap-4 mr-2">
            <Button onClick={onCreate}>{t('finetune.createTrainingTask')}</Button>
            <Button variant="black" onClick={rtClick}>{t('finetune.rtServiceManagement')}</Button>
        </div>
    </div>
};
