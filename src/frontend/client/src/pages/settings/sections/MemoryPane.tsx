/**
 * Settings → Memory (F132, AC-68 / AC-88–90, AC-107).
 *
 * The "my memory" switch only decides whether chats read and write memory; the
 * list below and every action on it stay available while it is off (AC-90).
 * Every call acts on the signed-in user in the current tenant only.
 */
import { Button, Modal, Switch, Tag } from "@bisheng/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { useRef, useState } from "react";
import {
  addMemoryItemApi,
  clearMemoryItemsApi,
  deleteMemoryItemApi,
  editMemoryItemApi,
  getMemorySettingApi,
  listMemoryItemsApi,
  memoryErrorMessage,
  updateMemorySettingApi,
  type MemoryItem,
  type MemoryItemInput,
  type MemorySetting,
} from "~/api/memory";
import { memoryMetaParts, memoryTypeLabel } from "~/components/Memory/memoryLabels";
import { useLocalize } from "~/hooks";
import { MemoryDetailView } from "./MemoryDetailView";
import { MemoryItemEditor } from "./MemoryItemEditor";

export const MEMORY_ITEMS_QUERY_KEY = ["memory", "items"] as const;
const SETTING_QUERY_KEY = ["memory", "setting"] as const;

export function MemoryPane() {
  const localize = useLocalize();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<MemoryItem | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [actionError, setActionError] = useState("");
  /** The memory opened in its own view; null shows the list. */
  const [openedId, setOpenedId] = useState<string | null>(null);
  /** While an opened memory is being replaced by its new version, keep showing the old one. */
  const [replacing, setReplacing] = useState(false);
  const lastOpened = useRef<MemoryItem | null>(null);

  const itemsQuery = useQuery({ queryKey: MEMORY_ITEMS_QUERY_KEY, queryFn: listMemoryItemsApi });
  const settingQuery = useQuery({ queryKey: SETTING_QUERY_KEY, queryFn: getMemorySettingApi });
  const items = itemsQuery.data ?? [];
  // No setting row means on (AC-68 default); the switch shows that until loaded.
  const enabled = settingQuery.data?.enabled ?? true;

  const refreshItems = () => queryClient.invalidateQueries({ queryKey: MEMORY_ITEMS_QUERY_KEY });

  const settingMutation = useMutation({
    mutationFn: updateMemorySettingApi,
    onSuccess: (setting: MemorySetting) => queryClient.setQueryData(SETTING_QUERY_KEY, setting),
    onError: (err) => setActionError(memoryErrorMessage(err, localize("memory.switch_failed"))),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteMemoryItemApi,
    onSuccess: (_result, itemId) => {
      setOpenedId((current) => (current === itemId ? null : current));
      return refreshItems();
    },
    onError: (err) => setActionError(memoryErrorMessage(err, localize("memory.delete_failed"))),
  });

  const clearMutation = useMutation({
    mutationFn: clearMemoryItemsApi,
    onSuccess: () => {
      setConfirmClear(false);
      return refreshItems();
    },
    onError: (err) => {
      setConfirmClear(false);
      setActionError(memoryErrorMessage(err, localize("memory.clear_failed")));
    },
  });

  const openEditor = (item: MemoryItem | null) => {
    setActionError("");
    setEditing(item);
    setEditorOpen(true);
  };

  const handleSubmit = async (input: MemoryItemInput) => {
    if (editing) {
      // An edit replaces the item with a new one: an open view follows it.
      const result = await editMemoryItemApi(editing.id, input);
      setReplacing(true);
      setOpenedId((current) => (current === editing.id ? result.item_id : current));
      try {
        await refreshItems();
      } finally {
        setReplacing(false);
      }
    } else {
      await addMemoryItemApi(input);
      await refreshItems();
    }
  };

  const found = openedId ? items.find((item) => item.id === openedId) : undefined;
  if (found) lastOpened.current = found;
  // The new version only appears once the list reloads; until then the view stays mounted
  // on the old one, so its state (the "changed · undo" note) survives the switch.
  const opened = found ?? (openedId && replacing ? (lastOpened.current ?? undefined) : undefined);
  const dialogs = (
    <MemoryItemEditor open={editorOpen} item={editing} onOpenChange={setEditorOpen} onSubmit={handleSubmit} />
  );

  if (opened) {
    return (
      <>
        {actionError && (
          <p role="alert" className="mb-3 text-body-sm text-danger">
            {actionError}
          </p>
        )}
        <MemoryDetailView
          item={opened}
          onBack={() => setOpenedId(null)}
          onEdit={openEditor}
          onDelete={(item) => {
            setActionError("");
            deleteMutation.mutate(item.id);
          }}
          onReplaced={async (newItemId) => {
            setReplacing(true);
            setOpenedId(newItemId);
            try {
              await refreshItems();
            } finally {
              setReplacing(false);
            }
          }}
        />
        {dialogs}
      </>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <section className="flex items-start justify-between gap-4 rounded-xl border border-border-base px-4 py-3">
        <div className="min-w-0">
          <div id="memory-switch-label" className="text-body font-medium text-text-1">
            {localize("memory.switch_label")}
          </div>
          <p className="mt-0.5 text-body-sm text-text-3">{localize("memory.switch_hint")}</p>
        </div>
        <Switch
          aria-labelledby="memory-switch-label"
          checked={enabled}
          loading={settingMutation.isLoading}
          onCheckedChange={(next) => {
            setActionError("");
            settingMutation.mutate(next);
          }}
        />
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-body font-medium text-text-1">
            {localize("memory.list_title")}
            {items.length > 0 && <span className="ml-1 text-text-3">{items.length}</span>}
          </h3>
          <div className="flex items-center gap-2">
            <Button
              size="small"
              variant="text"
              color="danger"
              disabled={!items.length}
              onClick={() => setConfirmClear(true)}
            >
              {localize("memory.clear")}
            </Button>
            <Button size="small" variant="outlined" onClick={() => openEditor(null)}>
              {localize("memory.add")}
            </Button>
          </div>
        </div>

        {actionError && (
          <p role="alert" className="text-body-sm text-danger">
            {actionError}
          </p>
        )}

        {itemsQuery.isError ? (
          <div className="flex items-center gap-2 py-8 text-body-sm text-text-3">
            {localize("memory.load_failed")}
            <Button size="small" variant="link" onClick={() => itemsQuery.refetch()}>
              {localize("memory.retry")}
            </Button>
          </div>
        ) : itemsQuery.isLoading ? null : items.length === 0 ? (
          <p className="py-8 text-center text-body-sm text-text-3">{localize("memory.empty")}</p>
        ) : (
          <ul className="flex flex-col divide-y divide-border-base rounded-xl border border-border-base">
            {items.map((item) => (
              <li
                key={item.id}
                data-memory-item
                className="group flex items-start gap-3 px-4 py-3 transition-colors hover:bg-fill-1"
              >
                {/* The whole text block opens the memory; the icons on the right stay shortcuts. */}
                <button
                  type="button"
                  className="min-w-0 flex-1 cursor-pointer text-left"
                  onClick={() => {
                    setActionError("");
                    setOpenedId(item.id);
                  }}
                >
                  {/* Spans only: a button holds phrasing content. */}
                  <span className="block whitespace-pre-wrap break-words text-body text-text-1">{item.content}</span>
                  <span className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-caption text-text-3">
                    <Tag size="small">{memoryTypeLabel(item.type, localize)}</Tag>
                    {memoryMetaParts(item, localize).map((part) => (
                      <span key={part}>{part}</span>
                    ))}
                  </span>
                </button>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    size="small"
                    variant="text"
                    color="default"
                    iconOnly
                    aria-label={localize("memory.edit")}
                    title={localize("memory.edit")}
                    onClick={() => openEditor(item)}
                  >
                    <Outlined.Edit />
                  </Button>
                  <Button
                    size="small"
                    variant="text"
                    color="default"
                    iconOnly
                    aria-label={localize("memory.delete")}
                    title={localize("memory.delete")}
                    onClick={() => {
                      setActionError("");
                      deleteMutation.mutate(item.id);
                    }}
                  >
                    <Outlined.Delete />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {dialogs}

      <Modal
        open={confirmClear}
        onOpenChange={setConfirmClear}
        size="small"
        closable={false}
        title={localize("memory.clear_confirm_title")}
        description={localize("memory.clear_confirm_desc")}
        submitting={clearMutation.isLoading}
        footer={
          <>
            <Button variant="outlined" onClick={() => setConfirmClear(false)} disabled={clearMutation.isLoading}>
              {localize("memory.cancel")}
            </Button>
            <Button color="danger" loading={clearMutation.isLoading} onClick={() => clearMutation.mutate()}>
              {localize("memory.clear_confirm_ok")}
            </Button>
          </>
        }
      />
    </div>
  );
}
