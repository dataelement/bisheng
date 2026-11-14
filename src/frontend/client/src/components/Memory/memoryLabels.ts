/** Display helpers shared by the memory settings page and the chat notices (F132). */
import type { MemoryItem, MemorySource } from "~/api/memory";

type Localize = (key: string, options?: Record<string, unknown>) => string;

export const MEMORY_ITEM_TYPES = ["fact", "preference", "experience"] as const;

const SCENES = new Set(["daily", "linsight", "assistant", "workflow"]);

export function memoryTypeLabel(type: string, localize: Localize): string {
  return (MEMORY_ITEM_TYPES as readonly string[]).includes(type) ? localize(`memory.type.${type}`) : type;
}

/** "Added by hand", or the scene (plus app name) the item came from; auto-consolidated items say so. */
export function memorySourceLabel(source: MemorySource | null | undefined, localize: Localize): string {
  if (!source || source.origin === "manual" || source.scene === "manual") return localize("memory.source.manual");
  const scene = source.scene && SCENES.has(source.scene) ? localize(`memory.source.${source.scene}`) : localize("memory.source.unknown");
  const where = source.app_name ? `${scene} · ${source.app_name}` : scene;
  return source.origin === "auto" ? localize("memory.source.auto", { source: where }) : where;
}

/** One-line meta of an item: type is shown separately as a tag. The event date is
 *  left out: the content already states it, and it stays editable in the item editor. */
export function memoryMetaParts(item: MemoryItem, localize: Localize): string[] {
  const parts: string[] = [];
  if (item.recorded_at) parts.push(localize("memory.recorded_at_value", { time: item.recorded_at }));
  parts.push(memorySourceLabel(item.source, localize));
  return parts;
}
