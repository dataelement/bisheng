// @ts-strict-ignore
import { Button, SearchInput, Select } from '@bisheng/ui';
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";


import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
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
    const selectLabels = useSelectLabels()

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
            <Select
                {...selectLabels}
                className="w-[180px] shrink-0"
                aria-label={t('finetune.rtService')}
                options={[
                    { value: 'all', label: t('finetune.all') },
                    ...services
                        .filter(service => service.id != null && String(service.id) !== "")
                        .map(service => ({ value: String(service.id), label: String(service.name ?? '') })),
                ]}
                value={rt}
                onChange={(val) => handleRtChange(val == null ? 'all' : String(val))}
            />
            <SearchInput ref={inputRef} placeholder={t('finetune.modelName')} onChange={useDebounce(handleSearch, 600, false)} className={"w-56 shrink-0"}></SearchInput>
        </div>
        <div className="flex flex-wrap items-center gap-4 mr-2">
            <Button onClick={onCreate}>{t('finetune.createTrainingTask')}</Button>
            <Button onClick={rtClick} variant="solid" color="default">{t('finetune.rtServiceManagement')}</Button>
        </div>
    </div>
};
