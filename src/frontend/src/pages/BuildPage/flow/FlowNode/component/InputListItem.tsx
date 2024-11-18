import { InputList } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";

export default function InputListItem({ data, onChange }) {

    return <div className='node-item mb-4'>
        <Label className="flex items-center bisheng-label">
            {data.label}
            {data.help && <QuestionTooltip content={data.help} />}
        </Label>
        <InputList
            className="mt-2"
            rules={[{ maxLength: 50, message: '最大50个字符' }]}
            value={data.value.length ? data.value : ['']}
            onChange={onChange}
            placeholder={data.placeholder || ''}
        ></InputList>
    </div>
};
