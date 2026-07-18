import AppAvator from "@/components/bs-comp/cardComponent/avatar";
import { PermissionDialog } from "@/components/bs-comp/permission/PermissionDialog";
import { hasPermissionId, usePermissionIds } from "@/components/bs-comp/permission/usePermissionLevels";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogTrigger } from "@/components/bs-ui/dialog";
import { useAssistantStore } from "@/store/assistantStore";
import { OnlineState } from "@/types/flow";
import { ChevronLeft, Shield, SquarePen } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import EditAssistantDialog from "./EditAssistantDialog";

const APP_HEADER_PERMISSION_IDS = [
    'edit_app',
    'publish_app',
    'unpublish_app',
    'manage_app_owner',
    'manage_app_manager',
    'manage_app_viewer',
]

export default function Header({ loca, onSave, onLine, onTabChange, canEdit: canEditProp }) {
    const { t } = useTranslation()
    const navigate = useNavigate()

    const { assistantState, dispatchAssistant } = useAssistantStore()
    const assistantId = assistantState?.id ? String(assistantState.id) : ''
    const { permissions } = usePermissionIds('assistant', assistantId ? [assistantId] : [], APP_HEADER_PERMISSION_IDS)
    const canManage = assistantId ? (
        hasPermissionId(permissions, assistantId, 'manage_app_owner') ||
        hasPermissionId(permissions, assistantId, 'manage_app_manager') ||
        hasPermissionId(permissions, assistantId, 'manage_app_viewer')
    ) : false
    const canEdit = canEditProp ?? (assistantId ? hasPermissionId(permissions, assistantId, 'edit_app') : false)
    const canPublish = assistantId ? hasPermissionId(permissions, assistantId, 'publish_app') : false
    const canUnpublish = assistantId ? hasPermissionId(permissions, assistantId, 'unpublish_app') : false
    const [editShow, setEditShow] = useState(false);
    const [permDialogOpen, setPermDialogOpen] = useState(false);

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
            <AppAvator id={assistantState.name} url={assistantState.viewLogo || assistantState.logo} flowType={5} className="ml-4"></AppAvator>
            <span id="app-title" className="bisheng-title">{assistantState.name}</span>
            {/* edit dialog */}
            <Dialog open={editShow} onOpenChange={setEditShow}>
                <DialogTrigger asChild>
                    <Button variant="ghost" size="icon" disabled={!canEdit}><SquarePen className="w-4 h-4" /></Button>
                </DialogTrigger>
                {
                    editShow && <EditAssistantDialog
                        logo={assistantState.logo || ''}
                        viewLogo={assistantState.viewLogo || ''}
                        name={assistantState.name}
                        desc={assistantState.desc}
                        onSave={handleEditSave}
                        loca={loca}
                    ></EditAssistantDialog>
                }
            </Dialog>
        </div>
        <div className="flex gap-4 items-center">
            <div
                className={`${tabType === 'edit' ? 'text-primary' : ''} hover:bg-secondary px-4 py-1 rounded-md cursor-pointer`}
                onClick={() => { setTabType('edit'); onTabChange('edit') }}
            >{t('api.assistantOrchestration')}</div>
            {canEdit && <div
                className={`${tabType === 'api' ? 'text-primary' : ''} hover:bg-secondary px-4 py-1 rounded-md cursor-pointer`}
                onClick={() => {
                    setTabType('api');
                    onTabChange('api')
                }}
            >{t('api.externalPublishing')}</div>}
        </div>
        <div className="flex gap-4 items-center">
            {canManage && assistantState?.id && (
                <Button
                    type="button"
                    variant="outline"
                    className="flex items-center gap-2 px-4"
                    onClick={() => setPermDialogOpen(true)}
                >
                    <Shield className="h-4 w-4 shrink-0" />
                    {t('build.authorizationManagement')}
                </Button>
            )}
            <Button variant="outline" className="px-10" type="button" disabled={!canEdit} onClick={onSave}>{t('build.save')}</Button>
            {(assistantState.status === OnlineState.OnLine ? canUnpublish : canPublish) ? (
                <Button
                    type="submit"
                    className="px-10"
                    onClick={() => onLine(assistantState.status === OnlineState.OffLine)}
                >
                    {assistantState.status === OnlineState.OnLine ? t('build.offline') : t('build.online')}
                </Button>
            ) : null}
            {canManage && assistantState?.id ? (
                <PermissionDialog
                    open={permDialogOpen}
                    onOpenChange={setPermDialogOpen}
                    resourceType="assistant"
                    resourceId={String(assistantState.id)}
                    resourceName={assistantState.name || ""}
                />
            ) : null}
        </div>
    </div>
};
