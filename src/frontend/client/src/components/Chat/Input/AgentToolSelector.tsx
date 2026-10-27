// @ts-strict-ignore
/**
 * AgentToolSelector — v2.5 Agent-mode tool picker for the daily chat input bar.
 *
 * A multiple Select over the tool groups (one option per group, mirroring
 * Linsight); the trigger is the toolbar's own button, tinted while any is on.
 * Backend still dispatches at child level, so each parent's children[] are
 * flattened into leaf-level entries at request time (see useAiChat).
 */
import { Button, Select } from '@bisheng/ui';
import { Outlined } from "bisheng-icons";
import { useEffect } from "react";
import { useRecoilState } from "recoil";
import ApiAppIcon from "~/components/ui/icon/ApiApp";
import { useLocalize } from "~/hooks";
import useSelectCopy from "~/hooks/useSelectCopy";
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
  disabled?: boolean;
  /** Toolbar out of room (see useContainerCompact): collapse label to icon. */
  compact?: boolean;
}

function iconForGroup(group: AvailableToolGroup) {
  const firstKey = group.children?.[0]?.tool_key;
  if (firstKey === "web_search") return <Outlined.Earth className="text-text-2" />;
  return <Outlined.Hammer className="text-text-2" />;
}

function labelForGroup(group: AvailableToolGroup) {
  return group.name;
}

/** The leaf-flattened shape stored in `store.selectedAgentTools`. */
function toSelection(group: AvailableToolGroup) {
  return {
    id: group.id,
    name: group.name,
    description: group.description,
    children: (group.children || []).map((c) => ({
      id: c.id,
      tool_key: c.tool_key,
      name: c.name,
      desc: c.desc || c.description,
    })),
  };
}

export default function AgentToolSelector({ availableTools, disabled, compact = false }: Props) {
  const localize = useLocalize();
  const selectCopy = useSelectCopy();
  const [selected, setSelected] = useRecoilState(store.selectedAgentTools);
  const [initialized, setInitialized] = useRecoilState(store.agentToolsInitialized);

  // One-shot initialisation from admin-configured default_checked set.
  // Ignores subsequent bsConfig changes within the same session so a user's
  // manual toggles aren't overwritten when the config gets refetched.
  useEffect(() => {
    if (initialized || !availableTools || availableTools.length === 0) return;
    const defaults = availableTools.filter((g) => g.default_checked).map(toSelection);
    if (defaults.length) setSelected(defaults);
    setInitialized(true);
  }, [availableTools, initialized, setSelected, setInitialized]);

  // Prune selections for groups that no longer exist in the admin config
  // (e.g., admin removed a tool between sessions).
  useEffect(() => {
    if (!availableTools || selected.length === 0) return;
    const validIds = new Set(availableTools.map((g) => g.id));
    const pruned = selected.filter((g) => validIds.has(g.id));
    if (pruned.length !== selected.length) setSelected(pruned);
  }, [availableTools, selected, setSelected]);

  const activeCount = selected.length;
  const isActive = activeCount > 0;

  // Keep earlier picks as they were (and in their order); only new ids are
  // built from the admin config.
  const handleChange = (ids: (string | number)[]) => {
    const kept = selected.filter((g) => ids.includes(g.id));
    const added = availableTools
      .filter((g) => ids.includes(g.id) && !kept.some((k) => k.id === g.id))
      .map(toSelection);
    setSelected([...kept, ...added]);
  };

  if (!availableTools || availableTools.length === 0) return null;

  return (
    <Select
      {...selectCopy}
      multiple
      disabled={disabled}
      options={availableTools.map((group) => ({
        value: group.id,
        label: labelForGroup(group),
        icon: iconForGroup(group),
      }))}
      value={selected.map((g) => g.id)}
      onChange={handleChange}
      aria-label={localize("com_tools_title")}
      trigger={
        <Button
          color="default"
          variant="text"
          disabled={disabled}
          aria-label={localize("com_tools_title")}
          className="min-w-0 max-w-[min(52vw,220px)] gap-1.5 px-2 text-text-2"
        >
          {/* Icon is neutral by default (matches the + button) and turns
              brand-blue once a tool is selected — mirrors the knowledge-space
              selector (ChatKnowledge) so both pickers signal an active selection. */}
          <ApiAppIcon size="15" className={cn("shrink-0", isActive ? "text-blue-500" : "text-text-2")} strokeWidth={1.5} />
          {/* Compact: collapse to icon only to save horizontal space. */}
          {!compact && (
            <span className="truncate min-w-0 max-w-[min(20vw,60px)]">
              {localize("com_tools_title")}
            </span>
          )}
        </Button>
      }
    />
  );
}
