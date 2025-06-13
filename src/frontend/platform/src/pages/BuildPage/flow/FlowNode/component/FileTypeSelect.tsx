import { Label } from "@/components/bs-ui/label";
import { Select, SelectContent, SelectTrigger } from "@/components/bs-ui/select";
import { Check } from "lucide-react";
import { useState } from "react";

type FileType = 'file' | 'image' | 'audio';

type FileTypes = FileType[];

interface FileTypeSelectProps {
    data: {
        label: string;
        value: FileTypes;
    };
    onChange: (value: FileTypes) => void;
}

const options: { value: FileType, label: string }[] = [
    {
        label: '文档（pdf、txt、md、html、xls、xlsx、doc、docx、ppt、pptx）',
        value: 'file'
    },
    {
        label: '图片（png、jpg、jpeg、bmp）',
        value: 'image'
    },
    {
        label: '音频（mp3）',
        value: 'audio'
    }
];

export default function FileTypeSelect({ data, onChange }: FileTypeSelectProps) {
    const [types, setTypes] = useState<FileTypes>(data.value)
    const handleSelect = (clickedValue: FileType) => {
        let newValue = types;
        // 原来已存在 则移除
        if (types.includes(clickedValue)) {
            //只剩一项不允许删除
            if (types.length === 1) return;
            newValue = types.filter(item => item !== clickedValue);
        } else {
            newValue = [...types, clickedValue];
        }
        setTypes(newValue);
        onChange(newValue);
    };

    const getDisplayText = () => {
        if (types.length === 3) return "全部类型";
        const map = {
            file: '文档',
            image: '图片',
            audio: '音频',
        };
        return types.map(item => map[item]).join('、');
    };

    const isOptionSelected = (value: 'file' | 'image' | 'audio') => {
        return types.includes(value)
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
                            onClick={() => handleSelect(option.value as FileType)}
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