
import { Button } from "@/components/bs-ui/button";
import { Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Sheet, SheetClose, SheetContent, SheetFooter, SheetHeader, SheetTitle } from "@/components/bs-ui/sheet";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { WorkflowNode } from "@/types/flow";
import { copyText } from "@/utils";
import { Copy, CopyCheck } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useState } from "react";
import NodeLogo from "./NodeLogo";

interface Input {
    key: string,
    required: boolean,
    label: string,
    value: string
}

export const ResultText = ({ title, text }: { title: string, text: string }) => {
    const [copyed, setCopied] = useState(false)
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
        <textarea defaultValue={text} disabled className="w-full p-2 block text-muted-foreground " />
    </div>
}

// ref
export const RunTest = forwardRef((props, ref) => {
    const [open, setOpen] = useState(false)
    const [inputs, setInputs] = useState<Input[]>([])
    const [loading, setLoading] = useState(false)
    const [node, setNode] = useState<WorkflowNode>(null)
    const { message } = useToast()

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
                        if (param.type === 'code_input') {
                            // code_input类型特殊处理
                            return param.value.forEach(val => {
                                setInputs((prev) => {
                                    return [...prev, { key: val.key, required: false, label: val.key, value: '' }]
                                })
                            })
                        }
                        setInputs((prev) => {
                            return [...prev, { key: param.key, required: !!param.required, label: param.label || param.key, value: '' }]
                        })
                    }
                })
            })
        }
    }));

    const [results, setResults] = useState<any[]>([])
    const handleRunClick = () => {
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

        console.log('给后端什么 :>> ', node, inputs);
        console.log('结果展示 :>> ');
        setResults([
            { title: '输出1', text: '输出1' },
            { title: '输出1', text: '输出1' },
            { title: '输出1', text: '输出1' },
            { title: '输出1', text: '输出1' },
            { title: '输出1', text: '输出1' },
            { title: '输出1', text: '输出1' },
            { title: '输出1', text: '输出1' },
            { title: '输出1', text: '输出1' },
            { title: '输出2', text: '输出2' }
        ])

        setTimeout(() => {
            setLoading(false)
        }, 2000);
    }

    return (
        <Sheet open={open} onOpenChange={setOpen} >
            <SheetContent className="sm:max-w-96"
                onPointerDownOutside={(event) => {
                    event.preventDefault();
                }}
                onInteractOutside={(event) => {
                    event.preventDefault();
                }}>
                <SheetHeader>
                    <SheetTitle className="flex items-center p-2 text-md gap-2 font-normal">
                        {node && <NodeLogo type={node.type} colorStr={node.name} />}
                        单节点运行
                    </SheetTitle>
                </SheetHeader>
                <div className="px-2 pt-2 pb-10 h-[calc(100vh-40px)] overflow-y-auto bg-[#fff]">
                    {
                        inputs.map((input) => <div className="mb-2" key={input.key}>
                            <Label className="flex items-center bisheng-label mb-2">
                                {input.required && <span className="text-red-500">*</span>}
                                {input.label}
                            </Label>
                            <Textarea className="" onChange={(e) => {
                                setInputs((prev) => {
                                    return prev.map((item) => {
                                        if (item.key === input.key) {
                                            return { ...item, value: e.target.value }
                                        }
                                        return item
                                    })
                                })
                            }} />
                        </div>)
                    }

                    <Button className="w-full mb-2" disabled={loading} onClick={handleRunClick}>运行</Button>
                    {results.length !== 0 && <p className='mt-2 mb-3 text-sm font-bold'>运行结果</p>}
                    {results.map(res => <ResultText key={res.title} title={res.title} text={res.text} />)}
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
