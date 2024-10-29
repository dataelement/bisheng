import { TitleLogo } from "@/components/bs-comp/cardComponent";
import { AssistantIcon } from "@/components/bs-icons";
import { Badge } from "@/components/bs-ui/badge";
import { Button } from "@/components/bs-ui/button";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { Bell, CircleEllipsis, LogOut, PenLine, Play, Rocket } from "lucide-react";
import { useRef } from "react";
import { TestSheet } from "./FlowChat/TestSheet";

const Header = ({ flow }) => {
    const { message } = useToast()
    const testRef = useRef(null)

    const handleRunClick = () => {
        // 记录错误日志
        message({
            variant: 'warning',
            description: "跳过校验,启动会话"
        })

        testRef.current?.run(flow)
    }

    return (
        <header className="flex justify-between items-center p-4 py-2 bg-background shadow-md border-b">
            {/* Left Section with Back Button and Title */}
            <div className="flex items-center">
                <LogOut className="size-5 mr-4 rotate-180 cursor-pointer hover:opacity-80" />
                <div className="flex items-center ml-2">
                    <TitleLogo
                        url={''}
                        id={2}
                        className=""
                    ><AssistantIcon /></TitleLogo>
                    <div className="pl-4">
                        <h1 className="font-medium text-sm flex">
                            <span className="truncate max-w-48 font-bold">工作流名称</span>
                            <Button size="icon" variant="ghost" className="size-6"><PenLine className="size-4"></PenLine></Button>
                        </h1>
                        <p className="text-xs text-gray-500 ">
                            <Badge variant="secondary" className="font-light"><Rocket className="size-3.5 mr-1" /> 当前版本: v1</Badge>
                        </p>
                    </div>
                </div>
            </div>
            <div>
                <Button variant="link" >
                    流程编排
                </Button>
                <Button variant="link" >
                    对外发布
                </Button>
            </div>
            {/* Right Section with Options */}
            <div className="flex items-center">
                <Button size="icon" variant="ghost">
                    <Bell />
                </Button>
                <Button size="icon" variant="ghost" className="">
                    <CircleEllipsis />
                </Button>
                <Button variant="outline" size="sm" className="ml-4" onClick={handleRunClick}>
                    <Play className="size-3.5 mr-1" />
                    运行
                </Button>
                <Button variant="outline" size="sm" className="ml-4">
                    保存
                </Button>
                <Button size="sm" className="ml-4">
                    上线
                </Button>
            </div>
            <TestSheet ref={testRef} />
        </header>
    );
};

export default Header;
