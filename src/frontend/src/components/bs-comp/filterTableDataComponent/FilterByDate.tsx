import { DatePicker } from "@/components/bs-ui/calendar/datePicker";
export default function FilterByDate({ value, onChange }) {


    return <>
        <div className="w-[180px] relative">
            <DatePicker value={value[0]} placeholder="开始日期" onChange={(v) => onChange([v, value[1]])} />
        </div>
        <div className="w-[180px] relative">
            <DatePicker value={value[1]} placeholder="结束日期" onChange={(v) => onChange([value[0], v])} />
        </div>
    </>
};
