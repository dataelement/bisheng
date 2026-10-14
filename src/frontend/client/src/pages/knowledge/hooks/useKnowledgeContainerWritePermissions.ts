import { useEffect, useState } from "react";
import { useRecoilValue } from "recoil";
import { checkPermission } from "~/api/permission";
import store from "~/store";

interface ContainerWritePermissionOptions {
    spaceId?: string;
    folderId?: string;
    isSpaceAdmin: boolean;
}

type PermissionSnapshot = {
    key: string;
    canCreateFolder: boolean;
    canUploadFile: boolean;
};

export function useKnowledgeContainerWritePermissions({
    spaceId,
    folderId,
    isSpaceAdmin,
}: ContainerWritePermissionOptions) {
    const user = useRecoilValue(store.user);
    const bypass = Boolean(spaceId && isSpaceAdmin && !folderId);
    const scopeKey = JSON.stringify([
        user?.id, user?.role, (user as { tenant_id?: number } | null)?.tenant_id,
        spaceId, folderId, bypass,
    ]);
    const [snapshot, setSnapshot] = useState<PermissionSnapshot | null>(null);

    useEffect(() => {
        // 切换目录或账号后立即失效，不让旧授权在加载期间继续生效。
        setSnapshot({ key: scopeKey, canCreateFolder: false, canUploadFile: false });
        if (!spaceId || bypass) return;
        const controller = new AbortController();
        let cancelled = false;
        const objectType = folderId ? "folder" : "knowledge_space";
        const objectId = folderId || spaceId;
        const uploadPermissionId = folderId ? "upload_file_to_folder" : "upload_file_to_space";
        const options = { signal: controller.signal, cacheScope: scopeKey };
        Promise.allSettled([
            checkPermission(objectType, objectId, "can_edit", "create_folder", options),
            checkPermission(objectType, objectId, "can_edit", uploadPermissionId, options),
        ]).then(([createResult, uploadResult]) => {
            if (cancelled) return;
            setSnapshot({
                key: scopeKey,
                canCreateFolder: createResult.status === "fulfilled" && Boolean(createResult.value?.allowed),
                canUploadFile: uploadResult.status === "fulfilled" && Boolean(uploadResult.value?.allowed),
            });
        });
        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [scopeKey, spaceId, folderId, bypass]);

    const current = Boolean(spaceId && snapshot?.key === scopeKey);
    return {
        canCreateFolder: bypass || Boolean(current && snapshot?.canCreateFolder),
        canUploadFile: bypass || Boolean(current && snapshot?.canUploadFile),
    };
}
