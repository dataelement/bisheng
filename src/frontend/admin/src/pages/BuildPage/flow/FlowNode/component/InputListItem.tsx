import { InputList } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { generateUUID } from "@/components/bs-ui/utils";
import { useMemo } from "react";

export default function InputListItem({ data, dict, onChange }) {

    const value = useMemo(() => {
        const _value = data.value || [];

        // Check if the last element is empty and return the array as is if true
        const isLastItemEmpty = dict
            ? _value.length && _value[_value.length - 1].value === ''
            : _value.length && _value[_value.length - 1] === '';

        if (isLastItemEmpty) return _value;

        if (dict) {
            _value.push({ key: generateUUID(6), value: '' });
        } else {
            _value.push('');
        }

        return _value;
    }, [data]);

    return <div className='node-item mb-4'>
        <Label className="flex items-center bisheng-label">
            {data.label}
            {data.help && <QuestionTooltip content={data.help} />}
        </Label>
        <div className="nowheel nodrag overflow-y-auto max-h-52 mt-2">
            <InputList
                dict={dict}
                rules={[{ maxLength: 50, message: '最大50个字符' }]}
                value={value}
                onChange={(val) => {
                    const _val = val.slice(0, val.length - 1)
                    onChange(_val)
                }}
                placeholder={data.placeholder || ''}
            ></InputList>
        </div>
    </div>
};
