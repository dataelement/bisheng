import { TitleIconBg } from "@/components/bs-comp/cardComponent";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogTrigger } from "@/components/bs-ui/dialog";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { useAssistantStore } from "@/store/assistantStore";
import { ChevronLeftIcon, Pencil2Icon } from "@radix-ui/react-icons";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import EditAssistantDialog from "./EditAssistantDialog";

export default function Header() {
    const navigate = useNavigate()

    const { assistantState, dispatchAssistant } = useAssistantStore()
    {/* 编辑助手 */ }
    const [editShow, setEditShow] = useState(false);

    const handleEditSave = (form) => {
        dispatchAssistant('setBaseInfo', form)
        setEditShow(false)
    }

    const { message, toast } = useToast()
    // 保存助手详细信息
    const handleSave = () => {
        console.log('result => ', assistantState);
        message({
            title: '保存成功',
            variant: 'success',
            description: '未联调'
        })
    }

    const handleOnlineClick = () => {
        console.log('result => ', assistantState);
        message({
            title: '未联调',
            variant: 'error',
            description: '未联调'
        })
    }

    return <div className="flex justify-between items-center border-b px-4">
        <div className="flex items-center gap-2 py-4">
            <Button variant="outline" size="icon" onClick={() => navigate(-1)}><ChevronLeftIcon className="h-4 w-4" /></Button>
            <TitleIconBg id={assistantState.id} className="ml-4"></TitleIconBg>
            <span className="bisheng-title">{assistantState.name}</span>
            {/* edit dialog */}
            <Dialog open={editShow} onOpenChange={setEditShow}>
                <DialogTrigger asChild>
                    <Button variant="ghost" size="icon"><Pencil2Icon /></Button>
                </DialogTrigger>
                <EditAssistantDialog
                    name={assistantState.name}
                    desc={assistantState.desc}
                    onSave={handleEditSave}></EditAssistantDialog>
            </Dialog>
        </div>
        <div className="flex gap-4">
            <Button variant="outline" className="px-10" type="button" onClick={handleSave}>保存</Button>
            <Button type="submit" className="px-10" onClick={handleOnlineClick}>上线</Button>
        </div>
    </div>
};

