/** 重名时在展示中附加人员 ID；不修改数据库中的 user_name。 */

export type UserDisplayPeer = {
  user_name: string
  user_id?: number
  person_id?: string | null
}

export function formatUserDisplayName(
  u: UserDisplayPeer,
  peers?: UserDisplayPeer[]
): string {
  const name = (u.user_name || "").trim() || "-"
  if (!peers || peers.length < 2) return name
  const same = peers.filter((p) => (p.user_name || "").trim() === name)
  if (same.length < 2) return name
  const pid =
    (u.person_id && String(u.person_id).trim()) ||
    (u.user_id != null ? String(u.user_id) : "")
  if (!pid) return name
  return `${name}（${pid}）`
}

export function buildMemberDisplayNameMap(
  members: { user_id: number; user_name: string; person_id?: string | null }[]
): Map<number, string> {
  const peers: UserDisplayPeer[] = members.map((m) => ({
    user_name: m.user_name,
    user_id: m.user_id,
    person_id: m.person_id ?? undefined,
  }))
  const map = new Map<number, string>()
  for (const m of members) {
    map.set(
      m.user_id,
      formatUserDisplayName(
        {
          user_name: m.user_name,
          user_id: m.user_id,
          person_id: m.person_id ?? undefined,
        },
        peers
      )
    )
  }
  return map
}
