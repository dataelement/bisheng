import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Dropdown from "../../../components/dropdownComponent";
import InputComponent from "../../../components/inputComponent";
import InputFileComponent from "../../../components/inputFileComponent";
import { Button } from "../../../components/ui/button";
import { alertContext } from "../../../contexts/alertContext";
import { getVariablesApi } from "../../../controllers/API/flow";

/**
 * @component 会话报告生成专用表单
 * @description
 * 表单项数据由组件的参数信息和单独接口获取的必填信息及排序信息而来。
 * 
 */
export default function ChatReportForm({ flow, onStart }) {
    const { setErrorData } = useContext(alertContext);
    const { t } = useTranslation()

    // 从 api中获取
    const [items, setItems] = useState([])
    useEffect(() => {
        getVariablesApi({ flow_id: flow.id }).then(
            res => setItems(res)
        )
    }, [])

    const handleChange = (index, value) => {
        setItems(items.map((item, i) =>
            i === index ? { ...item, value } : item))
    }

    const handleStart = () => {
        // 校验
        const errors = items.reduce((res, el) => {
            if (el.required && !el.value) {
                res.push(`${el.name} is null`)
            }
            return res
        }, [])
        if (errors.length) {
            return setErrorData({
                title: t('prompt'),
                list: errors,
            });
        }

        // 组装数据，抛出
        const obj = items
        const str = items.map(el => `${el.name}：${el.value}\n`)
        onStart(obj, str)
    }

    return <div className="absolute right-20 bottom-32 w-[90%] max-w-[680px] flex flex-col gap-6 rounded-xl p-4 md:p-6 border bg-gray-50">
        {items.map((item, i) => <div key={item.id} className="w-full text-sm">
            {item.name}
            <span className="text-status-red">{item.required ? " *" : ""}</span>
            <div className="mt-2">
                {item.type === 'text' ? <InputComponent
                    password={false}
                    value={item.value}
                    onChange={(val) => handleChange(i, val)}
                /> :
                    item.type === 'select' ?
                        <Dropdown
                            options={item.options.map(e => e.value)}
                            onSelect={(val) => handleChange(i, val)}
                            value={item.value}
                        ></Dropdown> :
                        item.type === 'file' ?
                            <InputFileComponent
                                disabled={false}
                                value={item.value}
                                onChange={(e) => console.log('e :>> ', e)}
                                fileTypes={["pdf"]}
                                suffixes={[".pdf"]}
                                onFileChange={(val: string) => handleChange(i, val)}
                            ></InputFileComponent> : <></>
                }
            </div>
        </div>
        )}
        <Button size="sm" onClick={handleStart}>{t('report.start')}</Button>
    </div>
};
