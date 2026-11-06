import type { PermissionGrantAssignee } from "@/controllers/API/permission"

/**
 * Pure logic behind the visibility-scope section — kept out of the component so
 * it can be tested without a DOM, and so the one non-obvious rule below lives
 * somewhere a reader will find it.
 */

/**
 * Whether the "only you can see this" banner applies.
 *
 * Two things make the obvious implementation wrong:
 *
 * 1. **`grants.length === 0` never happens.** F048 writes a *protected* grant
 *    for the owner when the application is created, so a freshly published app
 *    has exactly one row. Counting rows would hide the banner forever — and the
 *    banner is the entire mechanism by which an owner learns that colleagues
 *    cannot see the app they just launched.
 * 2. **The state gate is not decoration.** Before the app is online, "colleagues
 *    cannot find this in the square" is true *and* unfixable, so saying it is
 *    pure noise. The section still renders; only the banner waits.
 */
export function isOwnerOnly(
  appState: string | undefined,
  grants: PermissionGrantAssignee[],
): boolean {
  if (appState !== "online") {
    return false
  }
  return countGrantedSubjects(grants) === 0
}

/** Grants a human deliberately made — i.e. everything except the owner's own protected row. */
export function countGrantedSubjects(grants: PermissionGrantAssignee[]): number {
  return grants.filter((grant) => !grant.protected).length
}

/**
 * Label for "N subjects have access", from the **first page** of the roster.
 *
 * One page is enough for both questions this section asks. If page one holds no
 * non-protected grant, no later page will either (protected rows number in the
 * single digits), and a count that ran past the page boundary would trade an
 * extra round trip for a digit nobody acts on. When there is more, the label
 * says `N+` rather than pretending to be exact.
 */
export function summarizeGrants(
  grants: PermissionGrantAssignee[],
  hasMore: boolean,
): string {
  const count = countGrantedSubjects(grants)
  return hasMore ? `${count}+` : `${count}`
}
