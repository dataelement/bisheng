/**
 * Decides where the task-mode toggle should sit after a navigation.
 *
 * Extracted from ChatView so the rule is testable on its own: it used to live in
 * two effects that disagreed. One reset the toggle to off on every
 * `location.key` change; the other restored it, but its deps
 * (`[conversationId, isTaskConversation, canUseTaskMode]`) are all constant
 * within a visit, so it could never fire twice. A single in-conversation
 * navigation — clicking the sidebar 首页 entry, whose target IS the current
 * pathname — therefore parked a task conversation on "daily" permanently, and
 * the next turn silently went to the daily chain.
 */
export interface TaskModeNavigationInput {
  /** Route param; `'new'` before the conversation has an id. */
  conversationId: string;
  /** The loaded history contains a task turn belonging to this conversation. */
  isTaskConversation: boolean;
  /** Task mode is available to this user / tenant at all. */
  canUseTaskMode: boolean;
  /** `location.state.taskMode`; undefined when the navigation declares nothing. */
  navTaskMode?: boolean;
  /** The post-submit `/c/new` → `/c/<id>` self-rewrite (same conversation). */
  isSelfRewrite: boolean;
  /** The user flipped the toggle by hand inside this conversation. */
  userToggled: boolean;
}

/**
 * Returns the mode to apply, or `null` to leave the toggle untouched.
 */
export function resolveTaskModeOnNavigation({
  conversationId,
  isTaskConversation,
  canUseTaskMode,
  navTaskMode,
  isSelfRewrite,
  userToggled,
}: TaskModeNavigationInput): boolean | null {
  if (conversationId === 'new') {
    // Both sidebar entries set the atom themselves before navigating, so only a
    // navigation that actually declares a mode is honoured here. Reading an
    // absent state as "daily" used to drop the user's choice: `newConversation`
    // fires its own state-less `navigate('/c/new')` a tick after ours, and that
    // second landing reset the toggle the button had just set.
    return navTaskMode === undefined ? null : !!navTaskMode;
  }
  // Same conversation, new URL: keep whatever the user is composing in.
  if (isSelfRewrite) {
    return null;
  }
  // An explicit manual choice outranks the derived mode until the user leaves.
  if (userToggled) {
    return null;
  }
  // Derive from the conversation's own history. `isTaskConversation` is false
  // until the history resolves, so this settles on off first and flips back on
  // once the loaded rows prove otherwise.
  return isTaskConversation && canUseTaskMode;
}
