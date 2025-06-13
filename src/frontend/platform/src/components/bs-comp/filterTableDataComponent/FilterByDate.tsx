import { useCallback } from "react";
import { DatePicker } from "@/components/bs-ui/calendar/datePicker";

interface DateFilterProps {
    value?: [Date | null, Date | null];
    onChange: (value: [Date | null, Date | null]) => void;
}

export default function FilterByDate({ value = [null, null], onChange }: DateFilterProps) {
    const [startDate, endDate] = value;

    /**
     * 处理日期变化，自动调整关联日期
     * startDate 不能晚于 endDate
     * endDate 不能早于 startDate
     */
    const handleDateChange = useCallback(
        (type: "start" | "end", date: Date | null) => {
            const newDates: [Date | null, Date | null] = [...value];

            if (type === "start") {
                newDates[0] = date;
                // 如果新开始日期晚于当前结束日期，则清空结束日期
                if (date && endDate && date > endDate) {
                    newDates[1] = null;
                }
            } else {
                newDates[1] = date;
                // 如果新结束日期早于当前开始日期，则清空开始日期
                if (date && startDate && date < startDate) {
                    newDates[0] = null;
                }
            }

            onChange(newDates);
        },
        [value, startDate, endDate, onChange]
    );

    return (
        <div className="flex gap-2 flex-wrap">
            <div className="w-[180px] relative">
                <DatePicker
                    value={startDate}
                    placeholder="开始日期"
                    onChange={(v) => handleDateChange("start", v)}
                />
            </div>
            <div className="w-[180px] relative">
                <DatePicker
                    value={endDate}
                    placeholder="结束日期"
                    onChange={(v) => handleDateChange("end", v)}
                />
            </div>
        </div>
    );
};