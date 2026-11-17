/**
 * F004 (T060): files of the current run (`file` events in `runStore`) as
 * workspace artifacts, merged with the files the conversation already knows
 * from history (answer-row `files` and task final files).
 *
 * A live file is listed only when a preview / download helper can fetch it:
 *
 * - `output/…` (workspace-relative, sent while the run works): the link comes
 *   from `GET /workstation/conversations/{id}/files/{file_id}/url`, through the
 *   same re-issue path that kept conversation attachments use;
 * - `linsight/final_result/{svid}/…` or `linsight/session_files/{svid}/…` (an
 *   object key owned by a task turn): `/linsight/workbench/file_download`.
 *
 * Any other `path` cannot be fetched, so the file is not listed.
 */
import { useMemo } from 'react';
import { getRunFileUrlPath } from '~/api/runApi';
import { useGetBsConfig } from '~/hooks/queries/data-provider';
import { useRunStore, type RunFileData } from '~/store/runStore';
import type { ArtifactFile } from './artifactUtils';

const VERSION_OWNED_KEY = /(?:^|\/)(linsight\/(?:final_result|session_files)\/([^/]+)\/.+)$/;

function decodeSafe(value: string): string {
    try {
        return decodeURIComponent(value);
    } catch {
        return value;
    }
}

function normalizePath(value: string | undefined): string {
    return decodeSafe(value || '')
        .replace(/\\/g, '/')
        .split(/[?#]/)[0]
        .replace(/^\/+/, '');
}

/** Map one `file` event to a workspace artifact, or null when it cannot be fetched yet. */
export function toLiveArtifact(
    file: RunFileData | null | undefined,
    conversationId?: string,
): ArtifactFile | null {
    if (!file?.file_id || !file.path) return null;
    const path = normalizePath(file.path);
    const name = file.name || path.split('/').pop() || '';
    if (!name) return null;
    const owned = VERSION_OWNED_KEY.exec(path);
    if (!owned) {
        if (!conversationId || !path.startsWith('output/')) return null;
        // `directUrl` marks the file as "not resolved against a task turn"; the
        // link itself is issued on every open through `attachment`.
        return {
            file_id: file.file_id,
            file_name: name,
            file_url: path,
            source: 'output',
            directUrl: getRunFileUrlPath(conversationId, file.file_id),
            attachment: { conversationId, fileId: file.file_id, run: true },
        };
    }
    // `versionId` makes preview / download resolve against the turn that owns the key.
    return { file_id: file.file_id, file_name: name, file_url: owned[1], source: 'output', versionId: owned[2] };
}

function pathKeys(file: ArtifactFile): string[] {
    const direct = file.attachment?.run ? undefined : file.directUrl;
    return [file.file_url, file.file_path, direct].map(normalizePath).filter(Boolean);
}

/**
 * The live files that `known` does not have yet. A live file is the same file as
 * a known one when the ids match, else when the paths match; the known entry
 * wins because it carries the stored address.
 */
export function newLiveArtifacts(
    known: ArtifactFile[],
    live: RunFileData[] | null | undefined,
    conversationId?: string,
): ArtifactFile[] {
    if (!live?.length) return NO_ARTIFACTS;
    const ids = new Set(known.map((f) => f.file_id).filter(Boolean));
    const paths = new Set(known.flatMap(pathKeys));
    const added: ArtifactFile[] = [];
    for (const event of live) {
        const file = toLiveArtifact(event, conversationId);
        if (!file || ids.has(file.file_id)) continue;
        const keys = pathKeys(file);
        if (keys.some((key) => paths.has(key))) continue;
        ids.add(file.file_id);
        keys.forEach((key) => paths.add(key));
        added.push(file);
    }
    return added.length ? added : NO_ARTIFACTS;
}

/** History files first, then the live files history does not have yet. */
export function mergeWorkspaceFiles(
    known: ArtifactFile[],
    live: RunFileData[] | null | undefined,
    conversationId?: string,
): ArtifactFile[] {
    const added = newLiveArtifacts(known, live, conversationId);
    return added.length ? [...known, ...added] : known;
}

const NO_ARTIFACTS: ArtifactFile[] = [];
const NO_FILES: RunFileData[] = [];

/**
 * Files of the conversation's current run. Always empty when the tenant switch
 * `unified_runtime_enabled` is off or missing, so nothing changes on the old path.
 */
export function useLiveRunFiles(conversationId: string | undefined): RunFileData[] {
    const enabled = useGetBsConfig().data?.unified_runtime_enabled === true;
    return useRunStore((state) => {
        if (!enabled || !conversationId) return NO_FILES;
        return state.conversations[conversationId]?.run?.files ?? NO_FILES;
    });
}

/**
 * Files of the conversation's current run that `known` does not have yet.
 * Keeps the same array while nothing changed, so memoized consumers stay put.
 */
export function useNewLiveArtifacts(known: ArtifactFile[], conversationId: string | undefined): ArtifactFile[] {
    const live = useLiveRunFiles(conversationId);
    return useMemo(() => newLiveArtifacts(known, live, conversationId), [known, live, conversationId]);
}
