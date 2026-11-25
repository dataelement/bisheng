import { readDesktopPresentation } from "~/utils/clientEnvironment";
import { useLayoutEffect, useState } from "react";
import { Outlined } from "bisheng-icons";
import { Button, Checkbox, Modal, SearchInput } from "@bisheng/ui";
import { useLocalize } from "~/hooks";
import { useKnowledgeSpaceAccess } from "~/hooks/useKnowledgeSpaceAccess";
import { useScrollRevealRef } from "~/hooks/useScrollRevealRef";
import type { KnowledgeItem } from "./knowledgeTypes";

export interface KnowledgePickerGroup {
  key: string;
  label?: string;
  items: Array<{
    id: string | number;
    name: string;
  }>;
}

export interface KnowledgePickerSelectionProps {
  value: KnowledgeItem[];
  onConfirm: (value: KnowledgeItem[]) => void;
  onClose: () => void;
}

interface KnowledgePickerDialogProps extends KnowledgePickerSelectionProps {
  keyword: string;
  onKeywordChange: (keyword: string) => void;
  groups: KnowledgePickerGroup[];
  isFetching: boolean;
  isError: boolean;
  onRetry: () => void;
  hasMore?: boolean;
  onLoadMore?: () => void;
}

const MAX_SELECTED = 50;

