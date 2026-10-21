import { isNumberDraftWithinBounds } from '@/utils/fieldValidation';
import { Input } from '@bisheng/ui';

import { Label } from "@/components/bs-ui/label";
import { Tag } from "@bisheng/ui";
import { useState } from "react";
import { useTranslation } from "react-i18next"; // 引入国际化

export default function HistoryNumItem({ data, onChange, i18nPrefix }) {
    const { t } = useTranslation('flow'); // 使用国际化
    const [value, setValue] = useState(data.value);

    return (
        <div className="flex items-center mb-4 nodrag -nopan">
            <Label className="bisheng-label">{t('recent')}</Label> {/* 最近 */}
            <Input type="number" min={0} value={value} onKeyDown={(e) => {
                    ['-', 'e', '+'].includes(e.key) && e.preventDefault();
                }} onChange={(e) => { if (!isNumberDraftWithinBounds(e.currentTarget.value, { min: 0 })) return; const num = Number(e.target.value);
if (num >= 0) {
                        onChange(num);
                        setValue(num);
                    } }} className={["w-20 mx-1", "h-5"].filter(Boolean).join(" ")} />
            <Label className="bisheng-label">{t('chatRecords')}</Label> {/* 条聊天记录 */}
            <Tag size="small" color="brand" className="ml-auto">
                {data.key}
            </Tag>
        </div>
    );
}
