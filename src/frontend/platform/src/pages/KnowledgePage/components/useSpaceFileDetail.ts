import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { knowledgeFilesApi } from "@/controllers/API/knowledgeFiles";
import {
  readFileMetadata,
  readFilePartitions,
  readVersionChunks,
  updateVersionChunk,
  deleteVersionChunk,
  type SpaceChunk,
} from "@/controllers/API/knowledgeIndex";
import { getMyResourcePermissionsApi } from "@/controllers/API/permission";
import { readProcessingTarget } from "@/controllers/API/knowledgeProcessing";
import { knowledgeQueryKeys, type KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import useKnowledgeStore from "../useKnowledgeStore";

export function useSpaceFileDetail(scope: KnowledgeQueryScope, spaceId: number, fileId: number) {
  const instance = useId();
  const prefix = [...knowledgeQueryKeys.space(scope, spaceId), "file-detail", fileId, instance];
  const [page, setPage] = useState(1);
  const [keyword, setKeyword] = useState("");
  const [busy, setBusy] = useState(false);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [failedWrite, setFailedWrite] = useState<{ run: () => Promise<unknown> } | null>(null);
  const locked = useRef(false);
  const alive = useRef(true);
  const selectedChunkIndex = useKnowledgeStore((state) => state.selectedChunkIndex);
  useEffect(() => { useKnowledgeStore.getState().setSelectedBbox([]); }, [selectedChunkIndex]);
  const preview = useQuery({
    queryKey: [...prefix, "preview"],
    queryFn: () => knowledgeFilesApi.getSpaceFilePreview(spaceId, fileId),
    cacheTime: 0,
    retry: false,
  });
  const canRead = preview.isSuccess;
  const info = useQuery({
    queryKey: [...prefix, "info"],
    queryFn: () => readFileMetadata(fileId),
    enabled: canRead,
    cacheTime: 0,
    retry: false,
  });
  const chunks = useQuery({
    queryKey: [...prefix, "chunks", page, keyword],
    queryFn: () => readVersionChunks(spaceId, fileId, page, keyword),
    enabled: canRead,
    cacheTime: 0,
    retry: false,
  });
  const boxes = useQuery({
    queryKey: [...prefix, "boxes"],
    queryFn: () => readFilePartitions(fileId),
    enabled: canRead,
    cacheTime: 0,
    retry: false,
  });
  const permissions = useQuery({
    queryKey: [...prefix, "actions"],
    queryFn: () => getMyResourcePermissionsApi("knowledge_space", String(spaceId)),
    enabled: canRead,
    cacheTime: 0,
    retry: false,
  });
  useEffect(() => {
    if (!chunks.data) return;
    setDrafts((previous) => {
      const pending = Object.entries(previous).filter(
        ([index, text]) =>
          chunks.data.data.find((row) => row.metadata.chunk_index === Number(index))?.text !== text,
      );
      return pending.length === Object.keys(previous).length ? previous : Object.fromEntries(pending);
    });
  }, [chunks.data]);
  const hasEdit = permissions.isSuccess && permissions.data.actions.includes("edit");
  const target = useQuery({
    queryKey: [...prefix, "target"],
    queryFn: () => readProcessingTarget(spaceId, fileId),
    enabled: hasEdit,
    cacheTime: 0,
    retry: false,
  });
  const canEdit = hasEdit && target.data?.file_id === fileId && !target.isError;
  useEffect(() => {
    alive.current = true;
    const store = useKnowledgeStore.getState();
    store.setSelectedChunkIndex(-1);
    store.setSelectedBbox([]);
    store.setNeedCoverData({ index: -1, txt: "" });
    return () => {
      alive.current = false;
      const current = useKnowledgeStore.getState();
      current.setSelectedChunkIndex(-1);
      current.setSelectedBbox([]);
      current.setNeedCoverData({ index: -1, txt: "" });
    };
  }, []);
  const error =
    preview.error || info.error || chunks.error || boxes.error || permissions.error || target.error;
  useEffect(() => {
    if (error) showApiError(error);
  }, [error]);
  const handleWrite = async (operation: () => Promise<unknown>) => {
    if (!alive.current || locked.current || !canEdit) return;
    locked.current = true;
    setBusy(true);
    try {
      await operation();
      if (!alive.current) return;
      setFailedWrite(null);
      const result = await chunks.refetch();
      if (alive.current && page > 1 && result.data && !result.data.data.length)
        setPage((value) => Math.max(1, value - 1));
    } catch (failure) {
      if (alive.current) {
        setFailedWrite({ run: operation });
        showApiError(failure);
      }
    } finally {
      locked.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const handleChange = (index: number, text: string) => {
    const chunk = chunks.data?.data.find((row) => row.metadata.chunk_index === index);
    if (!chunk || !text.trim() || !canEdit || locked.current || !alive.current) return;
    setDrafts((value) => ({ ...value, [index]: text }));
    const selection = useKnowledgeStore.getState();
    const selected = selection.selectedChunkIndex === index ? selection.selectedBbox : [];
    const updated: SpaceChunk = selected.length
      ? { ...chunk, metadata: { ...chunk.metadata, bbox: JSON.stringify({ chunk_bboxes: selected }) } }
      : chunk;
    return handleWrite(() => updateVersionChunk(spaceId, fileId, updated, text));
  };
  const handleDelete = (index: number) => {
    const chunk = chunks.data?.data.find((row) => row.metadata.chunk_index === index);
    if (chunk && canEdit) return handleWrite(() => deleteVersionChunk(spaceId, fileId, chunk));
  };
  return {
    preview,
    info,
    chunks,
    boxes,
    target,
    canEdit,
    page,
    setPage,
    keyword,
    busy,
    drafts,
    failed: Boolean(failedWrite),
    retryWrite: () => (failedWrite ? handleWrite(failedWrite.run) : undefined),
    setKeyword: (value: string) => {
      setPage(1);
      setKeyword(value);
    },
    handleChange,
    handleDelete,
  };
}
