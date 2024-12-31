
import { Button } from "@/components/bs-ui/button";
import { Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Sheet, SheetClose, SheetContent, SheetFooter, SheetHeader, SheetTitle } from "@/components/bs-ui/sheet";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { runWorkflowNodeApi } from "@/controllers/API/workflow";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { WorkflowNode } from "@/types/flow";
import { copyText } from "@/utils";
import { Copy, CopyCheck } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useState } from "react";
import { useTranslation } from "react-i18next";
import NodeLogo from "./NodeLogo";

interface Input {
    key: string,
    required: boolean,
    label: string,
    value: string
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

    return <div className="mb-2 rounded-md border bg-search-input text-sm shadow-sm">
        <div className="border-b px-2 flex justify-between items-center">
            <p>{title}</p>
            {copyed ? <CopyCheck size={14} /> : <Copy size={14} className="cursor-pointer" onClick={handleCopy} />}
        </div>
        <textarea defaultValue={text} disabled className="w-full min-h-28 p-2 block text-muted-foreground dark:bg-black " />
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

    useEffect(() => {
        if (!open) {
            setInputs([])
            setResults([])
        }
    }, [open])

    useImperativeHandle(ref, () => ({
        run: (node: WorkflowNode) => {
            setOpen(true)
            setNode(node)
            node.group_params.forEach((group) => {  
                group.params.forEach((param) => {
                    if (param.test === 'input') {
                        if (node.type === "tool") {
                            return setInputs((prev) => {
                                return [...prev, { key: param.label, required: false, label: param.label, value: '' }]
                            })
                        }
                        // if (param.type === 'code_input') {
                        // code_input类型特殊处理
                        return param.value.forEach(val => {
                            setInputs((prev) => {
                                return [...prev, { key: val.key, required: false, label: val.key, value: '' }]
                            })
                        })
                    } else if (param.test === 'var') {
                        let allVarInput = []
                        if (param.type === 'var_textarea') {
                            const regex = /{{#(.*?)#}}/g;
                            const parts = param.value.split(regex);
                            allVarInput = parts.reduce((res, part, index) => {
                                if (index % 2 === 1) {
                                    res.push({ key: part, required: false, label: param.varZh?.[part] || part, value: '' })
                                }
                                return res
                            }, [])
                        } else if (param.type === 'var_select') {
                            allVarInput = [{ key: param.value, required: false, label: param.varZh?.[param.value] || param.value, value: '' }]
                        } else if (param.type === 'user_question') {
                            allVarInput = param.value.map(part =>
                                ({ key: part, required: false, label: param.varZh?.[part] || part, value: '' })
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
                    description: `${input.label} 不可为空`
                })
                return true
            }
        })
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
                const result = res.map(item => ({ title: item.key, text: item.value }))
                setResults(result)
            })
        );
        setLoading(false)
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
                        <div className="mb-2" key={input.key}>
                            <Label className="flex items-center bisheng-label mb-2">
                                {input.required && <span className="text-red-500">*</span>}
                                {input.label}
                            </Label>
                            <Textarea
                                className=""
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
                    {results.map((res) => (
                        <ResultText key={res.text} title={res.title} value={res.text} />
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
