/**
 * Settings → Memory (F132, AC-68 / AC-88–90, AC-107).
 *
 * The "my memory" switch only decides whether chats read and write memory; the
 * list below and every action on it stay available while it is off (AC-90).
 * Every call acts on the signed-in user in the current tenant only.
 */
import {
  Button,
  EmptyStateIllustration,
  Modal,
  StateView,
  Switch,
  SystemMaintenanceIllustration,
} from "@bisheng/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import {
  addMemoryItemApi,
  clearMemoryItemsApi,
  deleteMemoryItemApi,
  getMemorySettingApi,
  listMemoryItemsApi,
  memoryErrorMessage,
  updateMemorySettingApi,
  type MemoryItem,
  type MemoryItemInput,
  type MemorySetting,
} from "~/api/memory";
import { groupMemoryItems, memoryDate, memoryGroupLabel } from "~/components/Memory/memoryLabels";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import { useLocalize } from "~/hooks";
import { MemoryDetailView } from "./MemoryDetailView";
import { MemoryItemEditor } from "./MemoryItemEditor";

export const MEMORY_ITEMS_QUERY_KEY = ["memory", "items"] as const;
const SETTING_QUERY_KEY = ["memory", "setting"] as const;

export function MemoryPane() {
  const localize = useLocalize();
  const queryClient = useQueryClient();
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
  const itemsLoading = itemsQuery.isLoading || (itemsQuery.isError && itemsQuery.isFetching);
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

  const openEditor = () => {
    setActionError("");
    setEditorOpen(true);
  };

  // Only adding is by hand; an existing memory is changed by asking the AI on its own view.
  const handleSubmit = async (input: MemoryItemInput) => {
    await addMemoryItemApi(input);
    await refreshItems();
  };

  const found = openedId ? items.find((item) => item.id === openedId) : undefined;
  if (found) lastOpened.current = found;
  // The new version only appears once the list reloads; until then the view stays mounted
  // on the old one, so its state (the "changed · undo" note) survives the switch.
  const opened = found ?? (openedId && replacing ? (lastOpened.current ?? undefined) : undefined);
  const dialogs = (
    <MemoryItemEditor open={editorOpen} onOpenChange={setEditorOpen} onSubmit={handleSubmit} />
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

      <section className="flex flex-col gap-3" aria-busy={itemsLoading}>
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
            <Button size="small" variant="outlined" onClick={openEditor}>
              {localize("memory.add")}
            </Button>
          </div>
        </div>

        {actionError && (
          <p role="alert" className="text-body-sm text-danger">
            {actionError}
          </p>
        )}

        {itemsLoading ? (
          <div role="status" className="flex min-h-[320px] flex-col items-center justify-center gap-4 px-4 text-center text-body text-text-3">
            <LoadingIcon className="size-20 [@media(max-height:479px)]:size-10" />
            <span>{localize("com_list_loading")}</span>
          </div>
        ) : itemsQuery.isError ? (
          <StateView
            size="page"
            image={<SystemMaintenanceIllustration />}
            title={localize("memory.load_failed")}
            action={<Button onClick={() => void itemsQuery.refetch()}>{localize("memory.retry")}</Button>}
          />
        ) : items.length === 0 ? (
          <StateView size="page" image={<EmptyStateIllustration />} title={localize("memory.empty")} />
        ) : (
          // Grouped by type, like Claude's memory page: a quiet heading per group, then one
          // row per memory with its summary and the date it was last saved. Delete lives on
          // the memory's own page.
          <div className="flex flex-col gap-6">
            {groupMemoryItems(items).map((group) => (
              <section key={group.type} aria-labelledby={`memory-group-${group.type}`}>
                <h4 id={`memory-group-${group.type}`} className="mb-1 px-3 text-body-sm font-medium text-text-2">
                  {memoryGroupLabel(group.type, localize)}
                </h4>
                <ul className="flex flex-col divide-y divide-border-base border-y border-border-base">
                  {group.items.map((item) => (
                    <li key={item.id} data-memory-item>
                      <button
                        type="button"
                        className="flex w-full cursor-pointer items-baseline gap-4 rounded-md px-3 py-3 text-left transition-colors hover:bg-fill-1 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-blue-500"
                        onClick={() => {
                          setActionError("");
                          setOpenedId(item.id);
                        }}
                      >
                        <span className="min-w-0 flex-1 truncate text-body text-text-1">{item.content}</span>
                        <span className="shrink-0 text-caption tabular-nums text-text-3">
                          {memoryDate(item.recorded_at)}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
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
