import { Badge } from "@/components/bs-ui/badge";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { useState } from "react";
import { useTranslation } from "react-i18next"; // 引入国际化

export default function HistoryNumItem({ data, onChange }) {
    const { t } = useTranslation(); // 使用国际化
    const [value, setValue] = useState(data.value);

    return (
        <div className="flex items-center mb-4 nodrag -nopan">
            <Label className="bisheng-label">{t('recent')}</Label> {/* 最近 */}
            <Input
                type="number"
                min={0}
                boxClassName="w-20 mx-1"
                className="h-5"
                value={value}
                onKeyDown={(e) => {
                    ['-', 'e', '+'].includes(e.key) && e.preventDefault();
                }}
                onChange={(e) => {
                    const num = Number(e.target.value);
                    if (num >= 0) {
                        onChange(num);
                        setValue(num);
                    }
                }}
            />
            <Label className="bisheng-label">{t('chatRecords')}</Label> {/* 条聊天记录 */}
            <Badge variant="outline" className="bg-[#E6ECF6] text-[#2B53A0] ml-auto">
                {data.key}
            </Badge>
        </div>
    );
}
