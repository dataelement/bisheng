import { Label } from "@/components/bs-ui/label";
import { Select, SelectContent, SelectTrigger } from "@/components/bs-ui/select";
import { Check } from "lucide-react";
import { useState } from "react";

interface FileTypeSelectProps {
    data: {
        label: string;
        value: 'all' | 'file' | 'image';
    };
    onChange: (value: 'all' | 'file' | 'image') => void;
}

const options = [
    {
        label: '文档（pdf、txt、md、html、xls、xlsx、doc、docx、ppt、pptx）',
        value: 'file'
    },
    {
        label: '图片（png、jpg、jpeg、bmp）',
        value: 'image'
    }
];

export default function FileTypeSelect({ data, onChange }: FileTypeSelectProps) {
    const [type, setType] = useState(data.value)
    const handleSelect = (clickedValue: 'file' | 'image') => {
        let newValue: 'all' | 'file' | 'image' = type;

        if (type === 'all') {
            // 全选时点击某个类型：取消该类型，保留另一个
            newValue = clickedValue === 'file' ? 'image' : 'file';
        } else if (type !== clickedValue) {
            // 点击已选中的唯一类型：切换回全选
            newValue = 'all';
        } else {
            return
        }
        setType(newValue);
        onChange(newValue);
    };

    const getDisplayText = () => {
        switch (type) {
            case 'all': return '全部类型';
            case 'file': return '文档';
            case 'image': return '图片';
            default: return '全部类型';
        }
    };

    const isOptionSelected = (value: 'file' | 'image') => {
        return type === 'all' || type === value;
    };

    return (
        <div className='node-item flex gap-4 items-center mb-4'>
            <Label className="bisheng-label whitespace-nowrap">
                {data.label}
            </Label>
            <Select >
                <SelectTrigger>
                    {getDisplayText()}
                </SelectTrigger>
                <SelectContent className="">
                    {options.map((option) => (
                        <div
                            key={option.value}
                            data-focus={isOptionSelected(option.value)}
                            className="flex justify-between w-full select-none items-center mb-1 last:mb-0 rounded-sm p-1.5 text-sm outline-none cursor-pointer hover:bg-[#EBF0FF] data-[focus=true]:bg-[#EBF0FF] dark:hover:bg-gray-700 dark:data-[focus=true]:bg-gray-700 data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
                            onClick={() => handleSelect(option.value as 'file' | 'image')}
                        >
                            <span className="w-64 overflow-hidden text-ellipsis">
                                {option.label}
                            </span>
                            {isOptionSelected(option.value) && <Check className="h-4 w-4" />}
                        </div>
                    ))}
                </SelectContent>
            </Select>
        </div>
    );
}