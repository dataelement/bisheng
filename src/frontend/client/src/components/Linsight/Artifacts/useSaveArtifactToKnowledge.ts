/**
 * Save a task deliverable into a knowledge space, reusing the platform's normal
 * staged-upload pipeline (fetch the artifact's bytes → stage → register).
 *
 * WHY A CLIENT-SIDE "(N)" RENAME. The spec wants a same-layer name collision to
 * land as `name(N).ext` with the source deliverable untouched. The backend's own
 * dedup can't do that for us: `POST /{space}/files` marks a colliding upload
 * FAILED and hands the frontend an "overwrite?" decision whose retry path
 * rewrites the PRE-EXISTING row in place (keeping its old name, possibly in a
 * different folder) — the opposite of what we want. So we resolve a free name
 * before uploading and never offer overwrite.
 *
 * The collision domain is the WHOLE SPACE, not the target folder: the backend
 * compares `md5 OR file_name` space-wide, and `KnowledgeFile.md5` holds the
 * upload's uuid object name rather than a content hash, so only the name branch
 * can ever match. Hence the space-wide probe below plus a `repeat` retry as the
 * net for a truncated or permission-denied probe.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
    addFilesApi,
    searchSpaceChildrenApi,
    type KnowledgeFile,
    type UploadFileResponse,
} from '~/api/knowledge';
import { NotificationSeverity } from '~/common';
import { useLocalize } from '~/hooks';
import { useRefreshEffectiveQuota } from '~/hooks/useEffectiveQuota';
import { useStorageQuotaGuard } from '~/hooks/usePersonalStorageQuota';
import {
    buildUploadFailureMessage,
    extractDuplicateFileEntries,
    uploadFilesSequential,
} from '~/pages/knowledge/hooks/useFileUpload';
import type { AddToKnowledgeSelection } from '~/pages/Subscription/Article/AddToKnowledgeModal';
import { useToastContext } from '~/Providers';
import { fetchArtifactBlob, type ArtifactFile } from './artifactUtils';

type Localize = (key: string, options?: Record<string, unknown>) => string;

/** Split a filename into its stem and dot-extension (a dotfile is all stem). */
function splitFileName(fileName: string): { stem: string; ext: string } {
    const dot = fileName.lastIndexOf('.');
    return dot > 0
        ? { stem: fileName.slice(0, dot), ext: fileName.slice(dot) }
        : { stem: fileName, ext: '' };
}

/**
 * First free name in the `name.ext`, `name(1).ext`, `name(2).ext` … series.
 * Falls back to a timestamp suffix past `maxAttempts` rather than looping.
 */
export function resolveUniqueFileName(
    existingNames: Set<string>,
    baseName: string,
    maxAttempts = 100,
): string {
    if (!existingNames.has(baseName)) return baseName;
    const { stem, ext } = splitFileName(baseName);
    for (let n = 1; n <= maxAttempts; n += 1) {
        const candidate = `${stem}(${n})${ext}`;
        if (!existingNames.has(candidate)) return candidate;
    }
    return `${stem}(${Date.now()})${ext}`;
}

/**
 * Names already taken in the target space. Best-effort: the search endpoint
 * needs `view_space` when no `parent_id` is given, and a custom permission
 * template can grant `upload_file` without it — an empty set just defers to the
 * `repeat` retry below.
 */
async function probeExistingNames(spaceId: string, baseName: string): Promise<Set<string>> {
    try {
        const res = await searchSpaceChildrenApi({
            space_id: spaceId,
            keyword: splitFileName(baseName).stem,
            page_size: 100,
        });
        return new Set(res.data.map((item) => item.name));
    } catch {
        return new Set<string>();
    }
}

/** An error whose `message` is already user-facing localized copy. */
type LocalizedError = Error & { localized?: true };

/**
 * Stage one blob under `fileName`. Routed through the shared sequential helper
 * so a rejection carries the same localized `api_errors.<code>` reason the
 * knowledge-space upload UI shows (storage quota, size limit, …).
 */
async function stageUpload(
    spaceId: string,
    blob: Blob,
    fileName: string,
    localize: Localize,
): Promise<{ filePath: string; repeat: boolean }> {
    let staged: UploadFileResponse | undefined;
    const { failures, earlyStop } = await uploadFilesSequential(
        spaceId,
        [new File([blob], fileName, { type: blob.type })],
        (response) => { staged = response; },
    );
    if (!staged) {
        const error: LocalizedError = new Error(
            buildUploadFailureMessage(failures, earlyStop, localize),
        );
        error.localized = true;
        throw error;
    }
    // uploadFileToServerApi rejects when file_path is absent, so a resolved
    // response always carries it.
    return { filePath: staged.file_path, repeat: Boolean(staged.repeat) };
}

