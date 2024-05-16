import { Button } from "@/components/bs-ui/button";
import { DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import ChatReportForm from "@/pages/ChatAppPage/components/ChatReportForm";
import { useRef } from "react";

export default function RunForm({ show, flow, onChangeShow, onSubmit }) {

    const formRef = useRef(null);
    const handleSubmit = () => {
        formRef.current.submit()
    }

    return <DialogContent className="sm:max-w-[625px]">
        <DialogHeader>
            <DialogTitle>测试运行</DialogTitle>
            <DialogDescription>请输入上游依赖参数</DialogDescription>
        </DialogHeader>
        {
            show && <ChatReportForm ref={formRef} type='diff' vid={flow.id} flow={flow} onStart={onSubmit} />
        }
        <DialogFooter>
            <DialogClose>
                <Button variant="outline" className="px-11" type="button" onClick={onChangeShow}>取消</Button>
            </DialogClose>
            <Button type="submit" className="px-11" onClick={handleSubmit}>开始运行</Button>
        </DialogFooter>
    </DialogContent>
};
