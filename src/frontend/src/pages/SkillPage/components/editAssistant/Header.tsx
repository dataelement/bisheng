import { TitleIconBg } from "@/components/bs-comp/cardComponent";
import { AssistantIcon } from "@/components/bs-icons/assistant";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogTrigger } from "@/components/bs-ui/dialog";
import { useAssistantStore } from "@/store/assistantStore";
import { ChevronLeftIcon, Pencil2Icon } from "@radix-ui/react-icons";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import EditAssistantDialog from "./EditAssistantDialog";
import { useTranslation } from "react-i18next";
import { useToast } from '@/components/bs-ui/toast/use-toast';
import { captureAndAlertRequestErrorHoc } from '@/controllers/request';
import { saveAssistanttApi } from '@/controllers/API/assistant';

export default function Header({ onSave, onLine }) {
    const { t } = useTranslation()

    const navigate = useNavigate()

    const { assistantState, dispatchAssistant } = useAssistantStore()
    {/* 编辑助手 */ }
    const [editShow, setEditShow] = useState(false);

    const { message } = useToast();

    const handleEditSave = async (form) => {
        await captureAndAlertRequestErrorHoc(
          saveAssistanttApi({
              ...assistantState,
              flow_list: assistantState.flow_list.map((item) => item.id),
              tool_list: assistantState.tool_list.map((item) => item.id),
              knowledge_list: assistantState.knowledge_list.map((item) => item.id),
              guide_question: assistantState.guide_question.filter((item) => item),
              ...form
          })
        ).then((res) => {
            if (!res) return;
            message({
                title: t('prompt'),
                variant: 'success',
                description: t('skills.saveSuccessful'),
            });
            dispatchAssistant('setBaseInfo', form);
            setEditShow(false);
        });
    };

    return <div className="flex justify-between items-center border-b px-4">
        <div className="flex items-center gap-2 py-4">
            <Button variant="outline" size="icon" onClick={() => navigate(-1)}><ChevronLeftIcon className="h-4 w-4" /></Button>
            <TitleIconBg id={assistantState.id} className="ml-4"><AssistantIcon /></TitleIconBg>
            <span className="bisheng-title">{assistantState.name}</span>
            {/* edit dialog */}
            <Dialog open={editShow} onOpenChange={setEditShow}>
                <DialogTrigger asChild>
                    <Button variant="ghost" size="icon"><Pencil2Icon /></Button>
                </DialogTrigger>
                {
                    editShow && <EditAssistantDialog
                        name={assistantState.name}
                        desc={assistantState.desc}
                        onSave={handleEditSave}></EditAssistantDialog>
                }
            </Dialog>
        </div>
        <div className="flex gap-4">
            <Button variant="outline" className="px-10" type="button" onClick={onSave}>{t('build.save')}</Button>
            <Button type="submit" className="px-10" onClick={onLine}>{t('build.online')}</Button>
        </div>
    </div>
};