/** Keep a space draft until confirmation, including across searches. */
export function KnowledgePickerDialog({
  value,
  onConfirm,
  onClose,
  keyword,
  onKeywordChange,
  groups,
  isFetching,
  isError,
  onRetry,
  hasMore,
  onLoadMore,
}: KnowledgePickerDialogProps) {
  const localize = useLocalize();
  const listRef = useScrollRevealRef<HTMLDivElement>();
  useLayoutEffect(() => {
    const presentation = readDesktopPresentation();
    presentation?.reportKnowledgeDialog?.(true);
    return () => presentation?.reportKnowledgeDialog?.(false);
  }, []);
  const [draft, setDraft] = useState(() =>
    value.filter((item) => item.type === "space"),
  );
  const access = useKnowledgeSpaceAccess(draft, "knowledge-picker");
  const accessMessage = access.message || (access.checking ? localize("knowledgeAccess.checking") : "");
  const available = access.available;
  const selectedIds = new Set(available.map((item) => String(item.id)));
  const hasSavedSpaces = value.some((item) => item.type === "space");
  const canConfirm =
    !isError &&
    !isFetching &&
    !access.checking &&
    !access.failed &&
    (available.length > 0 || hasSavedSpaces);
  const searchLabel = localize("dshChat.searchKnowledge");

  const handleToggle = (id: string, name: string) => {
    setDraft((current) => {
      const allowed = current.filter((item) => selectedIds.has(String(item.id)));
      return allowed.some((item) => String(item.id) === id)
        ? allowed.filter((item) => String(item.id) !== id)
        : allowed.length < MAX_SELECTED
          ? [...allowed, { id, name, type: "space" }]
          : allowed;
    });
  };
  const handleConfirm = () => {
    onConfirm([...value.filter((item) => item.type !== "space"), ...available]);
    onClose();
  };

  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={localize("dshChat.selectKnowledge")}
      closeLabel={localize("com_ui_close")}
      className={
        "dsh-knowledge-dialog min-[576px]:px-1 min-[576px]:pt-2 " +
        "min-[576px]:h-[80dvh] min-[576px]:max-h-[min(600px,calc(100dvh-64px))] " +
        "min-[576px]:w-[min(576px,calc(100vw-32px))] lg:w-[min(576px,calc(100vw-32px))]"
      }
      overlayClassName="dsh-knowledge-overlay"
      bodyClassName="flex flex-col gap-4 pt-1.5"
      footerClassName="max-[576px]:flex-wrap min-[576px]:gap-2 min-[576px]:pb-5"
      footer={
        <>
          <span
            className="mr-auto text-body-sm text-text-3 max-[576px]:!basis-full"
            aria-live="polite"
          >
            {localize("dshChat.selectedKnowledge", { count: available.length })}
          </span>
          <Button
            color="default"
            variant="outlined"
            className="min-w-16"
            onClick={onClose}
          >
            {localize("com_ui_cancel")}
          </Button>
          <Button className="min-w-16" onClick={handleConfirm} disabled={!canConfirm}>
            {localize("dshChat.confirmKnowledge")}
          </Button>
        </>
      }
    >
      <SearchInput
        className="shrink-0"
        value={keyword}
        onChange={(event) => onKeywordChange(event.target.value)}
        placeholder={searchLabel}
        aria-label={searchLabel}
        clearLabel={localize("com_ui_clear")}
      />
      <div
        ref={listRef}
        className="scrollbar-on-scroll min-h-0 flex-1 overflow-y-auto overscroll-contain rounded-md border border-border-base p-1 [scrollbar-gutter:stable]"
        aria-busy={isFetching}
        onScroll={(event) => {
          const { scrollHeight, scrollTop, clientHeight } = event.currentTarget;
          if (
            hasMore &&
            !isFetching &&
            scrollHeight - scrollTop <= clientHeight + 16
          )
            onLoadMore?.();
        }}
      >
        {isError ? (
          <div
            role="alert"
            className="flex h-full min-h-24 flex-col items-center justify-center gap-3 py-4 text-text-3"
          >
            <span>{localize("dshChat.knowledgeLoadError")}</span>
            <Button color="default" variant="outlined" onClick={onRetry}>
              {localize("dshChat.retryKnowledge")}
            </Button>
          </div>
        ) : isFetching && groups.length === 0 ? (
          <p role="status" className="grid h-full min-h-24 place-items-center px-2 text-center text-text-3">
            {localize("dshChat.loadingKnowledge")}
          </p>
        ) : groups.length === 0 && !hasMore ? (
          <p role="status" className="grid h-full min-h-24 place-items-center px-2 text-center text-text-3">
            {localize(keyword.trim() ? "dshChat.noKnowledgeMatch" : "dshChat.noKnowledge")}
          </p>
        ) : (
          groups.map((group) => (
            <section key={group.key} className="space-y-1">
              {group.label && (
                <h3 className="mb-2 text-body-sm text-text-3">{group.label}</h3>
              )}
              {group.items
                .filter((item) => item.id != null && String(item.id) !== "")
                .map((item) => {
                  const id = String(item.id);
                  const checked = selectedIds.has(id);
                  return (
                    <label
                      key={id}
                      className="flex min-h-7 cursor-pointer items-center gap-2 rounded-md px-2 hover:bg-fill-1 data-[selected=true]:bg-blue-500/[0.07] coarse-pointer:min-h-11 has-[:disabled]:cursor-not-allowed"
                      data-selected={checked}
                    >
                      <Checkbox
                        checked={checked}
                        disabled={!checked && available.length >= MAX_SELECTED}
                        onCheckedChange={() => handleToggle(id, item.name)}
                        aria-label={item.name}
                      />
                      <Outlined.Notebook size={14} className="shrink-0 text-text-3" aria-hidden />
                      <span
                        className="min-w-0 flex-1 truncate text-text-1"
                        title={item.name}
                      >
                        {item.name}
                      </span>
                    </label>
                  );
                })}
            </section>
          ))
        )}
        {isFetching && groups.length > 0 && (
          <p role="status" className="py-3 text-center text-text-3">
            {localize("dshChat.loadingKnowledge")}
          </p>
        )}
      </div>
      {hasMore && !isError && <Button color="default" variant="outlined" loading={isFetching} onClick={onLoadMore}>
        {localize("dshChat.loadMoreKnowledge")}
      </Button>}
      {accessMessage && <p role="status" className="text-body-sm text-danger">{accessMessage}</p>}
      {available.length >= MAX_SELECTED && (
        <p role="status" className="text-body-sm text-text-3">
          {localize("dshChat.knowledgeLimit")}
        </p>
      )}
    </Modal>
  );
}
