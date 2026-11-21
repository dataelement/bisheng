import { useContext, useEffect, useMemo, useRef, useState } from "react";
import type { KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { locationContext } from "@/contexts/locationContext";
import { SpaceVersionHistorySheet } from "./SpaceVersionHistorySheet";

interface DirectoryVersionHistoryOptions {
  epoch: object;
  scope: KnowledgeQueryScope;
  spaceId: number;
  parentId: number | null;
  rows: readonly KnowledgeSpaceChild[];
  rowsUpdatedAt: number;
}

interface HistoryOpening {
  identity: object;
  epoch: object;
  selectedFileId: number;
  anchorFileId: number;
  trackedRow?: KnowledgeSpaceChild;
  refreshAfter?: object;
}

function sameHistoryRow(row: KnowledgeSpaceChild, previous: KnowledgeSpaceChild): boolean {
  return row.id === previous.id && row.file_type === 1 && row.knowledge_id === previous.knowledge_id &&
    row.is_multi_version === previous.is_multi_version && row.has_similar === previous.has_similar &&
    (row.status === 2) === (previous.status === 2);
}

export function useDirectoryVersionHistory({ epoch, scope, spaceId, parentId, rows, rowsUpdatedAt }: DirectoryVersionHistoryOptions) {
  const { appConfig } = useContext(locationContext);
  const enabled = appConfig.versionManagementEnabled === true;
  const historyEpoch = useMemo(() => ({ epoch, enabled }), [epoch, enabled]);
  const revision = useMemo(() => ({ rows, rowsUpdatedAt }), [rows, rowsUpdatedAt]);
  const currentRevision = useRef(revision);
  currentRevision.current = revision;
  const [opening, setOpening] = useState<HistoryOpening | null>(null);
  const trackedRow = opening?.trackedRow;
  const active = opening?.epoch === historyEpoch &&
    (!trackedRow || rows.some(row => sameHistoryRow(row, trackedRow)))
    ? opening : null;

  useEffect(() => {
    if (!opening) return;
    if (!active) {
      setOpening(current => current === opening ? null : current);
      return;
    }
    if (active.trackedRow || active.refreshAfter === revision) return;
    const anchor = rows.find(row => row.id === active.anchorFileId && row.file_type === 1 && row.knowledge_id === spaceId);
    if (anchor) setOpening(current => current === active ? { ...current, trackedRow: anchor } : current);
  }, [opening, active, revision, rows, spaceId]);

  const open = (item: KnowledgeSpaceChild) => {
    if (!enabled || item.knowledge_id !== spaceId || item.file_type !== 1 || item.is_multi_version !== true ||
        !rows.some(row => sameHistoryRow(row, item))) return;
    setOpening({ identity: {}, epoch: historyEpoch, selectedFileId: item.id, anchorFileId: item.id, trackedRow: item });
  };

  const overlay = active && (
    <SpaceVersionHistorySheet
      open
      scope={scope}
      spaceId={spaceId}
      parentId={parentId}
      fileId={active.selectedFileId}
      onOpenChange={next => { if (!next) setOpening(current => current?.identity === active.identity ? null : current); }}
      onChanged={anchorFileId => {
        // A committed history mutation may change the directory's physical row or its version badge.
        // Track the replacement only after refresh, even if the current filter omits it.
        setOpening(current => current?.identity === active.identity ? {
          ...current,
          anchorFileId: anchorFileId ?? current.anchorFileId,
          trackedRow: undefined,
          refreshAfter: currentRevision.current,
        } : current);
      }}
    />
  );
  return { open, overlay };
}
