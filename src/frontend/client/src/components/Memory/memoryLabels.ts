/** Display helpers shared by the memory settings page and the chat notices (F132). */
import type { MemoryItem, MemorySource } from "~/api/memory";

type Localize = (key: string, options?: Record<string, unknown>) => string;

export const MEMORY_ITEM_TYPES = ["fact", "preference", "experience"] as const;

const SCENES = new Set(["daily", "linsight", "assistant", "workflow"]);

export function memoryTypeLabel(type: string, localize: Localize): string {
  return (MEMORY_ITEM_TYPES as readonly string[]).includes(type) ? localize(`memory.type.${type}`) : type;
}

/** Plural heading of a type's group in the memory list ("Preferences"). */
export function memoryGroupLabel(type: string, localize: Localize): string {
  return (MEMORY_ITEM_TYPES as readonly string[]).includes(type) ? localize(`memory.group.${type}`) : type;
}

/** "Added by hand", or the scene (plus app name) the item came from; auto-consolidated items say so.
 *  Only the scene says where an item came from: editing or AI-revising an item keeps its scene and
 *  only switches ``origin`` to manual, so ``origin`` must not turn a chat-born item into "added by hand". */
export function memorySourceLabel(source: MemorySource | null | undefined, localize: Localize): string {
  if (!source || source.scene === "manual") return localize("memory.source.manual");
  const scene = source.scene && SCENES.has(source.scene) ? localize(`memory.source.${source.scene}`) : localize("memory.source.unknown");
  const where = source.app_name ? `${scene} · ${source.app_name}` : scene;
  return source.origin === "auto" ? localize("memory.source.auto", { source: where }) : where;
}

const GROUP_ORDER = ["preference", "fact", "experience"];

/** Items grouped by type for the memory list, in a fixed order (preferences first);
 *  an unknown type gets its own group after the known ones. Order inside a group is kept. */
export function groupMemoryItems(items: MemoryItem[]): { type: string; items: MemoryItem[] }[] {
  const groups = new Map<string, MemoryItem[]>(GROUP_ORDER.map((type) => [type, []]));
  for (const item of items) {
    const group = groups.get(item.type) ?? [];
    group.push(item);
    groups.set(item.type, group);
  }
  return [...groups].filter(([, group]) => group.length > 0).map(([type, group]) => ({ type, items: group }));
}

/** The date part of a "YYYY-MM-DD HH:mm" timestamp, for the quiet date column of the list. */
export function memoryDate(recordedAt: string | null): string {
  return recordedAt ? recordedAt.slice(0, 10) : "";
}
