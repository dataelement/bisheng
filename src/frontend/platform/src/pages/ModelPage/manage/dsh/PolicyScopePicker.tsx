import UsersSelect from '@/components/bs-comp/selectComponent/Users'
import type { DepartmentUserOption } from '@/components/bs-comp/selectComponent/DepartmentUsersSelect'
import { Checkbox } from "@bisheng/ui";
import type { PolicySubject, PolicySubjectOption } from '@/controllers/API/dshUnified'
import { useTranslation } from 'react-i18next'

interface PolicyScopePickerProps {
    options: PolicySubjectOption[]
    value: PolicySubject[]
    users: DepartmentUserOption[]
    onChange: (value: PolicySubject[]) => void
    onUsersChange: (users: DepartmentUserOption[]) => void
    disabled?: boolean
}

export function PolicyScopePicker({ options, value, users, onChange, onUsersChange, disabled }: PolicyScopePickerProps) {
    const { t } = useTranslation()
    const toggle = (option: PolicySubject, checked: boolean) => {
        const rest = value.filter(item => item.kind !== option.kind || item.id !== option.id)
        onChange(checked ? [...rest, { kind: option.kind, id: option.id }] : rest)
    }
    return <div className="space-y-4">
        {(['DEPARTMENT', 'ROLE'] as const).map(kind => <section key={kind}>
            <p className="mb-2 text-sm font-medium">{t(`dsh.unified.${kind}`)}</p>
            <div className="max-h-40 space-y-2 overflow-auto rounded-md border p-3">
                {options.filter(item => item.kind === kind).map(item => <label
                    key={`${kind}:${item.id}`} className="flex items-center gap-2 text-sm"
                    style={{ paddingLeft: item.depth * 16 }}
                >
                    <Checkbox disabled={disabled}
                        checked={value.some(selected => selected.kind === kind && selected.id === item.id)}
                        onCheckedChange={checked => toggle(item, checked === true)} />
                    {item.name}
                </label>)}
            </div>
        </section>)}
        <section>
            <p className="mb-2 text-sm font-medium">{t('dsh.unified.USER')}</p>
            <UsersSelect multiple disabled={disabled} value={users} onChange={next => {
                onUsersChange(next)
                onChange([...value.filter(item => item.kind !== 'USER'), ...next.map(item => ({
                    kind: 'USER' as const, id: item.value,
                }))])
            }} />
        </section>
    </div>
}
