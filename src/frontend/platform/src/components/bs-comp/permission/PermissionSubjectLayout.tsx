import { TabsList, TabsTrigger } from "@/components/bs-ui/tabs"
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
  if (onChange) return <div className="inline-flex w-fit shrink-0 items-center justify-center rounded-[6px] border border-[#ECECEC] bg-white p-[3px]">
    {tabs.map(tab => <button key={tab.value} type="button" aria-pressed={value === tab.value}
      className={`min-w-0 rounded-[4px] px-3 py-0.5 text-[14px] leading-[22px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 ${value === tab.value ? "bg-primary/10 font-medium text-primary" : "font-normal text-[#818181]"}`}
      onClick={() => onChange(tab.value)}>{tab.label}</button>)}
  </div>
  return <TabsList className="h-auto w-fit shrink-0 rounded-[6px] border border-[#ECECEC] bg-white p-[3px] shadow-none">
    {tabs.map(tab => <TabsTrigger key={tab.value} value={tab.value}
      className="min-w-0 rounded-[4px] px-3 py-0.5 text-[14px] font-normal leading-[22px] text-[#818181] shadow-none data-[state=active]:border-transparent data-[state=active]:bg-primary/10 data-[state=active]:font-medium data-[state=active]:text-primary data-[state=active]:shadow-none data-[state=inactive]:border-transparent">{tab.label}</TabsTrigger>)}
  </TabsList>
}

interface PermissionSubjectIdentityProps {
  type: SubjectType
  name: string
  metadata?: ReactNode
}

export function PermissionSubjectIdentity({ type, name, metadata }: PermissionSubjectIdentityProps) {
  const Icon = type === "department" ? Building2 : Users
  return <div className="flex min-w-0 flex-1 items-center gap-3">
    {type === "user" ? <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-[#C9CDD4] text-sm font-semibold text-white">{(name.trim().charAt(0) || "U").toUpperCase()}</span>
      : <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary"><Icon aria-hidden="true" className="size-4" /></span>}
    <div className="min-w-0">
      <p className="truncate text-sm font-medium text-[#212121]">{name}</p>
      {metadata && <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-1 text-xs text-[#86909C]">{metadata}</div>}
    </div>
  </div>
}
