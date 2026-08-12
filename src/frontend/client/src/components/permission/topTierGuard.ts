import type { PermissionGrantAssignee } from "~/api/permission";

/**
 * Top-tier (owner) grants may only be managed by the resource creator.
 *
 * This is a UI guardrail, not an authorization boundary. The catalog still ships
 * `owner.allow_same_level = true`, so the server continues to accept an owner
 * changing another owner and a direct API call is unaffected. The creator's own
 * row is already safe from everyone: it is a protected assignment and the server
 * refuses to move or remove it outright, so what this hides is one ordinary
 * owner editing another — peers of the same trust tier.
 *
 * Enforcing it properly means changing what the permission model expresses, and
 * that decision is still open. Kept in step with the platform app's copy.
 */

export const TOP_TIER_LEVEL = 4;

/** Read the viewer's standing from the roster it already loaded.
 *
 * Only the creator's own row identifies them, so a roster paged past that row
 * reads as "not the creator" — restrictive, which is the safe direction for a
 * guardrail. Rosters are served sorted with a default page of 50, so in practice
 * the row is on the first page.
 */
export function viewerIsCreator(
  assignees: PermissionGrantAssignee[],
  currentUserId: string | number | null | undefined,
): boolean {
  if (currentUserId === null || currentUserId === undefined) return false;
  const userId = String(currentUserId);
  return assignees.some(
    (assignee) =>
      assignee.source.type === "CREATOR" &&
      assignee.subject.type === "user" &&
      String(assignee.subject.id) === userId,
  );
}

/** Whether the viewer may act on a grant at this model level. */
export function canManageLevel(
  level: number | null | undefined,
  isCreator: boolean,
): boolean {
  return level !== TOP_TIER_LEVEL || isCreator;
}
