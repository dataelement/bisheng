import { TitleLogo } from "@/components/bs-comp/cardComponent";
import { AssistantIcon } from "@/components/bs-icons";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogTrigger } from "@/components/bs-ui/dialog";
import { useAssistantStore } from "@/store/assistantStore";
import { ChevronLeft, SquarePen } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import EditAssistantDialog from "./EditAssistantDialog";

export default function Header({ onSave, onLine, onTabChange }) {
    const { t } = useTranslation()

    const navigate = useNavigate()

    const { assistantState, dispatchAssistant } = useAssistantStore()
    {/* 编辑助手 */ }
    const [editShow, setEditShow] = useState(false);

    const needSaveRef = useRef(false)
    useEffect(() => {
        if (needSaveRef.current) {
            needSaveRef.current = false
            onSave()
        }
    }, [assistantState])
    const handleEditSave = (form) => {
        dispatchAssistant('setBaseInfo', form)
        setEditShow(false)
        needSaveRef.current = true
    }

    const [tabType, setTabType] = useState('edit')
    return <div className="flex justify-between bg-background-login items-center border-b px-4">
        <div className="flex items-center gap-2 py-4">
            <Button variant="outline" size="icon" onClick={() => navigate(-1)}><ChevronLeft className="h-4 w-4" /></Button>
            <TitleLogo
                url={assistantState.logo}
                id={assistantState.id}
                className="ml-4"
            ><AssistantIcon /></TitleLogo>
            <span className="bisheng-title">{assistantState.name}</span>
            {/* edit dialog */}
            <Dialog open={editShow} onOpenChange={setEditShow}>
                <DialogTrigger asChild>
                    <Button variant="ghost" size="icon"><SquarePen className="w-4 h-4" /></Button>
                </DialogTrigger>
                {
                    editShow && <EditAssistantDialog
                        logo={assistantState.logo || ''}
                        name={assistantState.name}
                        desc={assistantState.desc}
                        onSave={handleEditSave}></EditAssistantDialog>
                }
            </Dialog>
        </div>
        <div className="flex gap-4 items-center">
            <div
                className={`${tabType === 'edit' ? 'text-primary' : ''} hover:bg-secondary px-4 py-1 rounded-md cursor-pointer`}
                onClick={() => { setTabType('edit'); onTabChange('edit') }}
            >{t('api.assistantOrchestration')}</div>
            <div
                className={`${tabType === 'api' ? 'text-primary' : ''} hover:bg-secondary px-4 py-1 rounded-md cursor-pointer`}
                onClick={() => { setTabType('api'); onTabChange('api') }}
            >{t('api.externalPublishing')}</div>
        </div>
        <div className="flex gap-4">
            <Button variant="outline" className="px-10" type="button" onClick={onSave}>{t('build.save')}</Button>
            <Button type="submit" className="px-10" onClick={onLine}>{t('build.online')}</Button>
        </div>
    </div>
};

