import { Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { useState } from "react";
import { useTranslation } from "react-i18next";

export default function TextAreaItem({ data, onChange, i18nPrefix }) {
    const [value, setValue] = useState(data.value || '')
    const { t } = useTranslation('flow')

    return <div className='node-item mb-4' data-key={data.key}>
        <Label className='bisheng-label'>{t(`${i18nPrefix}label`)}</Label>
        <Textarea value={value}
            className="nodrag mt-2"
            placeholder={t(`${i18nPrefix}placeholder`) || ''}
            onChange={(e) => {
                setValue(e.target.value);
                onChange(e.target.value);
            }}
        ></Textarea>
    </div>
};
