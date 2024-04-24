import MultiSelect from "@/components/bs-ui/select/multi";
import { readFileLibDatabase } from "@/controllers/API";
import { useEffect, useRef, useState } from "react";

export default function KnowledgeBaseMulti({ value, onChange, children }:
    { value: any, onChange: (a: any) => any, children: (fun: any) => React.ReactNode }) {

    const [options, setOptions] = useState<any>([]);
    const originOptionsRef = useRef([])
    const reload = () => {
        readFileLibDatabase(1, 400).then(res => {
            originOptionsRef.current = res.data
            setOptions(res.data.map(el => ({ label: el.name, value: el.id })))
        })
    }

    useEffect(() => {
        reload()
    }, [])

    const handleChange = (res) => {
        // id => obj
        onChange(res.map(el => originOptionsRef.current.find(el2 => el2.id === el)))
    }

    return <MultiSelect
        value={value.map(el => el.id)}
        options={options}
        placeholder={"请选择知识库"}
        searchPlaceholder={"搜索知识库名称"}
        onChange={handleChange}
    >
        {children(reload)}
    </MultiSelect>
};
