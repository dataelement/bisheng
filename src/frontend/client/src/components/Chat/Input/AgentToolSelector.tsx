// @ts-strict-ignore
/**
 * AgentToolSelector — v2.5 Agent-mode tool picker for the daily chat input bar.
 *
 * Shows parent-level toggles that mirror Linsight (one Switch per tool group).
 * Backend still dispatches at child level, so each parent's children[] are
 * flattened into leaf-level entries at request time (see useAiChat).
 */
import { Settings2Icon, WebhookIcon } from "lucide-react";
import { Outlined } from "bisheng-icons";
import { useEffect } from "react";
import { useRecoilState } from "recoil";
import { Switch } from "~/components/ui";
import ApiAppIcon from "~/components/ui/icon/ApiApp";
import { Select, SelectContent, SelectTrigger } from "~/components/ui/Select";
import { useLocalize } from "~/hooks";
import store from "~/store";
import { cn } from "~/utils";

// Shape of a leaf tool inside a parent group's `children[]`.
interface ChildTool {
  id: number;
  name?: string;
  tool_key: string;
  desc?: string;
  description?: string;
}

// Shape of each parent group in bsConfig.tools (workstation config), mirrors
// linsight_config.tools: hierarchical parent with selected children + a single
// `default_checked` flag applied to the whole group.
export interface AvailableToolGroup {
  id: number;
  name: string;
  is_preset?: number;
  description?: string;
  default_checked?: boolean;
  children?: ChildTool[];
}

interface Props {
  availableTools: AvailableToolGroup[];
  selection: AgentToolSelection;
  disabled?: boolean;
  /** Toolbar out of room (see useContainerCompact): collapse label to icon. */
  compact?: boolean;
}

function iconForGroup(group: AvailableToolGroup) {
  const firstKey = group.children?.[0]?.tool_key;
  if (firstKey === "web_search") return <Outlined.Earth className="size-4 text-text-2" />;
  return <Outlined.Hammer className="size-4 text-text-2" />;
}

function labelForGroup(group: AvailableToolGroup, localize: (key: string) => string) {
  const isImageView =
    group.name === "Image View" ||
    (group.children ?? []).some((child) => child.tool_key === "image_view");
  if (isImageView) return localize("com_tools.image_view");
  return group.name;
}

export interface AgentToolSelection {
  /** At least one tool group is switched on. */
  isActive: boolean;
  isChecked: (id: number) => boolean;
  toggle: (group: AvailableToolGroup) => void;
}

/**
 * Selection state for the agent tools, separate from any UI so it keeps running
 * while its picker is closed: the default_checked seeding below must happen on
 * mount, not the first time a menu is opened. Call it once per input and hand the
 * result to AgentToolSelector (toolbar pill) or AgentToolList ("+" menu panel).
 */
export function useAgentToolSelection(availableTools: AvailableToolGroup[] | undefined): AgentToolSelection {
  const [selected, setSelected] = useRecoilState(store.selectedAgentTools);
  const [initialized, setInitialized] = useRecoilState(store.agentToolsInitialized);

  // One-shot initialisation from admin-configured default_checked set.
  // Ignores subsequent bsConfig changes within the same session so a user's
  // manual toggles aren't overwritten when the config gets refetched.
  useEffect(() => {
    if (initialized || !availableTools || availableTools.length === 0) return;
    const defaults = availableTools
      .filter((g) => g.default_checked)
      .map((g) => ({
        id: g.id,
        name: g.name,
        description: g.description,
        children: (g.children || []).map((c) => ({
          id: c.id,
          tool_key: c.tool_key,
          name: c.name,
          desc: c.desc || c.description,
        })),
      }));
    if (defaults.length) setSelected(defaults);
    setInitialized(true);
  }, [availableTools, initialized, setSelected, setInitialized]);

  // Prune selections for groups that no longer exist in the admin config
  // (e.g., admin removed a tool between sessions).
  useEffect(() => {
    if (!availableTools?.length || selected.length === 0) return;
    const validIds = new Set(availableTools.map((g) => g.id));
    const pruned = selected.filter((g) => validIds.has(g.id));
    if (pruned.length !== selected.length) setSelected(pruned);
  }, [availableTools, selected, setSelected]);

  const isChecked = (id: number) => selected.some((g) => g.id === id);
  const toggle = (group: AvailableToolGroup) => {
    if (isChecked(group.id)) {
      setSelected(selected.filter((g) => g.id !== group.id));
    } else {
      setSelected([
        ...selected,
        {
          id: group.id,
          name: group.name,
          description: group.description,
          children: (group.children || []).map((c) => ({
            id: c.id,
            tool_key: c.tool_key,
            name: c.name,
            desc: c.desc || c.description,
          })),
        },
      ]);
    }
  };

  return { isActive: selected.length > 0, isChecked, toggle };
}

