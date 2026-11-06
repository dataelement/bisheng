import { Textarea } from '@bisheng/ui';

import { Label } from "@/components/bs-ui/label";
import { useState } from "react";
import { useTranslation } from "react-i18next";

export default function TextAreaItem({ data, onChange, i18nPrefix }) {
    const [value, setValue] = useState(data.value || '')
    const { t } = useTranslation('flow')

    return <div className='node-item mb-4' data-key={data.key}>
        <Label className='bisheng-label'>{t(`${i18nPrefix}label`)}</Label>
        <Textarea value={value} placeholder={t(`${i18nPrefix}placeholder`) || ''} onChange={(e) => {
                setValue(e.target.value);
                onChange(e.target.value);
            }} textareaClassName={"nodrag mt-2"}></Textarea>
    </div>
};
