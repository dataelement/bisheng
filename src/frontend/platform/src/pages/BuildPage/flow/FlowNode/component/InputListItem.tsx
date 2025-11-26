import { InputList } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { generateUUID } from "@/components/bs-ui/utils";
import { useCallback, useEffect, useMemo } from "react";
import { useUpdateVariableState } from "../flowNodeStore";
import { debounce } from "lodash-es";
import { useTranslation } from "react-i18next";

export default function InputListItem({ node, data, preset, onChange }) {
    const [_, setUpdateVariable] = useUpdateVariableState()
    const { t } = useTranslation()

    const value = useMemo(() => {
        const _value = data.value || [];

        // Check if the last element is empty and return the array as is if true
        const isLastItemEmpty = preset
            ? _value.length && _value[_value.length - 1].value === ''
            : _value.length && _value[_value.length - 1] === '';

        if (isLastItemEmpty) return _value;

        if (preset) {
            _value.push({ key: generateUUID(6), value: '' });
        } else {
            _value.push('');
        }

        return _value;
    }, [data]);

    useEffect(() => {
        return () => {
            preset && setUpdateVariable(null)
        }
    }, [preset])

    const setDebouncePresetQuestion = useCallback(debounce((info) => {
        if (!info.value.trim()) return
        preset && info && setUpdateVariable({
            action: info.action,
            node: null,
            question: {
                id: info.id,
                name: info.value,
            }
        })
    }, 1000), [preset])

    const handleChange = (val, info) => {
        const _val = val.slice(0, val.length - 1)
        onChange(_val)

        setDebouncePresetQuestion(info)
    }

    return <div className='node-item mb-4'>
        <Label className="flex items-center bisheng-label">
            {data.label}
            {data.help && <QuestionTooltip content={data.help} />}
        </Label>
        <div className="nowheel nodrag overflow-y-auto max-h-52 mt-2">
            <InputList
                dict={preset}
                rules={[{ maxLength: 50, message: t('max50Characters') }]}
                value={value}
                onChange={handleChange}
                placeholder={data.placeholder || ''}
            ></InputList>
        </div>
    </div>
};
