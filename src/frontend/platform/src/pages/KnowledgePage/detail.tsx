import { toast } from '@bisheng/ui';
import { Outlined } from "bisheng-icons";


import { checkResourceActionApi } from "@/controllers/API/permission";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useEffect,useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate,useParams } from "react-router-dom";
import Files from "./components/Files";
import Header from "./components/Header";
import Paragraphs from "./components/Paragraphs";

export default function FilesPage() {
    const [value, setValue] = useState('file')
    const [fileId, setFileId] = useState('')
    const [fileTitle, setFileTitle] = useState(true);
    const [permissionChecked, setPermissionChecked] = useState(false);
    const [canEditKb, setCanEditKb] = useState(false);
    const [canDeleteKb, setCanDeleteKb] = useState(false);
    const { id: knowledgeId } = useParams();
    const navigate = useNavigate();

    const { t } = useTranslation('knowledge');

    useEffect(() => {
        const guardByPermission = async () => {
            if (!knowledgeId) {
                setPermissionChecked(true);
                navigate('/filelib');
                return;
            }
            const [result, editResult, deleteResult] = await Promise.all([
                captureAndAlertRequestErrorHoc(
                    checkResourceActionApi({ resource_type: 'knowledge_library', resource_id: String(knowledgeId), action: 'visible' })
                ),
                captureAndAlertRequestErrorHoc(
                    checkResourceActionApi({ resource_type: 'knowledge_library', resource_id: String(knowledgeId), action: 'edit' })
                ),
                captureAndAlertRequestErrorHoc(
                    checkResourceActionApi({ resource_type: 'knowledge_library', resource_id: String(knowledgeId), action: 'delete' })
                ),
            ]);
            const allowed = !!result?.allowed;
            setCanEditKb(!!editResult?.allowed);
            setCanDeleteKb(!!deleteResult?.allowed);
            setPermissionChecked(true);
            if (!allowed) {
                toast.show({ type: 'warning', message: String(t('noOperationPermission') ?? '') });
                navigate('/filelib');
            }
        };
        guardByPermission();
    }, [knowledgeId]);

    const onPreview = (id: string) => {
        setFileId(id)
        setValue('chunk')
        setFileTitle(false)
    }
    const handleBackFromChunk = () => {
        if (value === 'chunk') {
            setValue('file');
            setFileId('');
            setFileTitle(true)
        }
    };
    return <div className="size-full px-2 relative bg-background-login">
        {!permissionChecked && (
            <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/60">
                <Outlined.Loading  className="size-4 animate-spin"/>
            </div>
        )}
        {/* tab */}
        <div>
            {value === 'file' && <div>
                <div className="flex justify-between w-1/2 pt-4">
                    <Header fileTitle={fileTitle} showBackButton={true} />
                </div>
                <Files
                    onPreview={onPreview}
                    canEditKb={canEditKb}
                    canDeleteKb={canDeleteKb}
                />
            </div>}
            {value === 'chunk' && <div>
                <Paragraphs
                    fileId={fileId}
                    onBack={handleBackFromChunk}
                    canEditKb={canEditKb}
                    canDeleteKb={canDeleteKb}
                />
            </div>}
        </div>
    </div>
};
