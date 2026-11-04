/**
 * AgentToolSelector — v2.5 Agent-mode tool picker for the daily chat input bar.
 *
 * Shows parent-level toggles that mirror Linsight (one Switch per tool group).
 * Backend still dispatches at child level, so each parent's children[] are
 * flattened into leaf-level entries at request time (see useAiChat).
 */

import { Outlined } from "bisheng-icons";
import { useEffect, useRef } from "react";
import { useRecoilState } from "recoil";
import { Button, Select, Switch } from "@bisheng/ui";
import useSelectCopy from "~/hooks/useSelectCopy";
import ApiAppIcon from "~/components/ui/icon/ApiApp";
import { useAuthContext, useLocalize } from "~/hooks";
import store from "~/store";
import type { SelectedAgentTool } from "~/store/modeltype";
import { cn } from "~/utils";

// Shape of a leaf tool inside a parent group's `children[]`.
interface ChildTool {
  id: number;
  name?: string;
  tool_key: string;
  enabled?: boolean;
  desc?: string;
  description?: string;
}

// Shape of each parent group in bsConfig.tools (workstation config), mirrors
// safe user-facing catalog: hierarchical parent with available children.
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

export function isToolGroupEnabled(group: AvailableToolGroup) {
  return !group.children?.length || group.children.some(child => child.enabled !== false);
}

function selectedToolGroup(group: AvailableToolGroup): SelectedAgentTool {
  return {
    id: group.id,
    name: group.name,
    description: group.description,
    children: (group.children || []).filter(child => child.enabled !== false).map(child => ({
      id: child.id,
      tool_key: child.tool_key,
      name: child.name,
      desc: child.desc || child.description,
    })),
  };
}

export interface AgentToolSelection {
  /** At least one tool group is switched on. */
  isActive: boolean;
  isChecked: (id: number) => boolean;
  toggle: (group: AvailableToolGroup) => void;
}

/**
 * Keep per-task tool choices while either picker presentation is closed.
 * Share per-account preferences between the composer and capability details.
 */
/** Mounted once by the authenticated layout, above cached and uncached pages. */
export function useAgentToolPreferences(availableTools?: AvailableToolGroup[]) {
  const [selected, setSelected] = useRecoilState(store.selectedAgentTools);
  const { user } = useAuthContext();
  const userId = user?.id === undefined ? undefined : String(user.id);
  const restoring = useRef<{ userId: string; value: typeof selected }>();
  const hydratedUser = useRef<string>();
  useEffect(() => {
    if (!userId || hydratedUser.current === userId) return;
    let restored: typeof selected | undefined;
    try {
      const value = JSON.parse(localStorage.getItem(`bs:${userId}:selectedAgentTools`) ?? 'null');
      if (Array.isArray(value)) restored = value;
    } catch { /* Invalid snapshots resolve from the configured defaults. */ }
    if (restored === undefined) {
      if (!availableTools) return;
      restored = availableTools.filter(group => group.default_checked && isToolGroupEnabled(group)).map(selectedToolGroup);
    }
    restoring.current = { userId, value: restored };
    hydratedUser.current = userId;
    setSelected(restored);
  }, [userId, availableTools, setSelected]);
  useEffect(() => {
    if (!userId || hydratedUser.current !== userId) return;
    if (restoring.current) {
      if (restoring.current.value !== selected) return;
      restoring.current = undefined;
    }
    try { localStorage.setItem(`bs:${userId}:selectedAgentTools`, JSON.stringify(selected)); }
    catch { /* Keep the in-session choice when browser storage is unavailable. */ }
  }, [userId, selected]);
}

export function useAgentToolSelection(availableTools: AvailableToolGroup[] | undefined): AgentToolSelection {
  const [selected, setSelected] = useRecoilState(store.selectedAgentTools);
  // Revalidate the user selection when the authorized catalog changes.
  useEffect(() => {
    if (!availableTools || selected.length === 0) return;
    const byId = new Map(availableTools.filter(isToolGroupEnabled).map(group => [group.id, group]));
    const pruned = selected.flatMap(group => {
      const current = byId.get(group.id);
      return current ? [selectedToolGroup(current)] : [];
    });
    if (JSON.stringify(pruned) !== JSON.stringify(selected)) setSelected(pruned);
  }, [availableTools, selected, setSelected]);

  const isChecked = (id: number) => selected.some((g) => g.id === id);
  const toggle = (group: AvailableToolGroup) => {
    if (!isToolGroupEnabled(group)) return;
    if (isChecked(group.id)) {
      setSelected(selected.filter((g) => g.id !== group.id));
    } else {
      setSelected([
        ...selected,
        selectedToolGroup(group),
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
  const selectCopy = useSelectCopy();
  const isActive = selection.isActive;

  if (!availableTools || availableTools.length === 0) return null;

  return (
    <Select
      {...selectCopy}
      multiple
      disabled={disabled}
      options={availableTools.map((group) => ({
        value: group.id,
        label: labelForGroup(group, localize),
        icon: iconForGroup(group),
        disabled: !isToolGroupEnabled(group),
      }))}
      value={availableTools.filter((group) => selection.isChecked(group.id)).map((group) => group.id)}
      onChange={(ids) => {
        const changed = availableTools.find((group) => ids.includes(group.id) !== selection.isChecked(group.id));
        if (changed) selection.toggle(changed);
      }}
      aria-label={localize("com_tools_title")}
      trigger={
        <Button color="default" variant="text" disabled={disabled} aria-label={localize("com_tools_title")}
          className="min-w-0 max-w-[min(52vw,220px)] gap-1.5 px-2 text-text-2">
          <ApiAppIcon className={cn("shrink-0", isActive ? "text-blue-500" : "text-text-2")} />
          {!compact && <span className="truncate text-sm font-normal max-w-[min(20vw,60px)]">{localize("com_tools_title")}</span>}
          <Outlined.Down className="size-4 shrink-0" />
        </Button>
      }
    />
  );
}