/**
 * Register the staged bytes in the space. Retry the registration ONCE on failure
 * (no re-upload) to recover from transient errors — otherwise a flaky register
 * leaves the bytes as a storage orphan with no record in the space. A duplicate
 * re-register from the retry is caught by the duplicate detection in saveTo.
 */
async function registerStagedFile(
    spaceId: string,
    filePath: string,
    parentId: number | null,
): Promise<KnowledgeFile[]> {
    const register = () => addFilesApi(spaceId, { file_path: [filePath], parent_id: parentId });
    try {
        return await register();
    } catch (firstErr) {
        console.warn('[useSaveArtifactToKnowledge] registration failed, retrying once:', firstErr);
        return await register();
    }
}

export function useSaveArtifactToKnowledge(file: ArtifactFile, versionId: string) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const isStorageBlocked = useStorageQuotaGuard();
    const refreshQuota = useRefreshEffectiveQuota();
    const [pickerOpen, setPickerOpen] = useState(false);
    const [saving, setSaving] = useState(false);
    // A save outlives its button when the surrounding panel closes or the user
    // navigates away — the toast is global and still lands, the setState must not.
    const mountedRef = useRef(true);
    useEffect(() => () => { mountedRef.current = false; }, []);
    // Ref, not the `saving` state: keeps saveTo's identity stable so the picker
    // can't re-render into a stale handler between opening and confirming.
    const savingRef = useRef(false);

    // Deferred a tick because the trigger is a DropdownMenuItem: otherwise Radix
    // treats the same click as an outside-click on the freshly mounted dialog and
    // dismisses it (same fix as ArticleList's menu → source-filter popover).
    const openPicker = useCallback(() => {
        setTimeout(() => setPickerOpen(true), 0);
    }, []);

    const saveTo = useCallback(
        async (selection: AddToKnowledgeSelection) => {
            if (savingRef.current) return;
            const spaceId = selection.knowledgeSpaceId;
            const parentId = selection.folderId ? Number(selection.folderId) : null;
            savingRef.current = true;
            setSaving(true);
            showToast({
                message: localize('com_linsight.saveToKnowledgeSaving'),
                severity: NotificationSeverity.INFO,
            });
            try {
                // Original bytes only — the spec stores the source Markdown, never
                // a pdf/docx conversion.
                const { blob, fileName } = await fetchArtifactBlob(file, versionId);
                // Size is only knowable once fetched, so guard after the fetch.
                // The guard reports the reason itself.
                if (isStorageBlocked(blob.size)) return;

                const taken = await probeExistingNames(spaceId, fileName);
                let candidate = resolveUniqueFileName(taken, fileName);
                let staged = await stageUpload(spaceId, blob, candidate, localize);
                // The probe can come back empty (no view_space) or truncated, so
                // the backend's own `repeat` flag is the authoritative collision
                // check — keep bumping N until it clears. Bounded because each
                // attempt re-stages the bytes.
                for (let attempt = 0; staged.repeat && attempt < 3; attempt += 1) {
                    taken.add(candidate);
                    candidate = resolveUniqueFileName(taken, fileName);
                    staged = await stageUpload(spaceId, blob, candidate, localize);
                }

                const registered = await registerStagedFile(spaceId, staged.filePath, parentId);
                const blocked = new Set(
                    extractDuplicateFileEntries(registered).map((entry) => entry.fileId),
                );
                const saved = registered.find((item) => !blocked.has(item.id));
                if (saved && saved.approvalStatus === 'pending_review') {
                    // The space gates uploads behind an approval workflow — the
                    // file is NOT in the space yet, so this must not read as done.
                    showToast({
                        message: localize('com_linsight.saveToKnowledgePending'),
                        severity: NotificationSeverity.INFO,
                    });
                } else if (saved) {
                    showToast({
                        message: localize('com_linsight.saveToKnowledgeSuccess', { name: saved.name }),
                        severity: NotificationSeverity.SUCCESS,
                    });
                } else {
                    // Every registered row came back a duplicate. The rename loop
                    // should prevent this; it means another writer won the name
                    // between our probe and the register.
                    showToast({
                        message: localize('com_linsight.saveToKnowledgeFailed'),
                        severity: NotificationSeverity.ERROR,
                    });
                }
            } catch (e) {
                console.error('save artifact to knowledge space failed:', e);
                const error = e as LocalizedError;
                showToast({
                    // Only a staging rejection carries localized copy; a failed
                    // artifact fetch would otherwise surface raw English.
                    message: (error?.localized && error.message)
                        || localize('com_linsight.saveToKnowledgeFailed'),
                    severity: NotificationSeverity.ERROR,
                });
            } finally {
                refreshQuota();
                savingRef.current = false;
                if (mountedRef.current) setSaving(false);
            }
        },
        [file, versionId, isStorageBlocked, refreshQuota, showToast, localize],
    );

    return { pickerOpen, setPickerOpen, openPicker, saveTo, saving };
}
