import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { MessageItem, MessageReadState } from "~/api/message";
import { deleteMessageApi, getMessageListApi, markAllMessageReadApi, markMessageReadApi } from "~/api/message";
import { NotificationSeverity } from "~/common";
import { ExpandableSearchField } from "~/components/ui/ExpandableSearchField";
import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";
import { cn } from "~/utils";
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
 * 未读消息 / 已读消息 are server-side lists (the backend filters by this user's read records) —
 * we never hide rows client-side to fake a state change. Approval to-dos are excluded by the
 * backend's `notify` tab, so a pending approval only ever appears under 我的审批-待我处理.
 */
export function NotificationPane({ open, onOpenApprovalCenter, onUnreadMaybeChanged }: NotificationPaneProps) {
  const localize = useLocalize();
  const { i18n } = useTranslation();
  const { showToast } = useToastContext();

  const [readState, setReadState] = useState<MessageReadState>("unread");
  const [notifications, setNotifications] = useState<MessageItem[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [markingAll, setMarkingAll] = useState(false);
  const [isTouchMobile, setIsTouchMobile] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  const formatTime = (createdAt: string) =>
    new Date(createdAt).toLocaleString(resolveMessageTimeLocale(i18n.language), {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });

  useEffect(() => {
    if (typeof window === "undefined") return;
    const detect = () => {
      const narrowViewport = window.matchMedia("(max-width: 768px)").matches;
      const hoverCapable = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
      const touchCapable = navigator.maxTouchPoints > 0 || window.matchMedia("(pointer: coarse)").matches;
      setIsTouchMobile(narrowViewport && (touchCapable || !hoverCapable));
    };
    detect();
    window.addEventListener("resize", detect);
    return () => window.removeEventListener("resize", detect);
  }, []);

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
    [readState, searchQuery],
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
      setNotifications((prev) => prev.filter((n) => Number(n.id) !== id));
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

  const handleDelete = async (id: number) => {
    try {
      await deleteMessageApi(id);
      setNotifications((prev) => prev.filter((n) => Number(n.id) !== id));
      showToast({ message: localize("com_notifications_toast_deleted"), severity: NotificationSeverity.SUCCESS });
      onUnreadMaybeChanged?.();
    } catch {
      showToast({ message: localize("com_notifications_toast_delete_failed"), severity: NotificationSeverity.INFO });
    }
  };

  const tabs: MessageReadState[] = ["unread", "read"];

  return (
    <div className="flex min-h-0 flex-col bg-white">
      {/* Status tabs mirror 我的审批's 待我处理 / 已处理 structure; the search box sits below them. */}
      <div className="flex gap-2 px-5 pb-2 pt-3">
        {tabs.map((state) => (
          <button
            key={state}
            type="button"
            className={cn(
              "h-auto whitespace-nowrap rounded-none border-0 border-b-2 border-transparent bg-transparent px-2 py-[5px] text-sm leading-none transition-colors fine-pointer:hover:text-text-1",
              readState === state ? "border-[#212121] font-medium text-text-1" : "font-normal text-text-3",
            )}
            onClick={() => setReadState(state)}
          >
            {state === "unread" ? localize("com_notifications_tab_unread") : localize("com_notifications_tab_read")}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-3 px-5 pb-2 pt-1">
        <ExpandableSearchField
          alwaysExpanded
          showClearButton
          value={searchQuery}
          onChange={setSearchQuery}
          placeholder={localize("com_notifications_search_placeholder")}
          expandedWidthClassName="w-full"
        />
        {/* 全部已读 is a list action of 未读消息 only — it never touches approval tasks. */}
        {readState === "unread" && (
          <button
            type="button"
            disabled={markingAll || notifications.length === 0}
            onClick={handleMarkAllRead}
            className="h-8 shrink-0 rounded-md border border-transparent bg-fill-1 px-3 text-[14px] font-normal leading-none text-text-2 transition-colors hover:bg-[#f0f0f0] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {localize("com_notifications_mark_all_read")}
          </button>
        )}
      </div>

      <div
        ref={listRef}
        className="scrollbar-os min-h-0 flex-1 overflow-y-auto px-2 pb-3"
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
            <div className="divide-y divide-border-base">
              {notifications.map((notification) => (
                <NotificationRow
                  key={notification.id}
                  notification={notification}
                  isTouchMobile={isTouchMobile}
                  formatTime={formatTime}
                  onOpenApprovalCenter={onOpenApprovalCenter}
                  onMarkRead={handleMarkRead}
                  onDelete={handleDelete}
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
