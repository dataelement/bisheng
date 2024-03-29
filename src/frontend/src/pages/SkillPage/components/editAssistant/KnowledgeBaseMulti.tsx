import MultiSelect from "@/components/bs-ui/select/multi";
import { readFileLibDatabase } from "@/controllers/API";
import { useEffect, useState } from "react";

export default function KnowledgeBaseMulti({ value, onChange, children }:
    { value: any, onChange: (a: any) => any, children: (fun: any) => React.ReactNode }) {

    const [options, setOptions] = useState<any>([]);
    const reload = () => {
        readFileLibDatabase(1, 400).then(res => {
            setOptions(res.data.map(el => ({ label: el.name, value: el.id })))
        })
    }

    useEffect(() => {
        reload()
    }, [])

    return <MultiSelect
        value={value}
        options={options}
        placeholder={"请选择知识库"}
        searchPlaceholder={"搜索知识库名称"}
        onChange={onChange}
    >
        {children(reload)}
    </MultiSelect>
};
