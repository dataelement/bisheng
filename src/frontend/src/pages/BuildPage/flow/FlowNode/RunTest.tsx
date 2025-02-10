
import { Button } from "@/components/bs-ui/button";
import { Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Sheet, SheetClose, SheetContent, SheetFooter, SheetHeader, SheetTitle } from "@/components/bs-ui/sheet";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { runWorkflowNodeApi } from "@/controllers/API/workflow";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { WorkflowNode } from "@/types/flow";
import { copyText } from "@/utils";
import { Copy, CopyCheck } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useState } from "react";
import { useTranslation } from "react-i18next";
import useFlowStore from "../flowStore";
import NodeLogo from "./NodeLogo";

interface Input {
    key: string,
    required: boolean,
    label: string,
    value: string,
    autoFill: boolean
}

export const ResultText = ({ title, value }: { title: string, value: any }) => {
    const [copyed, setCopied] = useState(false)
    const [text, setText] = useState(() => {
        if (typeof value === 'object') {
            return JSON.stringify(value, null, 2)
        } else if (Array.isArray(value)) {
            return value.join('\n')
        } else {
            return value
        }
    })
    const handleCopy = (e) => {
        e.stopPropagation()

        setCopied(true)
        copyText(text)
        setTimeout(() => {
            setCopied(false)
        }, 2000)
    }

    return <div className="nodrag mb-2 rounded-md border bg-search-input text-sm shadow-sm" onKeyDown={e => e.stopPropagation()}>
        <div className="border-b px-2 flex justify-between items-center">
            <p>{title}</p>
            {copyed ? <CopyCheck size={14} /> : <Copy size={14} className="cursor-pointer" onClick={handleCopy} />}
        </div>
        <textarea defaultValue={text} readOnly className="w-full min-h-28 p-2 block text-muted-foreground bg-gray-100 dark:bg-black outline-none resize-none" />
    </div>
}