export { iconForGroup, labelForGroup };

interface AgentToolListProps {
  availableTools: AvailableToolGroup[];
  selection: AgentToolSelection;
  disabled?: boolean;
}

/** One switch row per tool group — the body of both the pill's panel and the "+" submenu. */
export function AgentToolList({ availableTools, selection, disabled }: AgentToolListProps) {
  const localize = useLocalize();
  return (
    <>
      {availableTools.map((group) => {
        const label = labelForGroup(group, localize);
        return (
          <div key={group.id} className="flex h-8 shrink-0 justify-between items-center rounded-lg px-2">
            <div className="flex gap-2 items-center min-w-0">
              {iconForGroup(group)}
              <span
                className="max-w-40 text-sm font-normal line-clamp-1 flex-1 truncate"
                title={group.description || label}
              >
                {label}
              </span>
            </div>
            <Switch
              variant="tool"
              aria-label={label}
              className="shrink-0"
              disabled={disabled}
              checked={selection.isChecked(group.id)}
              onCheckedChange={() => selection.toggle(group)}
            />
          </div>
        );
      })}
    </>
  );
}

export default function AgentToolSelector({ availableTools, selection, disabled, compact = false }: Props) {
  const localize = useLocalize();
  const isActive = selection.isActive;

  if (!availableTools || availableTools.length === 0) return null;

  return (
    <Select disabled={disabled}>
      <SelectTrigger
        className={cn(
          // Tools Select never sets a value (selection is via inner switches), so
          // Radix keeps the trigger in [data-placeholder] state; without this the
          // base `data-[placeholder]:text-gray-500` would override to #595959 and
          // mismatch the knowledge/model selects. Pin it to the shared #4E5969.
          "dsh-composer-control h-8 min-w-0 max-w-[min(52vw,220px)] rounded-lg border-none bg-transparent shadow-none hover:bg-fill-2 px-2 text-text-2 data-[placeholder]:text-text-2 focus:ring-0 outline-none w-auto gap-1",
        )}
      >
        <div className="flex min-w-0 gap-1.5 items-center">
          {/* Icon is neutral by default (matches the + button) and turns
              brand-blue once a tool is selected — mirrors the knowledge-space
              selector (ChatKnowledge) so both pickers signal an active selection. */}
          <div className="relative shrink-0">
            <ApiAppIcon size="15" className={cn("shrink-0", isActive ? "text-blue-500" : "text-text-2")} strokeWidth={1.5} />
          </div>
          {/* Compact: collapse to icon + chevron only to save horizontal space. */}
          {!compact && (
            <span className="text-[14px] font-normal truncate min-w-0 max-w-[min(20vw,60px)]">
              {localize("com_tools_title")}
            </span>
          )}
        </div>
      </SelectTrigger>
      <SelectContent
        className="dsh-chat-menu bg-page rounded-2xl w-[200px] max-h-[320px] overflow-y-auto"
        viewportClassName="flex flex-col gap-1 p-3"
      >
        <AgentToolList availableTools={availableTools} selection={selection} disabled={disabled} />
      </SelectContent>
    </Select>
  );
}
