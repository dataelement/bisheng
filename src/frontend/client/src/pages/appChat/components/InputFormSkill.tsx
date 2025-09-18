
import { forwardRef, useContext, useEffect, useImperativeHandle, useRef, useState } from "react";
import { getVariablesApi } from "~/api/apps";
import { useToastContext } from "~/Providers";
import { useLocalize } from "~/hooks";
import InputComponent from "./InputComponent";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "~/components/ui/Select";
import InputFileComponent from "./InputFileComponent";
import { Button } from "~/components";
import { emitAreaTextEvent, EVENT_TYPE } from "../useAreaText";
import { MessageWarper } from "./MessageBsChoose";

/**
 * @component 会话报告生成专用表单
 * @description
 * 表单项数据由组件的参数信息和单独接口获取的必填信息及排序信息而来。
 */
const InputFormSkill = forwardRef(({ flow, logo }, ref) => {
    const type = 'chat'
    const vid = 0
    const { showToast } = useToastContext();
    const localize = useLocalize()

    useImperativeHandle(ref, () => ({
        submit: () => {
            handleStart()
        }
    }));

    // 从 api中获取
    const [items, setItems] = useState<any[]>([])
    useEffect(() => {
        if (flow.flow_type === 5) return
        // chat -》L1； diff -> 对比测试
        type === 'chat' ? getVariablesApi({ flow_id: flow.flow_id || flow.id }).then(
            res => setItems(res)
        ) : getVariablesApi({ version_id: vid, flow_id: flow.flow_id || flow.id }).then(
            res => setItems(res)
        )
    }, [])

    const handleChange = (index, value) => {
        setItems((_items) => _items.map((item, i) =>
            i === index ? { ...item, value } : item))
    }

    // 文件名 kv关系
    const fileKindexVpath = useRef({})
    const handleStart = () => {
        // 校验
        const errors = items.reduce((res, el) => {
            if (el.required && !el.value) {
                res.push(`${el.name} 是必填项`)
            }
            if (el.type === 'text' && el.value.length > Number(el.maxLength)) {
                res.push(`${el.name} 长度不能超过 ${el.maxLength}`)
            }
            return res
        }, [])
        if (errors.length) {
            showToast({ message: errors.join('\n'), status: 'error' });
        }

        // 组装数据，抛出
        const obj = items
        const str = items.map((el, i) => `${el.name ? el.name + '：' : ''}${el.type === 'file'
            ? fileKindexVpath.current[i] : el.value}\n`).join('')

        const formdata = obj.map(item => ({
            id: item.nodeId,
            name: item.name,
            file_path: item.type === 'file' ? item.value : '',
            value: item.type === 'file' ? '' : item.value
        }))
        console.log('obj, str :>> ', formdata, str);
        // onStart(obj, str)
        emitAreaTextEvent({
            action: EVENT_TYPE.FORM_SUBMIT,
            data: formdata,
            nodeId: null,
            message: str,
            skill: true
        })
    }

    if (items.length === 0) return null

    return <MessageWarper flow={flow} logo={logo}>
        <div className="">
            <div className="max-h-[520px] overflow-y-auto space-y-2 px-1">
                {items.map((item, i) => <div key={item.id} className="w-full text-sm">
                    {item.name}
                    <span className="text-red-500">{item.required ? " *" : ""}</span>
                    <div className="mt-2">
                        {item.type === 'text' ? <InputComponent
                            type='textarea'
                            password={false}
                            value={item.value}
                            onChange={(val) => handleChange(i, val)}
                        /> :
                            item.type === 'select' ?
                                <Select onValueChange={(val) => handleChange(i, val)}>
                                    <SelectTrigger>
                                        <SelectValue placeholder="" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectGroup>
                                            {
                                                item.options.map(el => <SelectItem key={el.value} value={el.value}>{el.value}</SelectItem>)
                                            }
                                        </SelectGroup>
                                    </SelectContent>
                                </Select> :
                                item.type === 'file' ?
                                    <InputFileComponent
                                        isSSO
                                        disabled={false}
                                        placeholder={localize('com_file_current_empty')}
                                        value={''}
                                        onChange={(e) => fileKindexVpath.current[i] = e}
                                        fileTypes={["pdf"]}
                                        suffixes={flow.data.nodes.find(el => el.id === item.nodeId)
                                            ?.data.node.template.file_path.suffixes || ['xxx']}
                                        onFileChange={(val: string) => handleChange(i, val)}
                                        flow={flow}
                                    ></InputFileComponent> : <></>
                        }
                    </div>
                </div>
                )}
            </div>
            {type === 'chat' && <div className="flex justify-end">
                <Button size="sm" className="mt-4 h-8 px-4" onClick={handleStart}>开始</Button>
            </div>}
        </div>
    </MessageWarper>
});

export default InputFormSkill