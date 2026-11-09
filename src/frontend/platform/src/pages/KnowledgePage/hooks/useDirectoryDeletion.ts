import { useState } from "react";
import type { KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";
import { getMyResourcePermissionsApi } from "@/controllers/API/permission";
import { showApiError } from "@/controllers/request";
import { useKnowledgeDeletion } from "./useKnowledgeDeletion";
interface DirectoryDeletionOptions {
  spaceId: number;
  epoch: object;
  scopeKey: string;
  rows: KnowledgeSpaceChild[];
  isCurrent: () => boolean;
  onDeleted: () => Promise<void>;
}
const rowKey = (item: KnowledgeSpaceChild) => `${item.file_type}:${item.id}`;
const selections = (items: KnowledgeSpaceChild[]) =>
  items.map((item) => ({
    id: item.id,
    type: item.file_type === 0 ? ("folder" as const) : ("file" as const),
  }));
export function useDirectoryDeletion({
  spaceId,
  epoch,
  scopeKey,
  rows,
  isCurrent,
  onDeleted,
}: DirectoryDeletionOptions) {
  const [selection, setSelection] = useState<{ epoch: object; keys: string[] }>({
    epoch,
    keys: [],
  });
  const [selectionError, setSelectionError] = useState<object | null>(null);
  const selectedKeys = selection.epoch === epoch ? selection.keys : [];
  const handleSelection = async (item: KnowledgeSpaceChild, checked: boolean) => {
    if (!checked) {
      setSelection((value) => ({
        epoch,
        keys: value.epoch === epoch ? value.keys.filter((key) => key !== rowKey(item)) : [],
      }));
      return;
    }
    try {
      const result = await getMyResourcePermissionsApi(
        item.file_type === 0 ? "folder" : "knowledge_file",
        String(item.id),
      );
      if (!isCurrent()) return;
      if (!result.actions.includes("delete")) {
        setSelectionError(epoch);
        return;
      }
      setSelectionError(null);
      setSelection((value) => ({
        epoch,
        keys: [...new Set([...(value.epoch === epoch ? value.keys : []), rowKey(item)])],
      }));
    } catch (error) {
      if (isCurrent()) showApiError(error);
    }
  };
  const selectedRows = rows.filter((item) => selectedKeys.includes(rowKey(item)));
  const deletion = useKnowledgeDeletion(JSON.stringify([scopeKey, selectedKeys]));
  const remove = async (items: KnowledgeSpaceChild[]) => {
    const success = await deletion.open({ spaceId, kind: "files", items: selections(items) });
    if (success && isCurrent()) {
      setSelection({ epoch, keys: [] });
      await onDeleted();
    }
  };
  const references = (items: KnowledgeSpaceChild[]) => {
    void deletion.open({ spaceId, kind: "files", items: selections(items) }, true);
  };
  return {
    deletion,
    selectedKeys,
    selectedRows,
    selectionError,
    handleSelection,
    remove,
    references,
  };
}
