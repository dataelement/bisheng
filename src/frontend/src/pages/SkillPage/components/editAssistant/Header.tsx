import { ChevronLeftIcon, Pencil2Icon } from "@radix-ui/react-icons";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { SkillIcon } from "@/components/bs-icons/skill";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogTrigger } from "@/components/bs-ui/dialog";
import EditAssistantDialog from "./EditAssistantDialog";

export default function Header() {

    const navigate = useNavigate()
    {/* 编辑助手 */ }
    const [editShow, setEditShow] = useState(false);

    return <div className="flex justify-between items-center border-b px-4">
        <div className="flex items-center gap-2 py-4">
            <Button variant="outline" size="icon" onClick={() => navigate(-1)}><ChevronLeftIcon className="h-4 w-4" /></Button>
            <div className="bg-blue-600 rounded-sm ml-4"><SkillIcon></SkillIcon></div>
            <span className="bisheng-title">助手名称</span>
            <Dialog open={editShow} onOpenChange={setEditShow}>
                <DialogTrigger asChild>
                    <Button variant="ghost" size="icon"><Pencil2Icon /></Button>
                </DialogTrigger>
                <EditAssistantDialog onOpenChange={setEditShow}></EditAssistantDialog>
            </Dialog>
        </div>
        <div className="flex gap-4">
            <Button variant="outline" className="px-10" type="button" >保存</Button>
            <Button type="submit" className="px-10">上线</Button>
        </div>
    </div>
};

