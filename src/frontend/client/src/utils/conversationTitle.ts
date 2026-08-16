/**
 * Placeholder conversation titles.
 *
 * New backend rows store an EMPTY name for unnamed conversations and the client
 * renders the localized placeholder (`com_ui_new_chat`). Legacy rows persisted
 * the display string itself ("New Chat" / "新对话"), so those literals are
 * treated as placeholders too — no data migration required.
 */
export const PLACEHOLDER_CONVERSATION_TITLE_RE = /^(new chat|新对话)$/i;

export function isPlaceholderConversationTitle(title?: string | null): boolean {
  const trimmed = (title ?? '').trim();
  return trimmed === '' || PLACEHOLDER_CONVERSATION_TITLE_RE.test(trimmed);
}

/** The title to render: the real name, or the localized placeholder. */
export function displayConversationTitle(
  title: string | null | undefined,
  localizedPlaceholder: string,
): string {
  return isPlaceholderConversationTitle(title) ? localizedPlaceholder : String(title).trim();
}
