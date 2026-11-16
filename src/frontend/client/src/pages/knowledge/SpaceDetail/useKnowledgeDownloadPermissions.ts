import { useQueries } from '@tanstack/react-query';
import { useEffect, useId, useMemo, useRef } from 'react';
import { FileType } from '~/api/knowledge';
import { inspectBatch } from '~/api/knowledgeBatch';
import { showApiError } from '~/api/request';
import { useAuthContext } from '~/hooks';
import type { UseKnowledgeFilePermissionsOptions } from './knowledgeSpaceTypes';

/** Download eligibility is read independently of list loading, selection, and menus. */
export function useKnowledgeDownloadPermissions({
    displayFiles, space, currentFolderId, downloadPages, downloadEpoch = 0,
}: UseKnowledgeFilePermissionsOptions) {
    const { user } = useAuthContext();
    const instance = useId();
    const generation = useRef(0);
    const spaceId = Number(space.id);
    const identity = JSON.stringify([user?.id, user?.role, user?.tenant_id]);
    const prefix = useMemo(
        () => ['knowledge-download-permissions', instance, ++generation.current, identity, space.id, currentFolderId, downloadEpoch],
        [instance, identity, space.id, currentFolderId, downloadEpoch],
    );
    const files = displayFiles.filter(file => !file.isCreating &&
        /^[1-9][0-9]*$/.test(file.id) && Number.isSafeInteger(Number(file.id)));
    const byId = new Map(files.map(file => [file.id, file]));
    const pages = downloadPages ?? [files.map(file => file.id)];
    const listed = new Set(pages.flat());
    // Status polling can prepend newly uploaded rows outside the cursor pages.
    const added = files.filter(file => !listed.has(file.id)).map(file => file.id);
    const reads = added.length ? [...pages, added] : pages;
    const queries = useQueries({
        queries: reads.map((ids, index) => {
            const rows = ids.flatMap(id => byId.has(id) ? [byId.get(id)!] : []);
            const items = rows.map(file => ({ id: Number(file.id), type: file.type === FileType.FOLDER ? 'folder' as const : 'file' as const }));
            return {
                queryKey: [...prefix, index, rows],
                queryFn: async () => (await inspectBatch({ spaceId, operation: 'download', items })).inspection,
                enabled: Boolean(user?.id) && Number.isSafeInteger(spaceId) && spaceId > 0 && items.length > 0,
                staleTime: Infinity,
                cacheTime: 0,
                retry: false,
                refetchOnWindowFocus: false,
            };
        }),
    });
    const error = queries.find(query => query.isError)?.error;
    useEffect(() => { if (error) showApiError(error); }, [error]);
    return new Set(queries.flatMap(query => query.isSuccess && query.data.check_complete
        ? query.data.valid_items.filter(item => byId.has(String(item.id)) &&
            item.type === (byId.get(String(item.id))!.type === FileType.FOLDER ? 'folder' : 'file')).map(item => String(item.id))
        : []));
}
