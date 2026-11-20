import { resolveUserAvatarUrl } from "@bisheng/identity"
import { Tabs, UserAvatar } from "@bisheng/ui"
import { Building2, Users } from "lucide-react"
import type { ReactNode } from "react"
import type { SubjectType } from "./types"

export const permissionDialogClassName = "flex h-[80vh] max-h-[800px] w-[calc(100vw-80px)] max-w-[800px] min-w-0 flex-col gap-0 overflow-hidden"

interface PermissionSubjectTabsProps {
  tabs: { value: SubjectType; label: string }[]
  value?: SubjectType
  onChange?: (value: SubjectType) => void
}

/** The roster uses Radix tabs; the grant form uses a controlled button strip. */
export function PermissionSubjectTabs({ tabs, value, onChange }: PermissionSubjectTabsProps) {
  return <Tabs activeKey={value} onChange={key => onChange?.(key as SubjectType)}
    items={tabs.map(tab => ({ key: tab.value, label: tab.label }))} />
}

interface PermissionSubjectIdentityProps {
  type: SubjectType
  name: string
  avatar?: string | null
  avatarName?: string | null
  metadata?: ReactNode
}

export function PermissionSubjectIdentity({ type, name, avatar, avatarName = name, metadata }: PermissionSubjectIdentityProps) {
  const Icon = type === "department" ? Building2 : Users
  return <div className="flex min-w-0 flex-1 items-center gap-3">
    {type === "user" ? <UserAvatar className="size-8" fallbackClassName="text-sm" name={avatarName}
      src={resolveUserAvatarUrl(avatar, __APP_ENV__.BASE_URL)} />
      : <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary"><Icon aria-hidden="true" className="size-4" /></span>}
    <div className="min-w-0">
      <p className="truncate text-sm font-medium text-[#212121]">{name}</p>
      {metadata && <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-1 text-xs text-[#86909C]">{metadata}</div>}
    </div>
  </div>
}
