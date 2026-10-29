import { toast } from '@bisheng/ui';

import { updateKnowledgeApi } from "@/controllers/API";
import { showApiError } from "@/controllers/request";
import { Outlined } from "bisheng-icons";
import { KnowledgeTooltip } from "./KnowledgeTooltip";

import { useEffect,useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation,useNavigate,useParams } from "react-router-dom";


import useKnowledgeStore from "../useKnowledgeStore";

interface HeaderProps {
    fileTitle: boolean;
    onBack?: () => void; // 添加回退回调
    showBackButton?: boolean; // 控制是否显示回退按钮
}

export default function Header({ fileTitle, onBack, showBackButton = true }: HeaderProps) {
    const [libInfo, setLibInfo] = useState({ name: '', desc: '' })
    const [open, setOpen] = useState(false)
    const { id } = useParams()
    const { t } = useTranslation()
    const navigate = useNavigate()
    const location = useLocation()

    useEffect(() => {
        // @ts-ignore
        const [libname, libdesc] = window.libname || [] // 临时记忆
        if (libname) {
            localStorage.setItem('libname', libname)
            localStorage.setItem('libdesc', libdesc)
        }
        setLibInfo({ name: libname || localStorage.getItem('libname'), desc: libdesc || localStorage.getItem('libdesc') })
    }, [])

    // 默认的回退逻辑
    const handleBackDefault = () => {
        // 检查是否有历史记录可回退
        if (window.history.length > 1) {
            navigate(-1);
        } else {
            // 如果没有历史记录，回退到文件库首页
            navigate('/filelib');
        }
    }

    // 使用传入的回调或默认回调
    const handleBackClick = onBack || handleBackDefault;


    const handleSave = (form) => {
        updateKnowledgeApi({
            knowledge_id: Number(id),
            name: form.name,
            description: form.desc
        }).then((res) => {
            if (!res) return
            // api
            setLibInfo(form)
            setOpen(false)
            toast.show({ type: 'success', message: String(t('saved') ?? '') })
            localStorage.setItem('libname', form.name)
            localStorage.setItem('libdesc', form.desc)
        }).catch(showApiError)
    }

    const { isEditable } = useKnowledgeStore();

    return (
        <div className="flex items-start h-14 z-30">
            {/* 回退按钮 - 根据 showBackButton 控制显示 */}
            {showBackButton && (
                <KnowledgeTooltip content={t('back')} side="top">
                    <button
                        className="extra-side-bar-buttons w-[36px]"
                        onClick={handleBackClick}
                    >
                        <Outlined.ArrowLeft className="side-bar-button-size" />
                    </button>
                </KnowledgeTooltip>
            )}

            <div>
                <div className="group flex items-center">
                    {fileTitle && (
                        <span className="text-foreground text-sm font-black pl-4 truncate max-w-80">
                            {libInfo.name}
                        </span>
                    )}
                    <div className="h-10"></div>
                    {/* edit dialog */}
                    {/* {isEditable ? <Dialog open={open} onOpenChange={setOpen}>
                        <DialogTrigger asChild>
                            <Button variant="ghost" size="icon" className="group-hover:visible invisible disabled:pointer-events-auto">
                                <Outlined.Edit className="w-4 h-4" />
                            </Button>
                        </DialogTrigger>
                        {
                            open && <KnowledgeBaseSettingsDialog
                                initialName={libInfo.name}
                                initialDesc={libInfo.desc}
                                onSave={handleSave}
                            />
                        }
                    </Dialog> : <div className="h-10"></div>} */}
                </div>
            </div>
        </div>
    )
}
