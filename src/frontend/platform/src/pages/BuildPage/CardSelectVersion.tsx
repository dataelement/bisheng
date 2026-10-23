import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { changeCurrentVersion } from "@/controllers/API/flow";
import { changeWorkflowCurrentVersion } from "@/controllers/API/workflow";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { AppNumType } from "@/types/app";
import { Select, Tooltip } from "@bisheng/ui";
import { useState } from "react";
import { useTranslation } from "react-i18next";

interface VersionCardData {
    id: string;
    flow_type: number;
    version_list: { id: number | string; name: string; is_current: number }[];
}

interface SelectCompProps {
    value: string;
    onChange?: (id: string) => void;
    data: VersionCardData;
    disabled?: boolean;
}

const SelectComp = ({ value, onChange, data, disabled = false }: SelectCompProps) => {

    const { t } = useTranslation()
    const selectLabels = useSelectLabels()

    const handleChange = (id: string) => {
        const request = data.flow_type === AppNumType.FLOW
            ? changeWorkflowCurrentVersion
            : changeCurrentVersion
        captureAndAlertRequestErrorHoc(request({ flow_id: data.id, version_id: Number(id) }))
        onChange?.(id)
    }

    const options = data.version_list.length
        ? data.version_list
            .filter(version => version.id != null && version.id !== '')
            .map(version => ({ value: String(version.id), label: version.name }))
        : [{ value: '0', label: 'v0' }]

    return <Select
        {...selectLabels}
        aria-label={t('skills.version')}
        size="small"
        className="w-[120px]"
        options={options}
        value={value || null}
        disabled={disabled}
        // Re-picking the current version must not re-send the switch request.
        onChange={(v) => { if (v != null && String(v) !== value) handleChange(String(v)) }}
    />
}

export default function CardSelectVersion(
    { showPop, ...props }:
        { showPop: boolean, data: VersionCardData }
) {
    const [value, setValue] = useState(String(props.data.version_list.find(item => item.is_current === 1)?.id ?? '0'))

    const { t } = useTranslation()

    if (showPop) return <Tooltip  content={<>
                <p className="text-[white]">{t('skills.chooseOnline')}</p>
             </>}><span className="inline-flex" tabIndex={0}><SelectComp {...props} value={value} onChange={setValue} /></span></Tooltip>


    return <SelectComp {...props} value={value} disabled={!showPop} />
};
