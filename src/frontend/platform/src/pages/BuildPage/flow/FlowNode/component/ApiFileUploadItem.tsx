import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { readFileParam } from "@/pages/BuildPage/utils/apiFileParam";
import { useEffect, useState } from "react";

export default function ApiFileUploadItem({ node, data, onChange, onValidate }) {
    const [error, setError] = useState(false);

    useEffect(() => {
        data.required && onValidate(() => {
            if (!data.value?.content) {
                setError(true);
                return `${data.label} required`;
            }
            setError(false);
            return false;
        });
        return () => onValidate(() => { });
    }, [data.value]);

    const handleChange = async (file?: File) => {
        if (!file) {
            onChange('');
            return;
        }
        onChange(await readFileParam(file));
    };

    return (
        <div className='node-item mb-4 max-w-2xl nodrag' data-key={data.key}>
            <Label className="flex items-center bisheng-label">
                {data.label}{data.required && <span className="text-red-500 ml-1">*</span>}
            </Label>
            <Input
                className={`mt-2 nodrag ${error ? 'border-red-500' : ''}`}
                type="file"
                onChange={(event) => handleChange(event.currentTarget.files?.[0])}
            />
            {data.value?.name && <p className="bisheng-label text-xs mt-1">{data.value.name}</p>}
            <p className="bisheng-label text-xs mt-1">{node.is_preset ? data.label : data.desc}</p>
        </div>
    );
}
