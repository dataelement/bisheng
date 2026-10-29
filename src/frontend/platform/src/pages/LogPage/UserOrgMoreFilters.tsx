import { Button } from "@/components/bs-ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover"
import { getAuditUserOrgOptionsApi } from "@/controllers/API/log"
import { ChevronDown } from "lucide-react"
import { useState } from "react"
import { useTranslation } from "react-i18next"

export interface UserOrgFilterValue {
    userDepartment: string
    userCompany: string
    userOffice: string
}

interface UserOrgOptions {
    departments: string[]
    companies: string[]
    offices: string[]
}

const emptyOptions = (): UserOrgOptions => ({ departments: [], companies: [], offices: [] })

interface UserOrgMoreFiltersProps {
    value: UserOrgFilterValue
    onChange: (patch: Partial<UserOrgFilterValue>) => void
}

export function UserOrgMoreFilters({ value, onChange }: UserOrgMoreFiltersProps) {
    const { t } = useTranslation()
    const [open, setOpen] = useState(false)
    const [active, setActive] = useState<keyof UserOrgFilterValue | "">("")
    const [options, setOptions] = useState<UserOrgOptions>(emptyOptions)
    const [loaded, setLoaded] = useState(false)
    const selectedCount = [value.userDepartment, value.userCompany, value.userOffice].filter(Boolean).length

    const handleOpenChange = (next: boolean) => {
        setOpen(next)
        if (!next) setActive("")
        if (!next || loaded) return
        void getAuditUserOrgOptionsApi().then((data) => {
            setOptions({
                departments: data?.departments || [],
                companies: data?.companies || [],
                offices: data?.offices || [],
            })
        }).catch(() => {
            setOptions(emptyOptions())
        }).finally(() => {
            setLoaded(true)
        })
    }

    const fields: Array<{ key: keyof UserOrgFilterValue, label: string, names: string[] }> = [
        { key: "userDepartment", label: t("log.userDepartment"), names: options.departments },
        { key: "userCompany", label: t("log.userCompany"), names: options.companies },
        { key: "userOffice", label: t("log.userOffice"), names: options.offices },
    ]

    return (
        <Popover open={open} onOpenChange={handleOpenChange}>
            <PopoverTrigger asChild>
                <Button type="button" variant="outline" aria-label={t("log.moreFilters")} aria-expanded={open}>
                    <span>{t("log.moreFilters")}</span>
                    {selectedCount > 0 && <span aria-hidden className="ml-1 rounded-full bg-primary/10 px-1.5 text-xs text-primary">{selectedCount}</span>}
                    <ChevronDown className="ml-1 h-4 w-4" aria-hidden />
                </Button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-[320px] p-3" onOpenAutoFocus={(event) => event.preventDefault()}>
                <div className="mb-3 text-sm font-medium">{t("log.moreFilters")}</div>
                <div className="flex flex-col gap-3">
                    {fields.map((field) => (
                        <OrgDropdown
                            key={field.key}
                            label={field.label}
                            value={value[field.key] || ""}
                            names={field.names}
                            open={active === field.key}
                            searchPlaceholder={t("log.userOrgFilterSearch")}
                            emptyText={t("log.userOrgFilterEmpty")}
                            onToggle={() => setActive((current) => current === field.key ? "" : field.key)}
                            onChange={(next) => {
                                onChange({ [field.key]: next })
                                setActive("")
                            }}
                        />
                    ))}
                </div>
                <div className="mt-3 flex justify-end border-t pt-3">
                    <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => onChange({ userDepartment: "", userCompany: "", userOffice: "" })}
                    >
                        {t("log.userOrgFilterClear")}
                    </Button>
                </div>
            </PopoverContent>
        </Popover>
    )
}

function OrgDropdown({
    label,
    value,
    names,
    open,
    searchPlaceholder,
    emptyText,
    onToggle,
    onChange,
}: {
    label: string
    value: string
    names: string[]
    open: boolean
    searchPlaceholder: string
    emptyText: string
    onToggle: () => void
    onChange: (value: string) => void
}) {
    const [keyword, setKeyword] = useState("")
    const visible = keyword.trim()
        ? names.filter((name) => name.toLowerCase().includes(keyword.trim().toLowerCase()))
        : names

    return (
        <div className="flex flex-col gap-1.5 text-xs text-muted-foreground">
            <span>{label}</span>
            <button
                type="button"
                className="flex h-9 w-full items-center justify-between rounded-md border bg-search-input px-3 text-sm text-foreground"
                aria-label={label}
                aria-expanded={open}
                onClick={() => {
                    setKeyword("")
                    onToggle()
                }}
            >
                <span className="truncate">{value || label}</span>
                <ChevronDown className="h-4 w-4 shrink-0 opacity-80" aria-hidden />
            </button>
            {open && (
                <div className="rounded-md border bg-popover p-2">
                    <input
                        className="mb-2 h-8 w-full rounded-md border bg-background px-2 text-sm text-foreground outline-none"
                        aria-label={searchPlaceholder}
                        placeholder={searchPlaceholder}
                        value={keyword}
                        onChange={(event) => setKeyword(event.target.value)}
                    />
                    <div className="max-h-40 overflow-auto" role="listbox" aria-label={label}>
                        {visible.map((name) => (
                            <button
                                key={name}
                                type="button"
                                role="option"
                                aria-selected={value === name}
                                className={`flex w-full rounded-sm px-2 py-1.5 text-left text-sm text-foreground hover:bg-[#EBF0FF] dark:hover:bg-gray-700 ${value === name ? "bg-[#EBF0FF] dark:bg-gray-700" : ""}`}
                                onClick={() => onChange(value === name ? "" : name)}
                            >
                                {name}
                            </button>
                        ))}
                        {!visible.length && <div className="px-2 py-3 text-xs">{emptyText}</div>}
                    </div>
                </div>
            )}
        </div>
    )
}
