import { InputList } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { generateUUID } from "@/components/bs-ui/utils";

export default function InputListItem({ data, dict, onChange }) {

    return <div className='node-item mb-4'>
        <Label className="flex items-center bisheng-label">
            {data.label}
            {data.help && <QuestionTooltip content={data.help} />}
        </Label>
        <div className="nowheel nodrag overflow-y-auto max-h-52 mt-2">
            <InputList
                dict={dict}
                rules={[{ maxLength: 50, message: '最大50个字符' }]}
                value={data.value.length ? data.value : dict ? [{ key: generateUUID(6), value: '' }] : ['']}
                onChange={onChange}
                placeholder={data.placeholder || ''}
            ></InputList>
        </div>
    </div>
};
