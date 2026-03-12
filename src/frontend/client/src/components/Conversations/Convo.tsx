import { Check, X } from "lucide-react";
import LingsiIcon from '~/components/ui/icon/Lingsi';
import TodayItemIcon from '~/components/ui/icon/TodayItem';
import type { FocusEvent, KeyboardEvent, MouseEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useRecoilValue } from "recoil";
import { NotificationSeverity } from "~/common";
import {
  useGetEndpointsQuery,
  useUpdateConversationMutation,
} from "~/data-provider";
import type { TConversation } from "~/data-provider/data-provider/src";
import { Constants } from "~/data-provider/data-provider/src";
import { useLocalize, useMediaQuery, useNavigateToConvo } from "~/hooks";
import { useToastContext } from "~/Providers";
import store from "~/store";
import { cn } from "~/utils";
import { ConvoOptions } from "./ConvoOptions";

type KeyEvent = KeyboardEvent<HTMLInputElement>;

type ConversationProps = {
  conversation: TConversation;
  retainView: () => void;
  toggleNav: () => void;
  isLatestConvo: boolean;
};

export default function Conversation({
  conversation,
  retainView,
  toggleNav,
  isLatestConvo,
}: ConversationProps) {
  const params = useParams();

  const currentConvoId = useMemo(
    () => params.conversationId,
    [params.conversationId]
  );
  const updateConvoMutation = useUpdateConversationMutation(
    currentConvoId ?? ""
  );
  const activeConvos = useRecoilValue(store.allConversationsSelector);
  const { data: endpointsConfig } = useGetEndpointsQuery();
  const { navigateWithLastTools } = useNavigateToConvo();
  const { showToast } = useToastContext();
  const { conversationId, title } = conversation;
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [titleInput, setTitleInput] = useState(title);
  const [renaming, setRenaming] = useState(false);
  const [isPopoverActive, setIsPopoverActive] = useState(false);
  const isSmallScreen = useMediaQuery("(max-width: 768px)");
  const localize = useLocalize();
  const navigate = useNavigate();

  const clickHandler = async (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.button === 0 && (event.ctrlKey || event.metaKey)) {
      toggleNav();
      return;
    }

    event.preventDefault();

    if (currentConvoId === conversationId || isPopoverActive) {
      return;
    }

    toggleNav();

    // set document title
    if (typeof title === "string" && title.length > 0) {
      // document.title = title;
    }

    /* Note: Latest Message should not be reset if existing convo */
    navigateWithLastTools(
      conversation,
      !(conversationId ?? "") || conversationId === Constants.NEW_CONVO
    );
  };

  const renameHandler = useCallback(() => {
    setIsPopoverActive(false);
    setTitleInput(title);
    setRenaming(true);
  }, [title]);

  useEffect(() => {
    if (renaming && inputRef.current) {
      inputRef.current.focus();
    }
  }, [renaming]);

  const onRename = useCallback(
    (
      e: MouseEvent<HTMLButtonElement> | FocusEvent<HTMLInputElement> | KeyEvent
    ) => {
      e.preventDefault();
      setRenaming(false);
      if (titleInput === title) {
        return;
      }
      if (typeof conversationId !== "string" || conversationId === "") {
        return;
      }

      updateConvoMutation.mutate(
        {
          conversationId,
          title: titleInput ?? "",
          flowId: conversation.flowId,
          flowType: conversation.flowType,
        },
        {
          onError: () => {
            setTitleInput(title);
            showToast({
              message: "Failed to rename conversation",
              severity: NotificationSeverity.ERROR,
              showIcon: true,
            });
          },
        }
      );
    },
    [
      title,
      titleInput,
      conversationId,
      showToast,
      conversation,
      updateConvoMutation,
    ]
  );

  const handleKeyDown = useCallback(
    (e: KeyEvent) => {
      if (e.key === "Escape") {
        setTitleInput(title);
        setRenaming(false);
      } else if (e.key === "Enter") {
        onRename(e);
      }
    },
    [title, onRename]
  );

  const cancelRename = useCallback(
    (e: MouseEvent<HTMLButtonElement>) => {
      e.preventDefault();
      setTitleInput(title);
      setRenaming(false);
    },
    [title]
  );

  const isActiveConvo: boolean = useMemo(
    () =>
      currentConvoId === conversationId ||
      (isLatestConvo &&
        currentConvoId === "new" &&
        activeConvos[0] != null &&
        activeConvos[0] !== "new"),
    [currentConvoId, conversationId, isLatestConvo, activeConvos]
  );

  return (
    <div
      className={cn(
        "group relative w-full content-stretch flex gap-[8px] items-center mb-1 px-[12px] py-[6px] rounded-lg shrink-0 transition-colors",
        isActiveConvo ? "bg-[#e6edfc]" : "hover:bg-[#f7f7f7]",
        renaming ? "bg-[#e6edfc]" : "",
        isSmallScreen ? "py-[8px]" : ""
      )}
    >
      {renaming ? (
        <div className="flex h-6 grow cursor-pointer items-center gap-[8px] overflow-hidden whitespace-nowrap break-all">
          <input
            ref={inputRef}
            type="text"
            className="w-full rounded bg-white px-1 text-[14px] leading-tight focus-visible:outline-none text-[#212121]"
            value={titleInput ?? ""}
            onChange={(e) => setTitleInput(e.target.value)}
            onKeyDown={handleKeyDown}
            aria-label={`${localize("com_ui_rename")} ${localize(
              "com_ui_chat"
            )}`}
          />
          <div className="flex gap-1">
            <button
              onClick={cancelRename}
              aria-label={`${localize("com_ui_cancel")} ${localize(
                "com_ui_rename"
              )}`}
            >
              <X
                aria-hidden={true}
                className="h-4 w-4 transition-colors duration-200 ease-in-out hover:opacity-70"
              />
            </button>
            <button
              onClick={onRename}
              aria-label={`${localize("com_ui_submit")} ${localize(
                "com_ui_rename"
              )}`}
            >
              <Check
                aria-hidden={true}
                className="h-4 w-4 transition-colors duration-200 ease-in-out hover:opacity-70"
              />
            </button>
          </div>
        </div>
      ) : (
        <a
          // 切换会话
          // href={`/c/${conversationId}`}
          data-testid="convo-item"
          onClick={clickHandler}
          className={cn(
            "flex grow cursor-pointer items-center gap-[8px] overflow-hidden whitespace-nowrap break-all"
          )}
          title={title ?? ""}
        >
          {/* <EndpointIcon
            conversation={conversation}
            endpointsConfig={endpointsConfig}
            size={20}
            context="menu-item"
          /> */}
          <div
            className="relative flex items-center gap-[8px] flex-1 grow overflow-hidden"
            onDoubleClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setTitleInput(title);
              setRenaming(true);
            }}
            alt={conversation?.flowType}
          >
            {conversation?.flowType === 20 ? (
              <LingsiIcon className="size-[24px] shrink-0" />
            ) : (
              <TodayItemIcon className="size-[24px] shrink-0 text-[#6B778D]" />
            )}
            <span className="text-[#212121] text-[14px] leading-[20px] font-['PingFang_SC:Regular',sans-serif] truncate">
              {title}
            </span>
          </div>
        </a>
      )}
      <div
        className={cn(
          isPopoverActive || isActiveConvo
            ? "flex"
            : "hidden group-focus-within:flex group-hover:flex"
        )}
      >
        {!renaming && (
          <ConvoOptions
            title={title}
            retainView={retainView}
            renameHandler={renameHandler}
            isActiveConvo={isActiveConvo}
            conversationId={conversationId}
            isPopoverActive={isPopoverActive}
            setIsPopoverActive={setIsPopoverActive}
          />
        )}
      </div>
    </div>
  );
}
