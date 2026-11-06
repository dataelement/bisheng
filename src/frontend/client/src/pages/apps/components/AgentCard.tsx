import {
  Dropdown,
  DropdownItem,
  Tooltip as SharedTooltip,
  TooltipProvider as SharedTooltipProvider,
} from "@bisheng/ui";
import { DemoTag } from "~/mock/demo/DemoTag";
import type { AppItem } from "~/@types/app";
import { Button } from "~/components";
import AppAvator from "~/components/Avator";

import { useLocalize, useMediaQuery } from "~/hooks";
import { cn } from "~/utils";
import { Outlined } from "bisheng-icons";
import { MoreVertical } from "lucide-react";
import { useLazyAppSharePermission } from "../hooks/useLazyAppSharePermission";

interface AgentCardProps {
  agent: AppItem;
  /** Pin is optional — surfaces without a pin concept (e.g. the app square) omit it. */
  isPinned?: boolean;
  onTogglePin?: (agent: AppItem) => void;
  onStartChat: (agent: AppItem) => void;
  onShare: (agent: AppItem) => void;
}

export function AgentCard({ agent, isPinned = false, onTogglePin, onStartChat, onShare }: AgentCardProps) {
  const localize = useLocalize();
  const isMobileCard = useMediaQuery("(max-width: 576px)");
  const canHover = useMediaQuery("(hover: hover) and (pointer: fine)");
  const shouldUseHoverActions = !isMobileCard && canHover;
  const shouldUseHoverActionsInMobileCard = isMobileCard && canHover;
  const { canShare, ensureSharePermission } = useLazyAppSharePermission(agent);
  // Only render pin affordances when a toggle handler is supplied.
  const showPin = typeof onTogglePin === "function";
  // Hosted applications (flow_type 35) are not conversational — they open a web
  // surface at `/apps/{slug}`. Their primary action says "enter app", not "start chat".
  const HOSTED_APP_FLOW_TYPE = 35;
  const primaryActionLabel =
    agent.flow_type === HOSTED_APP_FLOW_TYPE ? localize("com_app_enter_app") : localize("com_app_start_chat");

  const handleShare = () => {
    onShare({ ...agent, can_share: true });
  };

  // Desktop card actions — rendered once, reused for the hover overlay and the
  // no-hover inline fallback.
  const actionButtons = (
    <>
      {canShare ? (
        <Button
          onClick={(e) => {
            e.stopPropagation();
            handleShare();
          }}
          variant="outline"
          className="flex-1 min-w-0 justify-center items-center h-full max-h-full rounded-md px-2 py-0 text-[14px] font-normal"
        >
          {localize("com_app_share_app")}
        </Button>
      ) : null}
      <Button
        onClick={(e) => {
          e.stopPropagation();
          onStartChat(agent);
        }}
        className="flex-1 min-w-0 justify-center items-center h-full max-h-full rounded-md px-2 py-0 text-[14px] font-normal"
      >
        {primaryActionLabel}
      </Button>
    </>
  );

  return (
    <div
      className={cn(
        "group/card relative flex cursor-pointer flex-col overflow-hidden rounded-[12px] border border-solid p-2 transition-all",
        "[--app-card-surface:var(--bg-page)] dark:[--app-card-surface:var(--fill-1)]",
        "border-border-base border-[0.5px] bg-[rgb(var(--app-card-surface))] fine-pointer:hover:shadow-[0px_2.094px_8.796px_1.047px_rgba(117,145,212,0.12)]",
        "after:pointer-events-none after:absolute after:inset-0 after:rounded-[12px] after:border after:border-blue-500 after:opacity-0 after:transition-opacity fine-pointer:group-hover/card:after:opacity-100",
        "bg-[linear-gradient(135deg,rgb(var(--brand-500)/0.04)_0%,rgb(var(--app-card-surface))_50%,rgb(var(--brand-500)/0.04)_100%)] dark:bg-[linear-gradient(135deg,rgb(var(--brand-500)/0.08)_0%,rgb(var(--app-card-surface))_50%,rgb(var(--brand-500)/0.08)_100%)]",
      )}
      onClick={() => onStartChat(agent)}
      onMouseEnter={() => {
        if (canHover) void ensureSharePermission();
      }}
    >
      {/* Header Info */}
      <div className="flex items-start justify-between w-full relative z-10 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <AppAvator
            className="size-[32px] min-w-[20px] shrink-0 rounded-md"
            url={agent.logo}
            id={agent.id as any}
            flowType={String(agent.flow_type)}
          />
          <p className="font-['PingFang_SC'] font-normal leading-[22px] text-text-1 text-[14px] truncate">
            {agent.name}
          </p>
          {/* Hosted applications only. A stopped application keeps its card on
              purpose: removing it is indistinguishable, to the user, from having
              lost access to it. */}
          {agent.app_state === "stopped" ? (
            <span className="shrink-0 rounded-sm bg-[#F2F3F5] px-1.5 py-0.5 text-[12px] leading-[16px] text-[#86909C]">
              {localize("com_app_state_stopped")}
            </span>
          ) : null}
          <DemoTag id={agent.id} className="shrink-0" />
        </div>

        {isMobileCard ? (
          showPin || canShare ? (
            <div
              className={cn(
                "flex items-center gap-1 shrink-0 transition-opacity",
                shouldUseHoverActionsInMobileCard
                  ? "opacity-0 pointer-events-none fine-pointer:group-hover/card:opacity-100 fine-pointer:group-hover/card:pointer-events-auto"
                  : "opacity-100 pointer-events-auto",
              )}
            >
              {showPin && isPinned ? (
                <span
                  className="inline-flex size-6 items-center justify-center rounded-md text-[rgb(var(--brand-muted))]"
                  aria-label={localize("com_app_unpin_tooltip")}
                >
                  <Outlined.Pin size={16} className="shrink-0" />
                </span>
              ) : null}
              {/* The menu is portaled, but its clicks still bubble through the
                  React tree to the card — stop them here. */}
              <span className="contents" onClick={(e) => e.stopPropagation()}>
                <Dropdown
                  align="end"
                  menu={
                    <>
                      {showPin ? (
                        <DropdownItem onSelect={() => onTogglePin?.(agent)}>
                          {isPinned ? localize("com_app_unpin_tooltip") : localize("com_app_pin_tooltip")}
                        </DropdownItem>
                      ) : null}
                      {canShare ? (
                        <DropdownItem onSelect={handleShare}>{localize("com_app_share_app")}</DropdownItem>
                      ) : null}
                    </>
                  }
                >
                  <button
                    type="button"
                    onClick={(e) => e.stopPropagation()}
                    className="inline-flex size-6 items-center justify-center rounded-md border border-border-base bg-[rgb(var(--app-card-surface))] text-text-3 fine-pointer:hover:bg-fill-1"
                    aria-label={localize("com_ui_more")}
                  >
                    <MoreVertical className="size-4" />
                  </button>
                </Dropdown>
              </span>
            </div>
          ) : null
        ) : showPin ? (
          <SharedTooltipProvider delayDuration={200}>
            <SharedTooltip
              content={isPinned ? localize("com_app_unpin_tooltip") : localize("com_app_pin_tooltip")}
            >
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onTogglePin?.(agent);
                }}
                className={cn(
                  "group/pin flex shrink-0 cursor-pointer items-center justify-center rounded-md p-1 transition-colors",
                  "border border-transparent fine-pointer:hover:border-border-base fine-pointer:hover:bg-fill-1",
                  isPinned
                    ? "opacity-100"
                    : shouldUseHoverActions
                      ? "opacity-0 pointer-events-none fine-pointer:group-hover/card:pointer-events-auto fine-pointer:group-hover/card:opacity-100"
                      : "opacity-100 pointer-events-auto",
                )}
                aria-label={isPinned ? localize("com_app_unpin_tooltip") : localize("com_app_pin_tooltip")}
              >
                {isPinned ? (
                  <span className="relative inline-flex size-[18px] items-center justify-center">
                    <Outlined.Pin
                      size={18}
                      className="absolute shrink-0 text-[rgb(var(--brand-muted))] transition-opacity fine-pointer:group-hover/pin:opacity-0"
                    />
                    <Outlined.PinOff
                      size={18}
                      className="pointer-events-none absolute text-text-2 opacity-0 transition-opacity fine-pointer:group-hover/pin:opacity-100"
                    />
                  </span>
                ) : (
                  <Outlined.Pin size={18} className="shrink-0 text-text-2" />
                )}
              </button>
            </SharedTooltip>
          </SharedTooltipProvider>
        ) : null}
      </div>

      {/* Description — fixed 3-line block (h = 3 × leading) so every card keeps a
          uniform height regardless of text length; clamp to 3 lines with ellipsis. */}
      <div className="mt-2 h-[58.5px] overflow-hidden font-['PingFang_SC'] font-normal text-[12px] text-text-3 leading-[19.5px] break-words line-clamp-3">
        {agent.description || localize("com_app_no_description_placeholder")}
      </div>

      {isMobileCard ? (
        <div className="mt-auto flex w-full min-w-0 items-center justify-between gap-1">
          <div className="relative min-w-0 flex-1 overflow-hidden">
            <div className="flex items-center gap-1 overflow-hidden whitespace-nowrap">
              {(agent.tags && agent.tags.length > 0
                ? agent.tags
                : [{ name: localize("com_app_featured_tag") }]
              ).map((tag, idx) => (
                <div
                  key={idx}
                  className="shrink-0 rounded-[4px] bg-fill-2 px-2 py-0.5 text-[12px] font-normal leading-[20px] text-text-2"
                >
                  {tag.name}
                </div>
              ))}
            </div>
            <div className="pointer-events-none absolute right-0 top-0 h-full w-6 bg-gradient-to-l from-[rgb(var(--app-card-surface))] to-transparent" />
          </div>
          <Button
            onClick={(e) => {
              e.stopPropagation();
              onStartChat(agent);
            }}
            variant="outline"
            className={cn(
              "h-6 shrink-0 rounded-md border border-border-base bg-[rgb(var(--app-card-surface))] px-2 py-0 text-[12px] font-normal leading-[20px] text-text-2 transition-opacity fine-pointer:hover:bg-fill-1",
              shouldUseHoverActionsInMobileCard
                ? "opacity-0 pointer-events-none fine-pointer:group-hover/card:opacity-100 fine-pointer:group-hover/card:pointer-events-auto"
                : "opacity-100 pointer-events-auto",
            )}
          >
            {primaryActionLabel}
          </Button>
        </div>
      ) : (
        <div
          className={cn(
            "w-full min-w-0",
            shouldUseHoverActions
              ? // Hover surfaces: actions overlay the bottom of the description on
                // hover (faded mask hides the text underneath), so the card height
                // stays at title + description without a reserved button row.
                "absolute inset-x-0 bottom-0 z-20 hidden px-2 pb-2 pt-6 [background:linear-gradient(to_top,rgb(var(--app-card-surface))_55%,rgb(var(--app-card-surface)/0))] fine-pointer:group-hover/card:block"
              : // No-hover surfaces: actions sit in normal flow below the description.
                "mt-2 block",
          )}
        >
          <div className="flex h-[28px] w-full min-w-0 items-stretch justify-center gap-2">
            {actionButtons}
          </div>
        </div>
      )}
    </div>
  );
}
