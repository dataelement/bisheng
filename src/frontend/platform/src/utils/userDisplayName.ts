/** Include the business person ID without changing the stored username. */

export type UserDisplayPeer = {
  user_name: string
  user_id?: number
  person_id?: string | null
}

export function formatUserDisplayName(u: UserDisplayPeer): string {
  const name = (u.user_name || "").trim() || "-"
  const pid = (u.person_id && String(u.person_id).trim()) || ""
  if (!pid) return name
  return `${name}（${pid}）`
}

export function buildMemberDisplayNameMap(
  members: { user_id: number; user_name: string; person_id?: string | null }[]
): Map<number, string> {
  const map = new Map<number, string>()
  for (const m of members) {
    map.set(
      m.user_id,
      formatUserDisplayName(
        {
          user_name: m.user_name,
          user_id: m.user_id,
          person_id: m.person_id ?? undefined,
        }
      )
    )
  }
  return map
}
