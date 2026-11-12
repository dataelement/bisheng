/** Pure helpers for the agent tool selection; kept free of UI imports so tests stay light. */
import type { SelectedAgentTool } from "~/store/modeltype";
import type { AvailableToolGroup } from "./AgentToolSelector";

export function isToolGroupEnabled(group: AvailableToolGroup) {
  return !group.children?.length || group.children.some(child => child.enabled !== false);
}

export function selectedToolGroup(group: AvailableToolGroup): SelectedAgentTool {
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

// Snapshots saved before the applied-defaults record existed already reflect
// the user's choice for every older default. Only these tools became defaults
// with the record, so only they are added to such a snapshot (once).
const NEW_DEFAULT_TOOL_KEYS = new Set(['bisheng_code_interpreter']);

/**
 * Apply each default-checked group once per account. A group already applied
 * stays as the user left it; a group that becomes a default later (for example
 * the code executor) is added on the next load. Defaults enter as `auto`, which
 * keeps them out of the composer text.
 */
export function applyToolDefaults(
  restored: SelectedAgentTool[] | undefined,
  applied: number[] | undefined,
  availableTools: AvailableToolGroup[],
): { selection: SelectedAgentTool[]; applied: number[] } {
  const defaults = availableTools.filter(group => group.default_checked && isToolGroupEnabled(group));
  const defaultIds = new Set(defaults.map(group => group.id));
  // A snapshot from before this record existed: its default groups count as preselected.
  const base = restored === undefined ? [] : applied === undefined
    ? restored.map(group => (defaultIds.has(group.id) ? { ...group, auto: true } : group))
    : restored;
  const appliedIds = new Set(applied ?? (restored === undefined ? [] : defaults
    .filter(group => !group.children?.some(child => NEW_DEFAULT_TOOL_KEYS.has(child.tool_key)))
    .map(group => group.id)));
  const have = new Set(base.map(group => group.id));
  const added = defaults
    .filter(group => !appliedIds.has(group.id) && !have.has(group.id))
    .map(group => ({ ...selectedToolGroup(group), auto: true }));
  return {
    selection: added.length ? [...base, ...added] : base,
    applied: Array.from(new Set([...appliedIds, ...defaultIds])),
  };
}

