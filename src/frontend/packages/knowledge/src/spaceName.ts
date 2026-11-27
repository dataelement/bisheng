export const SPACE_NAME_LIMIT = 50;

export function spaceNameLength(name: string): number {
  return Array.from(name).length;
}

export function truncateSpaceName(name: string, limit = SPACE_NAME_LIMIT): string {
  return Array.from(name).slice(0, limit).join('');
}

export function isValidSpaceName(name: string, originalName?: string): boolean {
  return Boolean(name.trim()) && (name === originalName || spaceNameLength(name) <= SPACE_NAME_LIMIT);
}
