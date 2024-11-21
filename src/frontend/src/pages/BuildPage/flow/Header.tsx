import { TitleLogo } from "@/components/bs-comp/cardComponent";
import { AssistantIcon } from "@/components/bs-icons";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Badge } from "@/components/bs-ui/badge";
import { Button } from "@/components/bs-ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { Bell, ChevronLeft, EllipsisVertical, PencilLineIcon, Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ChatTest } from "./FlowChat/ChatTest";
import useFlowStore from "./flowStore";

const Header = ({ flow, onTabChange }) => {
    const { message } = useToast()
    const testRef = useRef(null)
    const { uploadFlow } = useFlowStore()

    // 收集节点校验事件(表单 变量)
    const nodeValidateEntitiesRef = useRef({})
    useEffect(() => {
        const setNodeEvent = (e) => {
            const { action, id } = e.detail
            if (action === 'update') {
                nodeValidateEntitiesRef.current[id] = e.detail.validate
            } else {
                delete nodeValidateEntitiesRef.current[id]
            }
        }
        window.addEventListener('node_event', setNodeEvent)
        return () => {
            window.removeEventListener('node_event', setNodeEvent)
        }
    }, [])

    const handleRunClick = () => {
        // 记录错误日志
        let errors = []
        Object.keys(nodeValidateEntitiesRef.current).forEach(key => {
            errors = [...errors, ...nodeValidateEntitiesRef.current[key]()]
        })

        if (errors.length) return message({
            description: errors,
            variant: 'warning'
        })

        testRef.current?.run(flow)
    }

    const handleSaveClick = () => {
        // temp
        localStorage.setItem('flow_tmp', JSON.stringify(flow))
        message({
            variant: 'success',
            description: "已临时保存到本地"
        })
    }

    const handleExportClick = () => {
        setOpen(false)
        const jsonString = `data:text/json;chatset=utf-8,${encodeURIComponent(
            JSON.stringify({ ...flow })
        )}`;
        const link = document.createElement("a");
        link.href = jsonString;
        link.download = `${flow.name || '工作流实验数据'}.json`;

        link.click();
    }

    const handleImportClick = () => {
        setOpen(false)
        bsConfirm({
            desc: "导入将会覆盖现有工作流，确认导入？",
            onOk(next) {
                uploadFlow()
                next()
            }
        })
    }

    const [tabType, setTabType] = useState('edit')
    const [open, setOpen] = useState(false)
    return (
        <header className="flex justify-between items-center p-4 py-2 bisheng-bg border-b">
            {/* Left Section with Back Button and Title */}
            <div className="flex items-center">
                <Button variant="outline" size="icon" className="bg-[#fff] size-8"
                    onClick={() => {
                        window.history.back()
                    }}
                ><ChevronLeft /></Button>
                <div className="flex items-center ml-5">
                    <TitleLogo
                        url={''}
                        id={2}
                        className=""
                    ><AssistantIcon /></TitleLogo>
                    <div className="pl-3">
                        <h1 className="font-medium text-sm flex gap-2">
                            <span className="truncate max-w-48 font-bold">流程编排体验</span>
                            <Button size="icon" variant="ghost" className="size-6"><PencilLineIcon className="size-4 text-gray-500"></PencilLineIcon></Button>
                        </h1>
                        <p className="text-xs text-gray-500 mt-0.5">
                            <Badge variant="gray" className="font-light">当前版本: v0.0.0</Badge>
                        </p>
                    </div>
                </div>
            </div>
            <div>
                <Button variant="secondary" className={`${tabType === 'edit' ? 'bg-[#fff] hover:bg-[#fff]/70 text-primary h-8"' : ''} h-8`}
                    onClick={() => { setTabType('edit'); onTabChange('edit') }}
                >
                    流程编排
                </Button>
                <Button variant="secondary" className={`${tabType === 'api' ? 'bg-[#fff] hover:bg-[#fff]/70 text-primary h-8"' : ''} h-8`}
                    onClick={() => { setTabType('api'); onTabChange('api') }}>
                    对外发布
                </Button>
            </div>
            {/* Right Section with Options */}
            <div className="flex items-center gap-3">
                <Button size="icon" variant="outline" disabled className="bg-[#fff] h-8">
                    <Bell size={16} />
                </Button>
                <Button variant="outline" size="sm" className="bg-[#fff] h-8" onClick={handleRunClick}>
                    <Play className="size-3.5 mr-1" />
                    运行
                </Button>
                <Button variant="outline" size="sm" className="bg-[#fff] h-8 px-6" onClick={handleSaveClick}>
                    保存
                </Button>
                <Button size="sm" disabled className="h-8 px-6">
                    上线
                </Button>
                <Popover open={open} onOpenChange={setOpen}>
                    <PopoverTrigger asChild >
                        <Button size="icon" variant="outline" className="bg-[#fff] size-8">
                            <EllipsisVertical size={16} />
                        </Button>
                    </PopoverTrigger>
                    <PopoverContent className="w-auto p-2 cursor-pointer">
                        <div
                            className="rounded-sm py-1.5 pl-2 pr-8 text-sm hover:bg-[#EBF0FF] dark:text-gray-50 dark:hover:bg-gray-700"
                            onClick={handleImportClick}>导入工作流</div>
                        <div
                            className="rounded-sm py-1.5 pl-2 pr-8 text-sm hover:bg-[#EBF0FF] dark:text-gray-50 dark:hover:bg-gray-700"
                            onClick={handleExportClick}>导出工作流</div>
                    </PopoverContent>
                </Popover>
            </div>
            <ChatTest ref={testRef} />
        </header>
    );
};

export default Header;