// ref
export const RunTest = forwardRef((props, ref) => {
    const [open, setOpen] = useState(false)
    const [inputs, setInputs] = useState<Input[]>([])
    const [loading, setLoading] = useState(false)
    const [node, setNode] = useState<WorkflowNode>(null)
    const { message } = useToast()
    const { t } = useTranslation('flow')
    const [currentIndex, setCurrentIndex] = useState(0)

    useEffect(() => {
        if (!open) {
            setInputs([])
            setResults([])
        }
    }, [open])

    const runCache = useFlowStore(state => state.runCache)
    const setRunCache = useFlowStore(state => state.setRunCache)

    useImperativeHandle(ref, () => ({
        run: (node: WorkflowNode) => {
            setOpen(true)
            setNode(node)

            // 自动填充
            const appendAutoFillin = (param) => {
                // 预置问题自动填充
                const autoFill = /start_[a-zA-Z0-9]+\.preset_question/.test(param.key)
                if (autoFill) {
                    return { ...param, autoFill, value: param.label.split('/')[1] }
                } else {
                    const cache = runCache[node.id]
                    const value = cache?.[param.key] || ''
                    return { ...param, autoFill, value }
                }
            }
            /**
             * 遍历当前节点的项,找出要做节点运行入参的input or var的项
             */
            node.group_params.forEach((group) => {
                group.params.forEach((param) => {
                    if (param.test === 'input') { // 遍历value[] ,每一项作为一个test输入
                        if (node.type === "tool") {
                            return setInputs((prev) => {
                                return [...prev, appendAutoFillin({ key: param.label, required: false, label: param.label, value: '' })]
                            })
                        }
                        // if (param.type === 'code_input') {
                        // code_input类型特殊处理
                        return param.value.forEach(val => {
                            setInputs((prev) => {
                                return [...prev, appendAutoFillin({ key: val.key, required: false, label: val.key, value: '' })]
                            })
                        })
                    } else if (param.test === 'var') { // 提取value中的变量,每个变量作为一个test输入
                        let allVarInput = []
                        if (param.type === 'var_textarea') { // 从textarea提取变量
                            const regex = /{{#(.*?)#}}/g;
                            const parts = param.value.split(regex);
                            allVarInput = parts.reduce((res, part, index) => {
                                if (index % 2 === 1) {
                                    res.push(appendAutoFillin({ key: part, required: false, label: param.varZh?.[part] || part, value: '' }))
                                }
                                return res
                            }, [])
                        } else if (param.type === 'var_select') { // 从变量选择列表提取变量
                            allVarInput = [appendAutoFillin({ key: param.value, required: false, label: param.varZh?.[param.value] || param.value, value: '' })]
                        } else if (param.type === 'user_question') { // 从批量问题提取变量
                            allVarInput = param.value.map(part =>
                                (appendAutoFillin({ key: part, required: false, label: param.varZh?.[part] || part, value: '' }))
                            )
                        }

                        setInputs(prev => [...prev,
                        // 非本节点
                        ...allVarInput.filter(input => !input.key.startsWith(node.id))])
                    }
                })
            })

            // 去重
            setInputs(prev => [...new Map(prev.map(item => [item.key, item])).values()])
        }
    }));

    const [results, setResults] = useState<any[]>([])
    const handleRunClick = async () => {
        inputs.some(input => {
            if (input.required && !input.value) {
                message({
                    variant: "warning",
                    description: `${input.label} ${t('required')}`
                })
                return true
            }
        })

        // save cache
        const cacheData = inputs.reduce((res, input) => {
            res[input.key] = input.value
            return res
        }, {})
        setRunCache(node.id, cacheData)

        setLoading(true)
        setResults([])
        await captureAndAlertRequestErrorHoc(
            runWorkflowNodeApi(
                inputs.reduce((result, input) => {
                    result[`${input.key}`] = input.value;
                    return result;
                }, {}),
                node
            ).then(res => {
                const result = res.map(el => TranslationName(el)) // .map(item => ({ title: item.key, text: item.value }))
                setResults(result)
            })
        );
        setLoading(false)
    }

    // 翻译变量名
    const TranslationName = (data) => {
        const newData = data.reduce((res, item) => {
            if (item.type === 'variable') {
                const key = item.key.split('.')
                res[key[key.length - 1]] = item.value
            } else {
                res[item.key] = item.value
            }
            return res
        }, {})
        let result = [];
        let hasKeys = []

        node.group_params.forEach(group => {
            group.params.forEach(param => {
                if (Array.isArray(param.value) && param.value.some(el => newData[el.key])) {
                    // 尝试去value中匹配
                    param.value.forEach(value => {
                        if (!newData[value.key]) return
                        result.push({ title: value.label, text: newData[value.key] })
                        hasKeys.push(value.key)
                    })
                } else if (newData[param.key] !== undefined) {
                    result.push({ title: param.label || param.key, text: newData[param.key] })
                    hasKeys.push(param.key)
                } else if (param.key === 'tool_list') {
                    // tool
                    param.value.some(p => {
                        if (newData[p.tool_key] !== undefined) {
                            result.push({ title: p.label, text: newData[p.tool_key] })
                            hasKeys.push(p.tool_key)
                            return true
                        }
                    })
                }
            });
        });
        return result
    }

    return (
        <Sheet open={open} onOpenChange={setOpen}>
            <SheetContent
                className="sm:max-w-96"
                onPointerDownOutside={(event) => {
                    event.preventDefault();
                }}
                onInteractOutside={(event) => {
                    event.preventDefault();
                }}
            >
                <SheetHeader>
                    <SheetTitle className="flex items-center p-2 text-md gap-2 font-normal">
                        {node && <NodeLogo type={node.type} colorStr={node.name} />}
                        {t('singleNodeRun')}
                    </SheetTitle>
                </SheetHeader>
                <div className="px-2 pt-2 pb-10 h-[calc(100vh-40px)] overflow-y-auto bg-[#fff] dark:bg-[#303134]">
                    {inputs.map((input) => (
                        input.autoFill ? null : <div className="mb-2" key={input.key}>
                            <Label className="flex items-center bisheng-label mb-2">
                                {input.required && <span className="text-red-500">*</span>}
                                {input.label}
                            </Label>
                            <Textarea
                                className=""
                                defaultValue={input.value}
                                onChange={(e) => {
                                    setInputs((prev) =>
                                        prev.map((item) =>
                                            item.key === input.key ? { ...item, value: e.target.value } : item
                                        )
                                    );
                                }}
                            />
                        </div>
                    ))}

                    <Button className="w-full mb-2" disabled={loading} onClick={handleRunClick}>
                        {t('run')}
                    </Button>
                    {results.length !== 0 && <p className="mt-2 mb-3 text-sm font-bold">{t('runResults')}</p>}
                    {results.length > 1 && <div className="mb-2">
                        <Select value={currentIndex + ""} onValueChange={(val => setCurrentIndex(Number(val)))}>
                            <SelectTrigger className="w-[180px]">
                                {/* <SelectValue /> */}
                                <span>第 {currentIndex + 1} 轮运行结果</span>
                            </SelectTrigger>
                            <SelectContent>
                                <SelectGroup>
                                    {
                                        results.map((_, index) => <SelectItem key={index} value={index + ""}>第 {index + 1} 轮运行结果</SelectItem>)
                                    }
                                </SelectGroup>
                            </SelectContent>
                        </Select>
                    </div>}
                    {results[currentIndex]?.map((res, i) => (
                        <ResultText key={res.text + i} title={res.title} value={res.text} />
                    ))}
                </div>
                <SheetFooter>
                    <SheetClose asChild>
                        {/* <Button type="submit">Save changes</Button> */}
                    </SheetClose>
                </SheetFooter>
            </SheetContent>
        </Sheet>
    )
})
