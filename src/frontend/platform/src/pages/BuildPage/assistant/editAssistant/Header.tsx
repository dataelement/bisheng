// @ts-strict-ignore
import { Button } from '@bisheng/ui';
import AppAvator from "@/components/bs-comp/cardComponent/avatar";
import { PermissionDialog } from "@/components/bs-comp/permission/PermissionDialog";
import { hasResourceAction,useResourceActions } from "@/components/bs-comp/permission/useResourceActions";

import { Dialog,DialogTrigger } from "@/components/bs-ui/dialog";
import { useAssistantStore } from "@/store/assistantStore";
import { OnlineState } from "@/types/flow";
import { Tabs } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { Shield } from "lucide-react";
import { useEffect,useRef,useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import EditAssistantDialog from "./EditAssistantDialog";

const APP_HEADER_ACTIONS = [
    'edit',
    'publish',
    'unpublish',
    'manage_permission',
]

export default function Header({ loca, onSave, onLine, onTabChange, canEdit: canEditProp }) {
    const { t } = useTranslation()
    const navigate = useNavigate()

    const { assistantState, dispatchAssistant } = useAssistantStore()
    const assistantId = assistantState?.id ? String(assistantState.id) : ''
    const { actions } = useResourceActions('assistant', assistantId ? [assistantId] : [], APP_HEADER_ACTIONS)
    const canManage = assistantId ? hasResourceAction(actions, assistantId, 'manage_permission') : false
    const canEdit = canEditProp ?? (assistantId ? hasResourceAction(actions, assistantId, 'edit') : false)
    const canPublish = assistantId ? hasResourceAction(actions, assistantId, 'publish') : false
    const canUnpublish = assistantId ? hasResourceAction(actions, assistantId, 'unpublish') : false
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
            <Button variant="outlined" size="medium" onClick={() => window.history.length > 1 ? navigate(-1) : navigate('/build/apps')} color="default" iconOnly><Outlined.Left className="h-4 w-4" /></Button>
            <AppAvator id={assistantState.name} url={assistantState.viewLogo || assistantState.logo} flowType={5} className="ml-4"></AppAvator>
            <span id="app-title" className="bisheng-title">{assistantState.name}</span>
            {/* edit dialog */}
            <Dialog open={editShow} onOpenChange={setEditShow}>
                <DialogTrigger asChild>
                    <Button variant="text" size="medium" disabled={!canEdit} color="default" iconOnly><Outlined.Edit className="w-4 h-4" /></Button>
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
        {canEdit ? <Tabs activeKey={tabType} onChange={value => { setTabType(value); onTabChange(value) }}
            items={[
                { key: 'edit', label: t('api.assistantOrchestration') },
                ...(canEdit ? [{ key: 'api', label: t('api.externalPublishing') }] : []),
            ]} /> : <span>{t('api.assistantOrchestration')}</span>}
        <div className="flex gap-4 items-center">
            {canManage && assistantState?.id && (
                <Button type="button" variant="outlined" className="flex items-center gap-2" onClick={() => setPermDialogOpen(true)} color="default">
                    <Shield className="h-4 w-4 shrink-0" />
                    {t('build.authorizationManagement')}
                </Button>
            )}
            <Button variant="outlined" type="button" disabled={!canEdit} onClick={onSave} color="default">{t('build.save')}</Button>
            {(assistantState.status === OnlineState.OnLine ? canUnpublish : canPublish) ? (
                <Button type="submit" onClick={() => onLine(assistantState.status === OnlineState.OffLine)}>
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
