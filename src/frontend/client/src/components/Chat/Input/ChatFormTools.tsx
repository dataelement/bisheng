import { Button, Select } from "@bisheng/ui";
import { GlobeIcon, Settings2Icon } from "lucide-react";
import { useLocalize } from "~/hooks";
import useSelectCopy from "~/hooks/useSelectCopy";

import { BsConfig } from "~/types/chat";
import { cn } from "~/utils";

const NET_SEARCH = "netSearch";

/**
 * @deprecated v2.5 — use `AgentToolSelector` instead.
 * ChatToolDown only knows how to flip web-search on/off via the legacy
 * `searchType` atom. It is still rendered by `AiChatInput` when `bsConfig.tools`
 * is empty (pre-v2.5 admin configs); once the workstation config migration is
 * complete everywhere this component + the `searchType` atom can be deleted.
 */
export const ChatToolDown = ({
  config,
  searchType,
  setSearchType,
  disabled,
  compact = false,
}: {
  config?: BsConfig;
  searchType: string;
  setSearchType: (type: string) => void;
  disabled: boolean;
  /** Toolbar out of room (see useContainerCompact): collapse label to icon. */
  compact?: boolean;
}) => {
  const localize = useLocalize();
  const selectCopy = useSelectCopy();

  if (!config?.webSearch.enabled) return null;

  const active = searchType === NET_SEARCH;

  // The tools are a multiple Select whose value is shown by the pill itself
  // (the "arrow entry" trigger): the pill turns brand-tinted while a tool is on.
  return (
    <Select
      {...selectCopy}
      multiple
      disabled={disabled}
      options={[
        {
          value: NET_SEARCH,
          label: localize("com_tools_web_search"),
          icon: <GlobeIcon className="text-text-3" />,
        },
      ]}
      value={active ? [NET_SEARCH] : []}
      onChange={(next) => setSearchType(next.includes(NET_SEARCH) ? NET_SEARCH : "")}
      aria-label={localize("com_tools_title")}
      trigger={
        <Button
          color="default"
          variant="text"
          disabled={disabled}
          aria-label={localize("com_tools_title")}
          className={cn(
            "rounded-full",
            compact ? "gap-1 px-1.5" : "gap-2 px-2",
            // Business on-state of the web-search switch, not a Select state.
            active && "bg-blue-100 text-blue-600 hover:bg-blue-100 data-[menu-open]:bg-blue-100",
          )}
        >
          <Settings2Icon />
          {/* Compact: collapse to icon only to save horizontal space. */}
          {!compact && (
            <span className="truncate min-w-0 max-w-[min(36vw,140px)]">{localize("com_tools_title")}</span>
          )}
        </Button>
      }
    />
  );
};
