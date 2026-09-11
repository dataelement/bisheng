import { Segmented } from "@bisheng/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { MessageItem, MessageReadState } from "~/api/message";
import { getMessageListApi, markAllMessageReadApi, markMessageReadApi } from "~/api/message";
import { NotificationSeverity } from "~/common";
import { ExpandableSearchField } from "~/components/ui/ExpandableSearchField";
import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";
import { NotificationRow, type ApprovalCenterTarget } from "./NotificationRow";

const PAGE_SIZE = 20;

function resolveMessageTimeLocale(lang: string) {
  if (lang.startsWith("zh")) return "zh-CN";
  if (lang.startsWith("ja")) return "ja-JP";
  return "en-US";
}

export interface NotificationPaneProps {
  /** Whether the hosting dialog is open — drives the initial load. */
  open: boolean;
  onOpenApprovalCenter: (target: ApprovalCenterTarget) => void;
  /** Fired after any read-state change so the shell can refresh its badge. */
  onUnreadMaybeChanged?: () => void;
}

/**
 * The 通知 section of the 消息与审批 dialog.
 *
 * One mixed list — read and unread rows live together (unread carries the red dot).
 * Read state is authoritative on the server; marking read flips the row in place, it is
 * never hidden client-side. Approval to-dos are excluded by the backend's `notify` tab,
 * so a pending approval only ever appears under 我的审批-待我处理.
 */
export function NotificationPane({ open, onOpenApprovalCenter, onUnreadMaybeChanged }: NotificationPaneProps) {
  const localize = useLocalize();
  const { i18n } = useTranslation();
  const { showToast } = useToastContext();

  // 所有 / 未读 filter — 所有 is the mixed list (unread carries the red dot),
  // 未读 narrows to what still needs a look. Both keep the 全部已读 action.
  const [readState, setReadState] = useState<Extract<MessageReadState, "all" | "unread">>("all");
  const [notifications, setNotifications] = useState<MessageItem[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [markingAll, setMarkingAll] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  const formatTime = (createdAt: string) =>
    new Date(createdAt).toLocaleString(resolveMessageTimeLocale(i18n.language), {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });

  const load = useCallback(
    async (nextPage: number, append: boolean) => {
      if (!append) setLoading(true);
      try {
        const { data, total } = await getMessageListApi({
          tab: "notify",
          read_state: readState,
          keyword: searchQuery || undefined,
          page: nextPage,
          page_size: PAGE_SIZE,
        });
        setNotifications((prev) => (append ? [...prev, ...data] : data));
        setHasMore(nextPage * PAGE_SIZE < total);
        setPage(nextPage);
      } catch (error) {
        console.error("Failed to load notifications:", error);
        if (!append) setNotifications([]);
      } finally {
        if (!append) setLoading(false);
      }
    },
    [searchQuery, readState],
  );

  useEffect(() => {
    if (!open) return;
    setHasMore(true);
    void load(1, false);
  }, [open, load]);

  const handleScroll = (el: HTMLDivElement) => {
    if (loadingMore || loading || !hasMore) return;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 80) {
      setLoadingMore(true);
      void load(page + 1, true).finally(() => setLoadingMore(false));
    }
  };

  /** Read state is authoritative on the server: only drop the row once the call succeeds. */
  const handleMarkRead = async (id: number) => {
    try {
      await markMessageReadApi([id]);
      // 所有: flip the row in place; 未读: the row no longer belongs to the filter.
      setNotifications((prev) =>
        readState === "unread"
          ? prev.filter((n) => Number(n.id) !== id)
          : prev.map((n) => (Number(n.id) === id ? { ...n, is_read: true } : n)),
      );
      onUnreadMaybeChanged?.();
    } catch {
      showToast({ message: localize("com_notifications_toast_operation_failed"), severity: NotificationSeverity.INFO });
    }
  };

  const handleMarkAllRead = async () => {
    setMarkingAll(true);
    try {
      await markAllMessageReadApi();
      showToast({ message: localize("com_notifications_toast_all_read"), severity: NotificationSeverity.SUCCESS });
      onUnreadMaybeChanged?.();
      await load(1, false);
    } catch {
      showToast({ message: localize("com_notifications_toast_operation_failed"), severity: NotificationSeverity.INFO });
    } finally {
      setMarkingAll(false);
    }
  };

  const hasUnread = notifications.some((n) => !n.is_read);

  return (
    // Layout (padding + centered 720px column) is owned by SettingsPage so the pane
    // reads as one block, same as the 账号信息 / 通用 sections.
    <div className="flex min-h-0 flex-1 flex-col bg-white">
      <div className="flex w-full items-center gap-3 pb-4">
        {/* 所有 / 未读 — design-system Segmented (medium = 32px, matching the
            search field and 全部已读 beside it). */}
        <Segmented
          size="medium"
          options={[
            { value: "all", label: localize("com_ui_all_proper") },
            { value: "unread", label: localize("com_notifications_tab_unread") },
          ]}
          value={readState}
          onChange={(next) => setReadState(next as typeof readState)}
          // Extra 108px on top of the row's gap-3 — 120px total against the search field.
          className="mr-[108px]"
        />
        <ExpandableSearchField
          alwaysExpanded
          showClearButton
          value={searchQuery}
          onChange={setSearchQuery}
          placeholder={localize("com_notifications_search_placeholder")}
          expandedWidthClassName="w-full"
          // The field root is shrink-0 by default; let it flex so the 全部已读 button
          // beside it keeps its place instead of being pushed out of the row.
          containerClassName="min-w-0 flex-1 shrink"
        />
        {/* 全部已读 clears notification read state only — it never touches approval tasks. */}
        <button
          type="button"
          disabled={markingAll || !hasUnread}
          onClick={handleMarkAllRead}
          className="h-8 shrink-0 rounded-md border border-transparent bg-fill-1 px-3 text-[14px] font-normal leading-none text-text-2 transition-colors hover:bg-[#f0f0f0] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {localize("com_notifications_mark_all_read")}
        </button>
      </div>

      <div
        ref={listRef}
        className="scrollbar-os -mx-3 min-h-0 flex-1 overflow-y-auto pb-3"
        onScroll={(e) => handleScroll(e.currentTarget)}
      >
        {loading ? (
          <div className="flex h-full items-center justify-center text-[14px] text-text-3">
            {localize("com_notifications_loading")}
          </div>
        ) : notifications.length === 0 ? (
          <div className="flex h-full items-center justify-center text-[14px] text-text-3">
            {localize("com_notifications_empty")}
          </div>
        ) : (
          <>
            <div className="flex flex-col gap-2">
              {notifications.map((notification) => (
                <NotificationRow
                  key={notification.id}
                  notification={notification}
                  formatTime={formatTime}
                  onOpenApprovalCenter={onOpenApprovalCenter}
                  onMarkRead={handleMarkRead}
                />
              ))}
            </div>
            {loadingMore && (
              <div className="py-3 text-center text-[12px] text-text-3">{localize("com_notifications_loading")}</div>
            )}
            {!hasMore && <div className="py-3 text-center text-[12px] text-text-4">{localize("com_notifications_no_more")}</div>}
          </>
        )}
      </div>
    </div>
  );
}
