import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getFolderParentPathApi } from "~/api/knowledge";
import { NoPermissionIllustration, SystemErrorIllustration } from "~/components/illustrations";
import { Button } from "~/components/ui/Button";
import { useLocalize } from "~/hooks";

interface FolderUnavailableStateProps {
    spaceId: string;
    parentId?: string;
    reason: "missing" | "denied";
}

export function FolderUnavailableState({ spaceId, parentId, reason }: FolderUnavailableStateProps) {
    const localize = useLocalize();
    const navigate = useNavigate();
    const requestRef = useRef<AbortController | null>(null);
    const [returning, setReturning] = useState(false);
    const Illustration = reason === "missing" ? SystemErrorIllustration : NoPermissionIllustration;
    const spacePath = `/knowledge/space/${spaceId}`;

    useEffect(() => () => requestRef.current?.abort(), []);

    const handleReturn = async () => {
        if (!parentId) {
            navigate(spacePath, { replace: true });
            return;
        }
        const request = new AbortController();
        requestRef.current = request;
        setReturning(true);
        let destination = spacePath;
        try {
            const path = await getFolderParentPathApi(spaceId, parentId, {
                signal: request.signal,
                skipServiceMaintenance: true,
            });
            if (path[path.length - 1]?.id === parentId) destination = `${spacePath}/folder/${parentId}`;
        } catch {
            // Deleting an ancestor can invalidate both the folder and its last known parent.
        }
        if (!request.signal.aborted) navigate(destination, { replace: true });
    };

    return (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 p-4 text-center">
            <Illustration className="size-[120px]" />
            <p role="status" className="text-body text-text-3">
                {localize(reason === "missing" ? "com_knowledge.folder_missing" : "com_knowledge.folder_access_denied")}
            </p>
            <Button variant="outlined" color="default" loading={returning} onClick={handleReturn}>
                {localize(parentId ? "com_knowledge.go_to_parent_folder" : "com_knowledge.go_to_space_root")}
            </Button>
        </div>
    );
}
