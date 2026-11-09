/** A logical draft survives the web entry's delayed reset and settings return. */
export function readNewChatKey(state: unknown, fallback: string): string {
  return state && typeof state === 'object' && 'newChatKey' in state && typeof state.newChatKey === 'string'
    ? state.newChatKey : fallback;
}
