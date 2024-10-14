import { Dialog, DialogTrigger } from "@/components/bs-ui/dialog";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { updateKnowledgeApi } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { ArrowLeft, SquarePen } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import { Button } from "../../../components/bs-ui/button";
import ShadTooltip from "../../../components/ShadTooltipComponent";
import KnowledgeBaseSettingsDialog from "./EditKnowledgeDialog";

export default function Header() {
    const [libInfo, setLibInfo] = useState({ name: '', desc: '' })
    const [open, setOpen] = useState(false)
    const { id } = useParams()
    const { t } = useTranslation()

    useEffect(() => {
        // @ts-ignore
        const [libname, libdesc] = window.libname || [] // 临时记忆
        if (libname) {
            localStorage.setItem('libname', libname)
            localStorage.setItem('libdesc', libdesc)
        }
        setLibInfo({ name: libname || localStorage.getItem('libname'), desc: libdesc || localStorage.getItem('libdesc') })
    }, [])

    const { message } = useToast()
    const handleSave = (form) => {
        captureAndAlertRequestErrorHoc(updateKnowledgeApi({
            knowledge_id: Number(id),
            name: form.name,
            description: form.desc
        })).then((res) => {
            if (!res) return
            // api
            setLibInfo(form)
            setOpen(false)
            message({ variant: 'success', description: t('saved') })
            localStorage.setItem('libname', form.name)
            localStorage.setItem('libdesc', form.desc)
        })
    }

    return <div className="flex items-start h-14">
        <ShadTooltip content="back" side="top">
            <button className="extra-side-bar-buttons w-[36px]" onClick={() => { }} >
                <Link to='/filelib'><ArrowLeft className="side-bar-button-size" /></Link>
            </button>
        </ShadTooltip>
        <div>
            <div className="group flex items-center">
                <span className=" text-foreground text-sm font-black pl-4">{libInfo.name}</span>
                {/* edit dialog */}
                <Dialog open={open} onOpenChange={setOpen} >
                    <DialogTrigger asChild>
                        <Button variant="ghost" size="icon" className="group-hover:visible invisible"><SquarePen className="w-4 h-4" /></Button>
                    </DialogTrigger>
                    {
                        open && <KnowledgeBaseSettingsDialog initialName={libInfo.name} initialDesc={libInfo.desc} onSave={handleSave}></KnowledgeBaseSettingsDialog>
                    }
                </Dialog>
            </div>
            <p className="pl-4 text-muted-foreground text-sm">{libInfo.desc}</p>
        </div>
    </div>
};
