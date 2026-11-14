import type { UseKnowledgeFilePermissionsOptions } from "./knowledgeSpaceTypes";
import { useState, useRef, useEffect, useCallback } from "react";
import { FileType, KnowledgeFile } from "~/api/knowledge";
import { getMyResourcePermissions } from "~/api/permission";
export function useKnowledgeFilePermissions({
  displayFiles,
  space,
  currentFolderId,
}: UseKnowledgeFilePermissionsOptions) {
  const [moveEntryIds, setMoveEntryIds] = useState<Set<string>>(new Set());
  const [canCreateFolder, setCanCreateFolder] = useState(false);
  const [canUploadFile, setCanUploadFile] = useState(false);
  // The current target must accept uploaded content. Each source is checked
  // against the concrete move action again by the business endpoint.
  const [canMoveFile, setCanMoveFile] = useState(false);
  const [canMoveFolder, setCanMoveFolder] = useState(false);
  const [permissionEntryIds, setPermissionEntryIds] = useState<Set<string>>(
    new Set(),
  );
  const [renameEntryIds, setRenameEntryIds] = useState<Set<string>>(new Set());
  const [deleteEntryIds, setDeleteEntryIds] = useState<Set<string>>(new Set());
  const [downloadEntryIds, setDownloadEntryIds] = useState<Set<string>>(
    new Set(),
  );
  // File ids whose lazy permission lookup is in flight — the row/card menu shows
  // a loading row instead of the fail-closed item set until it settles.
  const [pendingFileIds, setPendingFileIds] = useState<Set<string>>(new Set());
  const permissionEntryProbeKey = displayFiles
    .filter((file) => !file.isCreating && /^\d+$/.test(String(file.id)))
    .map((file) => `${file.id}:${file.type}`)
    .join("|");
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const objectType = currentFolderId ? "folder" : "knowledge_space";
    const objectId = currentFolderId || space.id;

    // Ask what this user holds here, the way the per-file menu does, instead
    // of asserting each action separately. A per-action probe treats an
    // action the Catalog has switched off as an error, so disabling
    // upload_file made every visit pop "Action upload_file is unavailable
    // for knowledge_space" beside an upload button that was already hidden.
    // A held-actions list just leaves the action out. One request, not two.
    getMyResourcePermissions(objectType, String(objectId), {
      signal: controller.signal,
    })
      .then((summary) => {
        if (cancelled) return;
        const held = new Set(summary?.actions ?? []);
        setCanCreateFolder(held.has("create_folder"));
        const canPlaceInTarget = held.has("upload_file");
        setCanUploadFile(canPlaceInTarget);
        setCanMoveFile(canPlaceInTarget);
        setCanMoveFolder(canPlaceInTarget);
      })
      .catch(() => {
        if (!cancelled) {
          setCanCreateFolder(false);
          setCanUploadFile(false);
          setCanMoveFile(false);
          setCanMoveFolder(false);
        }
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [currentFolderId, space.id]);

  // File actions resolve lazily from one F048 my-permissions summary when the
  // user opens that file's menu. UI state remains fail-closed while loading.
  const checkedFileIdsRef = useRef<Set<string>>(new Set());

  // Drop lazily-cached grants when the listed files / folder change, so a re-opened
  // menu re-checks against the new context (mirrors the old probe-key re-fetch).
  useEffect(() => {
    checkedFileIdsRef.current = new Set();
    setPermissionEntryIds(new Set());
    setMoveEntryIds(new Set());
    setRenameEntryIds(new Set());
    setDownloadEntryIds(new Set());
    setDeleteEntryIds(new Set());
    setPendingFileIds(new Set());
  }, [permissionEntryProbeKey]);

  const ensureFilePermissions = useCallback(async (file: KnowledgeFile) => {
    const id = String(file.id);
    if (file.isCreating || !/^\d+$/.test(id)) return;
    if (checkedFileIdsRef.current.has(id)) return; // already resolved for this file
    checkedFileIdsRef.current.add(id);
    setPendingFileIds((prev) => new Set(prev).add(id));

    const resourceType =
      file.type === FileType.FOLDER ? "folder" : "knowledge_file";
    try {
      const summary = await getMyResourcePermissions(resourceType, file.id);
      const allowed = new Set(summary.actions);
      const grant = (
        action: string,
        setter: (updater: (prev: Set<string>) => Set<string>) => void,
      ) => {
        if (allowed.has(action)) {
          setter((prev) => new Set(prev).add(id));
        }
      };
      grant("manage_permission", setPermissionEntryIds);
      grant("move", setMoveEntryIds);
      grant("rename", setRenameEntryIds);
      grant("download", setDownloadEntryIds);
      grant("delete", setDeleteEntryIds);
    } catch {
      checkedFileIdsRef.current.delete(id);
    } finally {
      setPendingFileIds((prev) => {
        if (!prev.has(id)) return prev;
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  }, []);

  return {
    moveEntryIds,
    canCreateFolder,
    canUploadFile,
    canMoveFile,
    canMoveFolder,
    permissionEntryIds,
    renameEntryIds,
    deleteEntryIds,
    downloadEntryIds,
    pendingFileIds,
    ensureFilePermissions,
  };
}
