import { Tabs, TabsContent } from "@/components/bs-ui/tabs";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { checkPermission } from "@/controllers/API/permission";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import Files from "./components/Files";
import Header from "./components/Header";
import Paragraphs from "./components/Paragraphs";

export default function FilesPage() {
    const [value, setValue] = useState('file')
    const [fileId, setFileId] = useState('')
    const [fileTitle, setFileTitle] = useState(true);
    const [permissionChecked, setPermissionChecked] = useState(false);
    const { id: knowledgeId } = useParams();
    const navigate = useNavigate();
    const { message } = useToast();
    const { t } = useTranslation('knowledge');

    useEffect(() => {
        const guardByPermission = async () => {
            if (!knowledgeId) {
                setPermissionChecked(true);
                navigate('/filelib');
                return;
            }
            const result = await captureAndAlertRequestErrorHoc(
                checkPermission('knowledge_space', String(knowledgeId), 'can_read')
            );
            const allowed = !!result?.allowed;
            setPermissionChecked(true);
            if (!allowed) {
                message({ variant: 'warning', description: t('noOperationPermission') });
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
                <LoadingIcon />
            </div>
        )}
        {/* tab */}
        <Tabs value={value} onValueChange={(v) => {
            setValue(v);
            setFileId('');
            if (v === 'file') {
                setFileTitle(true);
            } else {
                setFileTitle(false);
            }
        }}>
            <TabsContent value="file" className="mt-0">
                <div className="flex justify-between w-1/2 pt-4">
                    <Header fileTitle={fileTitle} showBackButton={true} />
                </div>
                <Files onPreview={onPreview} />
            </TabsContent>
            <TabsContent value="chunk" className="mt-0">
                <Paragraphs fileId={fileId} onBack={handleBackFromChunk} />
            </TabsContent>
        </Tabs>
    </div>
};
