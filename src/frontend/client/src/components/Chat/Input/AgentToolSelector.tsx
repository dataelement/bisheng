/**
 * AgentToolSelector — v2.5 Agent-mode tool picker for the daily chat input bar.
 *
 * Shows parent-level toggles that mirror Linsight (one Switch per tool group).
 * Backend still dispatches at child level, so each parent's children[] are
 * flattened into leaf-level entries at request time (see useAiChat).
 */
import { Settings2Icon, GlobeIcon, Hammer, WebhookIcon } from "lucide-react";
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
  disabled?: boolean;
}

function iconForGroup(group: AvailableToolGroup) {
  const firstKey = group.children?.[0]?.tool_key;
  if (firstKey === "web_search") return <GlobeIcon size="16" />;
  return <Hammer size="16" />;
}

export default function AgentToolSelector({ availableTools, disabled }: Props) {
  const localize = useLocalize();
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
    if (!availableTools || selected.length === 0) return;
    const validIds = new Set(availableTools.map((g) => g.id));
    const pruned = selected.filter((g) => validIds.has(g.id));
    if (pruned.length !== selected.length) setSelected(pruned);
  }, [availableTools, selected, setSelected]);

  const activeCount = selected.length;
  const isActive = activeCount > 0;

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

  if (!availableTools || availableTools.length === 0) return null;

  return (
    <Select disabled={disabled}>
      <SelectTrigger
        className={cn(
          "h-8 min-w-0 max-w-[min(52vw,220px)] border-none bg-transparent shadow-none hover:bg-black/5 px-2 text-[#4E5969] focus:ring-0 outline-none w-auto gap-1",
          isActive && "border border-primary",
        )}
      >
        <div className="flex min-w-0 gap-1.5 items-center">
          <ApiAppIcon size="15" className={cn("shrink-0 text-[#165DFF]", isActive && "text-blue-600")} strokeWidth={1.5} />
          <span className="text-[14px] font-normal truncate min-w-0 max-w-[min(40vw,160px)]">
            {localize("com_tools_title")}
            {/* {isActive ? ` (${activeCount})` : ""} */}
          </span>
        </div>
      </SelectTrigger>
      <SelectContent className="bg-white rounded-xl p-2 w-64 max-h-[320px] overflow-y-auto">
        {availableTools.map((group) => (
          <div key={group.id} className="flex justify-between items-center mb-3 last:mb-0">
            <div className="flex gap-2 items-center min-w-0">
              {iconForGroup(group)}
              <span
                className="max-w-40 text-xs font-normal line-clamp-1 flex-1 truncate"
                title={group.description || group.name}
              >
                {group.name}
              </span>
            </div>
            <Switch
              className="data-[state=checked]:bg-blue-600 shrink-0"
              disabled={disabled}
              checked={isChecked(group.id)}
              onCheckedChange={() => toggle(group)}
            />
          </div>
        ))}
      </SelectContent>
    </Select>
  );
}
