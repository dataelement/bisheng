import { useCallback, useEffect, useRef, useState } from "react";
import {
    FileType, getFolderParentPathApi, getFolderDeletionStatusesApi, reconcileFolderDeletionApi,
    type FolderDeletionStateItem, type FolderDeletionStatus, type KnowledgeFile,
} from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { useLocalize } from "~/hooks";
import { useRefreshEffectiveQuota } from "~/hooks/useEffectiveQuota";
import { useToastContext } from "~/Providers";
import { dispatchKnowledgeSpaceFilesRefresh } from "./useFileManager";
import { dispatchFileChangeApprovalRefresh } from "./fileMutationUtils";

export type FolderDeletionStateReader = (spaceId: string | number, folderId: string) => "running" | "unknown" | undefined;
export type FolderDeletionGuard = (spaceId: string | number, folderId?: string | null) => Promise<boolean>;
export type FolderDeletionObservation = { epoch: number; versions: Map<string, number> };
export type FolderDeletionSnapshot = {
    observation?: FolderDeletionObservation;
    spaceId: string;
    folderId?: string;
    files: KnowledgeFile[];
    projectedFiles?: KnowledgeFile[];
    scopeDeletionStatus?: FolderDeletionStatus | null;
};
type DeletingFolder = {
    file?: KnowledgeFile;
    spaceId: string;
    id: string;
    viewFolderId?: string;
    uncertain: boolean;
    operationId?: string | null;
    local: boolean;
    requestPending: boolean;
    baselineOperationId?: string | null;
    attempt: number;
};
interface UseFolderDeletionOptions {
    serverEnabled?: boolean;
    identityKey: string;
    spaceId?: string;
    folderId?: string;
    enabled: boolean;
}

export function isDeleteRequestUncertain(error: unknown): boolean {
    const failure = error as { status_code?: number; response?: { status?: number }; code?: string };
    return failure.status_code === 500 || (!failure.status_code && (!failure.response || (failure.response.status ?? 0) >= 500 || failure.response.status === 408));
}
const folderDeletionKey = (spaceId: string | number, id: string) => `${spaceId}:${id}`;

/** Page-owned locks: server observations and pending local attempts share one ancestry map. */
export function useFolderDeletion(options: UseFolderDeletionOptions) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const refreshQuota = useRefreshEffectiveQuota();
    const ui = useRef({ localize, showToast });
    ui.current = { localize, showToast };
    const entries = useRef(new Map<string, DeletingFolder>());
    const lastOperations = useRef(new Map<string, string | null>());
    const versions = useRef(new Map<string, number>());
    const inheritedRoots = useRef(new Map<string, string>());
    const parents = useRef(new Map<string, string | undefined>());
    const checking = useRef(new Set<string>());
    const reconciledAt = useRef(new Map<string, number>());
    const snapshot = useRef<FolderDeletionSnapshot>();
    const sequence = useRef(0);
    const authority = useRef({ identity: options.identityKey, scope: "", epoch: 0 });
    const currentScope = `${options.spaceId}:${options.folderId ?? ""}:${options.enabled}`;
    if (authority.current.identity !== options.identityKey) {
        entries.current.clear(); lastOperations.current.clear(); versions.current.clear(); inheritedRoots.current.clear(); parents.current.clear(); checking.current.clear(); reconciledAt.current.clear();
        snapshot.current = undefined;
        authority.current = { identity: options.identityKey, scope: currentScope, epoch: authority.current.epoch + 1 };
    } else if (authority.current.scope !== currentScope) {
        snapshot.current = undefined;
        authority.current = { ...authority.current, scope: currentScope, epoch: authority.current.epoch + 1 };
    }
    const latestOptions = useRef(options);
    latestOptions.current = options;
    const [revision, setRevision] = useState(0);
    const changed = useCallback(() => setRevision(value => value + 1), []);
    const notify = useCallback(() => {
        ui.current.showToast({ message: ui.current.localize("com_knowledge.folder_deleting_blocked"), severity: NotificationSeverity.WARNING });
    }, []);
    const findEntry = useCallback((spaceId: string | number, id?: string | null): DeletingFolder | undefined => {
        const visited = new Set<string>();
        while (id && !visited.has(id)) {
            visited.add(id);
            const key = folderDeletionKey(spaceId, id);
            const root = inheritedRoots.current.get(key);
            const entry = entries.current.get(key) ?? (root ? entries.current.get(folderDeletionKey(spaceId, root)) : undefined);
            if (entry) return entry;
            id = parents.current.get(folderDeletionKey(spaceId, id));
        }
        return undefined;
    }, []);
    const getDeletionState: FolderDeletionStateReader = useCallback((spaceId, id) => {
        const entry = findEntry(spaceId, id);
        return entry ? entry.uncertain ? "unknown" : "running" : undefined;
    }, [findEntry]);
    const isDeleting = useCallback((spaceId: string | number, id?: string | null) => Boolean(findEntry(spaceId, id)), [findEntry]);
    const restore = useCallback((spaceId: string, status: FolderDeletionStatus, file?: KnowledgeFile) => {
        const id = String(status.root_folder_id);
        const key = folderDeletionKey(spaceId, id);
        const previous = entries.current.get(key);
        const same = previous && (!previous.operationId || previous.operationId === status.operation_id)
            && !(previous.local && !previous.operationId && !status.operation_id);
        versions.current.set(key, (versions.current.get(key) ?? 0) + 1);
        entries.current.set(key, {
            ...(same ? previous : undefined), spaceId, id,
            file: file?.id === id ? file : same ? previous.file : undefined,
            uncertain: status.state === "unknown", operationId: status.operation_id,
            local: same ? previous.local && Boolean(status.operation_id) : false,
            requestPending: same ? previous.requestPending : false, attempt: same ? previous.attempt : ++sequence.current,
        });
    }, []);
    const captureObservation = useCallback((): FolderDeletionObservation => ({ epoch: authority.current.epoch, versions: new Map(versions.current) }), []);
    const observe = useCallback((value: FolderDeletionSnapshot) => {
        if (!latestOptions.current.serverEnabled || value.spaceId !== latestOptions.current.spaceId || value.folderId !== latestOptions.current.folderId) return;
        if (value.observation && value.observation.epoch !== authority.current.epoch) return;
        const before = new Map(versions.current);
        const isFresh = (id: string) => !value.observation || (value.observation.versions.get(folderDeletionKey(value.spaceId, id)) ?? 0) === (before.get(folderDeletionKey(value.spaceId, id)) ?? 0);
        snapshot.current = value;
        (value.projectedFiles ?? value.files).forEach(file => {
            parents.current.set(folderDeletionKey(value.spaceId, file.id), file.parentId);
            const key = folderDeletionKey(value.spaceId, file.id);
            if (file.deletionStatus) {
                const root = String(file.deletionStatus.root_folder_id);
                if (isFresh(root) || entries.current.get(folderDeletionKey(value.spaceId, root))?.operationId === file.deletionStatus.operation_id) inheritedRoots.current.set(key, root);
                if (isFresh(root)) restore(value.spaceId, file.deletionStatus, file);
            } else if (isFresh(inheritedRoots.current.get(key) ?? file.id)) inheritedRoots.current.delete(key);
        });
        if (value.scopeDeletionStatus && isFresh(String(value.scopeDeletionStatus.root_folder_id))) {
            restore(value.spaceId, value.scopeDeletionStatus);
            if (value.folderId) inheritedRoots.current.set(folderDeletionKey(value.spaceId, value.folderId), String(value.scopeDeletionStatus.root_folder_id));
        } else if (!value.scopeDeletionStatus && value.folderId && isFresh(inheritedRoots.current.get(folderDeletionKey(value.spaceId, value.folderId)) ?? value.folderId)) inheritedRoots.current.delete(folderDeletionKey(value.spaceId, value.folderId));
        changed();
    }, [changed, restore]);
    const applyStatus = useCallback((spaceId: string, item: FolderDeletionStateItem) => {
        const id = String(item.folder_id);
        const key = folderDeletionKey(spaceId, id);
        const entry = entries.current.get(key);
        lastOperations.current.set(key, item.operation_id);
        if (item.state === "running" || item.state === "unknown") {
            restore(spaceId, { state: item.state, root_folder_id: item.folder_id, operation_id: item.operation_id });
        } else if (item.state === "idle" && entry && !entry.local && !entry.operationId) {
            // A visible alias has no historical token; idle explicitly ends its inherited lock.
            entries.current.delete(key);
            versions.current.set(key, (versions.current.get(key) ?? 0) + 1);
            dispatchKnowledgeSpaceFilesRefresh(spaceId);
        } else if (item.state === "untracked") {
            if (entry) {
                entry.uncertain = true;
                versions.current.set(key, (versions.current.get(key) ?? 0) + 1);
            }
        } else if (item.state === "succeeded" || item.state === "failed" || item.state === "approval_pending" || item.state === "unavailable") {
            // Losing the HTTP response cannot turn the preflight's old terminal into this attempt's result.
            if (entry?.local && !entry.operationId && (entry.requestPending || (item.state !== "unavailable" && (!item.operation_id || item.operation_id === entry.baselineOperationId)))) return;
            // Unknown history never produces a success toast. Terminal results refresh the original space.
            entries.current.delete(key);
            versions.current.set(key, (versions.current.get(key) ?? 0) + 1);
            if (entry) {
                dispatchKnowledgeSpaceFilesRefresh(spaceId);
                if (item.state === "succeeded") void refreshQuota();
                if (item.state === "approval_pending") dispatchFileChangeApprovalRefresh(spaceId);
                if (item.state === "failed") ui.current.showToast({ message: ui.current.localize("com_knowledge.folder_delete_failed"), severity: NotificationSeverity.ERROR });
            }
        }
        // An idle snapshot cannot end a still-pending local DELETE whose claim may not yet be visible.
        changed();
    }, [changed, refreshQuota, restore]);
    const query = useCallback(async (spaceId: string, ids: string[], epoch: number, signal?: AbortSignal) => {
        const all: FolderDeletionStateItem[] = [];
        for (let offset = 0; offset < ids.length; offset += 100) {
            if (signal?.aborted) return undefined;
            const batch = ids.slice(offset, offset + 100);
            const before = new Map(batch.map(id => {
                const key = folderDeletionKey(spaceId, id);
                return [id, { entry: entries.current.get(key), version: versions.current.get(key) ?? 0 }] as const;
            }));
            const known = batch.flatMap(id => {
                const operationId = before.get(id)?.entry?.operationId;
                return operationId ? [{ folder_id: Number(id), operation_id: operationId }] : [];
            });
            const items = await getFolderDeletionStatusesApi(spaceId, batch, known, signal);
            if (authority.current.epoch !== epoch) return undefined;
            items.forEach(item => {
                const id = String(item.folder_id);
                if (before.has(id) && entries.current.get(folderDeletionKey(spaceId, id)) === before.get(id)?.entry && (versions.current.get(folderDeletionKey(spaceId, id)) ?? 0) === before.get(id)?.version) {
                    applyStatus(spaceId, item);
                    all.push(item);
                }
            });
        }
        return all;
    }, [applyStatus]);
    // Timer, list and visibility triggers share one polling cycle.
    const polling = useRef<Promise<void> | null>(null);
    const pollAbort = useRef<AbortController>();
    const poll = useCallback(() => {
        if (polling.current) return polling.current;
        const { serverEnabled, enabled, spaceId, folderId } = latestOptions.current;
        if (!serverEnabled || !enabled || !spaceId || document.visibilityState === "hidden") return Promise.resolve();
        const epoch = authority.current.epoch;
        const ids = new Set<string>();
        for (const entry of entries.current.values()) if (entry.spaceId === spaceId) ids.add(entry.id);
        const visible = snapshot.current;
        visible?.files.forEach(file => ids.add(file.id));
        if (folderId) ids.add(folderId);
        for (const id of [...ids]) {
            let parent = parents.current.get(folderDeletionKey(spaceId, id));
            const visited = new Set<string>();
            while (parent && !visited.has(parent)) { visited.add(parent); ids.add(parent); parent = parents.current.get(folderDeletionKey(spaceId, parent)); }
        }
        const controller = new AbortController();
        pollAbort.current = controller;
        const work = (async () => {
            const items = await query(spaceId, [...ids], epoch, controller.signal);
            if (!items || authority.current.epoch !== epoch) return;
            for (const item of items) {
                if (document.visibilityState === "hidden" || authority.current.epoch !== epoch) return;
                const operationId = item.operation_id;
                if (item.state !== "unknown" || !item.can_reconcile || !operationId) continue;
                const key = `${spaceId}:${item.folder_id}:${operationId}`;
                if (checking.current.has(key) || Date.now() - (reconciledAt.current.get(key) ?? 0) < 10000) continue;
                checking.current.add(key); reconciledAt.current.set(key, Date.now());
                const entry = entries.current.get(folderDeletionKey(spaceId, String(item.folder_id)));
                try {
                    const result = await reconcileFolderDeletionApi(spaceId, String(item.folder_id), operationId, controller.signal);
                    if (authority.current.epoch === epoch && entries.current.get(folderDeletionKey(spaceId, String(item.folder_id))) === entry) applyStatus(spaceId, result);
                } finally { checking.current.delete(key); }
            }
            // Only an explicit not-found can stop observing untracked history; existence never unlocks it.
            for (const item of items.filter(value => value.state === "untracked")) {
                const key = folderDeletionKey(spaceId, String(item.folder_id));
                const entry = entries.current.get(key);
                if (!entry) continue;
                try { await getFolderParentPathApi(spaceId, entry.id, { skipServiceMaintenance: true, signal: controller.signal }); }
                catch (error) {
                    if ((error as { status_code?: number }).status_code === 18020 && authority.current.epoch === epoch && entries.current.get(key) === entry) {
                        entries.current.delete(key); versions.current.set(key, (versions.current.get(key) ?? 0) + 1); changed(); dispatchKnowledgeSpaceFilesRefresh(spaceId);
                    }
                }
            }
        })().catch(() => {
            if (controller.signal.aborted || authority.current.epoch !== epoch) return;
            for (const [key, entry] of entries.current) if (entry.spaceId === spaceId) {
                entry.uncertain = true;
                versions.current.set(key, (versions.current.get(key) ?? 0) + 1);
            }
            changed();
        });
        polling.current = work;
        void work.finally(() => { if (polling.current === work) polling.current = null; });
        return work;
    }, [applyStatus, changed, query]);
    useEffect(() => {
        if (!options.serverEnabled || !options.enabled || !options.spaceId) return;
        void poll();
        const timer = setInterval(() => { void poll(); }, 3000);
        const visible = () => {
            if (document.visibilityState !== "hidden") void poll();
            else { pollAbort.current?.abort(); polling.current = null; }
        };
        document.addEventListener("visibilitychange", visible);
        return () => {
            clearInterval(timer); document.removeEventListener("visibilitychange", visible);
            pollAbort.current?.abort(); polling.current = null;
        };
    }, [options.serverEnabled, options.enabled, options.spaceId, options.folderId, options.identityKey, poll]);
    const guardLocation = useCallback(async (spaceIdValue: string | number, folderId?: string | null, isFile = false) => {
        if (!folderId) return false;
        const spaceId = String(spaceIdValue);
        if (!isFile && isDeleting(spaceId, folderId)) { notify(); return true; }
        const server = latestOptions.current.serverEnabled;
        if (server === undefined) { notify(); return true; }
        if (!server && ![...entries.current.values()].some(entry => entry.spaceId === spaceId)) return false;
        const epoch = authority.current.epoch;
        const location = window.location.pathname;
        try {
            if (server) {
                // The permitted target is the authority: its projection includes hidden deleting ancestors.
                const items = await query(spaceId, [folderId], epoch);
                if (authority.current.epoch !== epoch || window.location.pathname !== location) return true;
                if (items?.length === 1 && ["idle", "failed", "approval_pending"].includes(items[0].state)) return false;
                notify(); return true;
            }
            const path = await getFolderParentPathApi(spaceId, folderId, { skipServiceMaintenance: true });
            if (authority.current.epoch !== epoch || window.location.pathname !== location) return true;
            if (!path.some(item => item.id === folderId)) { notify(); return true; }
            path.forEach((item, index) => parents.current.set(folderDeletionKey(spaceId, item.id), path[index - 1]?.id));
            if (!isDeleting(spaceId, folderId)) return false;
        } catch { /* A failed lookup cannot establish that this target is safe. */ }
        notify(); return true;
    }, [isDeleting, notify, query]);
    const guardFolder: FolderDeletionGuard = useCallback((spaceId, folderId) => guardLocation(spaceId, folderId), [guardLocation]);
    const guardMovedItem = useCallback((spaceId: string, id: string, type: "file" | "folder") => guardLocation(spaceId, id, type === "file"), [guardLocation]);
    const guardItems = useCallback(async (spaceId: string, files: KnowledgeFile[]) => {
        const server = latestOptions.current.serverEnabled;
        if (server === undefined && files.length) { notify(); return true; }
        if (server) {
            const ids = [...new Set(files.map(file => file.id))];
            if (!ids.length) return false;
            if (ids.some(id => isDeleting(spaceId, id))) { notify(); return true; }
            const epoch = authority.current.epoch;
            const location = window.location.pathname;
            try {
                const items = await query(spaceId, ids, epoch);
                if (authority.current.epoch !== epoch || window.location.pathname !== location) return true;
                if (items?.length === ids.length && items.every(item => ["idle", "failed", "approval_pending"].includes(item.state))) return false;
            } catch { /* All selected targets must have an authoritative safe result. */ }
            notify(); return true;
        }
        const folderIds = new Set(files.map(file => file.type === FileType.FOLDER ? file.id : file.parentId));
        for (const folderId of folderIds) if (await guardFolder(spaceId, folderId)) return true;
        return false;
    }, [guardFolder, isDeleting, notify, query]);
    const begin = useCallback((spaceId: string, files: KnowledgeFile[], viewFolderId?: string) => {
        const folders = files.filter(file => file.type === FileType.FOLDER);
        if (folders.some(file => isDeleting(spaceId, file.id))) { notify(); return false; }
        folders.forEach(file => {
            const key = folderDeletionKey(spaceId, file.id);
            versions.current.set(key, (versions.current.get(key) ?? 0) + 1);
            entries.current.set(key, {
                file: { ...file, spaceId }, spaceId, id: file.id, viewFolderId,
                uncertain: false, local: true, requestPending: true,
                baselineOperationId: lastOperations.current.get(key), attempt: ++sequence.current,
            });
        });
        if (folders.length) changed();
        return true;
    }, [changed, isDeleting, notify]);
    const isCurrentIdentity = useCallback((identity: string) => authority.current.identity === identity, []);
    const captureAttempts = useCallback((spaceId: string, ids: string[]) => ({
        identity: authority.current.identity,
        attempts: new Map(ids.map(id => [id, entries.current.get(folderDeletionKey(spaceId, id))?.attempt])),
    }), []);
    const finish = useCallback((spaceId: string, ids: string[], expected?: ReturnType<typeof captureAttempts>) => {
        if (expected && expected.identity !== authority.current.identity) return;
        ids.forEach(id => {
            const key = folderDeletionKey(spaceId, id);
            if (!expected || entries.current.get(key)?.attempt === expected.attempts.get(id)) {
                entries.current.delete(key);
                versions.current.set(key, (versions.current.get(key) ?? 0) + 1);
            }
        });
        changed();
    }, [changed]);
    const reconcile = useCallback((spaceId: string) => {
        if (latestOptions.current.serverEnabled !== false) { void poll(); return; }
        const identity = authority.current.identity;
        for (const [key, entry] of entries.current) {
            if (entry.spaceId !== spaceId || !entry.uncertain || checking.current.has(key)) continue;
            checking.current.add(key);
            void getFolderParentPathApi(spaceId, entry.id, { skipServiceMaintenance: true }).then(path => {
                if (authority.current.identity === identity && path.some(item => item.id === entry.id) && entries.current.get(key) === entry) finish(spaceId, [entry.id]);
            }).catch((error: unknown) => {
                if (authority.current.identity === identity && (error as { status_code?: number }).status_code === 18020 && entries.current.get(key) === entry) {
                    finish(spaceId, [entry.id]); dispatchKnowledgeSpaceFilesRefresh(spaceId);
                }
            }).finally(() => checking.current.delete(key));
        }
    }, [finish, poll]);
    const uncertain = useCallback((spaceId: string, ids: string[], expected?: ReturnType<typeof captureAttempts>, operations?: Map<string, string | null | undefined>) => {
        if (expected && expected.identity !== authority.current.identity) return;
        ids.forEach(id => {
            const entry = entries.current.get(folderDeletionKey(spaceId, id));
            if (entry && (!expected || entry.attempt === expected.attempts.get(id))) {
                entry.uncertain = true;
                entry.requestPending = false;
                if (operations?.get(id)) entry.operationId = operations.get(id);
                const key = folderDeletionKey(spaceId, id);
                versions.current.set(key, (versions.current.get(key) ?? 0) + 1);
            }
        });
        changed();
    }, [changed]);
    const mergeFiles = useCallback((spaceId: string, folderId: string | undefined, files: KnowledgeFile[], path: Array<{ id?: string }> = []) => {
        path.forEach((item, index) => { if (item.id) parents.current.set(folderDeletionKey(spaceId, item.id), path[index - 1]?.id); });
        files.forEach(file => parents.current.set(folderDeletionKey(spaceId, file.id), file.parentId));
        const result = files.map(file => {
            const entry = findEntry(spaceId, file.id) ?? findEntry(spaceId, file.parentId);
            return { ...file, isDeleting: Boolean(entry), deletionState: entry ? entry.uncertain ? "unknown" as const : "running" as const : undefined };
        });
        for (const entry of entries.current.values()) {
            if (entry.file && entry.local && entry.spaceId === spaceId && entry.viewFolderId === folderId && !result.some(file => file.id === entry.id)) {
                result.push({ ...entry.file, isDeleting: true, deletionState: entry.uncertain ? "unknown" : "running" });
            }
        }
        return result;
    }, [findEntry]);
    const scopeDeletionState = options.folderId ? getDeletionState(options.spaceId ?? "", options.folderId)
        ?? (options.serverEnabled && !snapshot.current ? "unknown" : undefined) : undefined;
    return { scopeDeletionState, revision, captureObservation, observe, guardFolder, guardMovedItem, guardItems, isDeleting, getDeletionState, notify, begin, captureAttempts, isCurrentIdentity, finish, uncertain, reconcile, mergeFiles };
}
export type FolderDeletionController = ReturnType<typeof useFolderDeletion>;
