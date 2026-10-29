import { permissionDialogClassName, PermissionSubjectIdentity, PermissionSubjectTabs } from '@/components/bs-comp/permission/PermissionSubjectLayout'
import { SubjectSearchDepartment } from '@/components/bs-comp/permission/SubjectSearchDepartment'
import { SubjectSearchUser } from '@/components/bs-comp/permission/SubjectSearchUser'
import { SubjectSearchUserGroup } from '@/components/bs-comp/permission/SubjectSearchUserGroup'
import type { SelectedSubject, SubjectType } from '@/components/bs-comp/permission/types'
import { Button } from '@/components/bs-ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/bs-ui/dialog'
import { Tabs, TabsContent } from '@/components/bs-ui/tabs'
import type { ModelVisibility, PolicySubjectOption } from '@/controllers/API/dshUnified'
import { getUsersApi } from '@/controllers/API/user'
import { Search, Trash2 } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { modelDepartmentSource, modelSubjectKinds, toModelSubject } from './modelPermissionSubjects'

interface ModelPermissionRosterProps {
    model: { id: number; name: string }
    value: ModelVisibility
    options: PolicySubjectOption[]
    disabled: boolean
    onChange: (value: ModelVisibility) => void
}

export function ModelPermissionRoster({ model, value, options, disabled, onChange }: ModelPermissionRosterProps) {
    const { t } = useTranslation()
    const permission = (key: string) => t(key, { ns: 'permission' })
    const grantContentRef = useRef<HTMLDivElement>(null)
    const [tab, setTab] = useState<SubjectType>('user')
    const [grantTab, setGrantTab] = useState<SubjectType>('user')
    const [search, setSearch] = useState('')
    const [adding, setAdding] = useState(false)
    const [selection, setSelection] = useState<SelectedSubject[]>([])
    const source = useMemo(() => modelDepartmentSource(options, String(model.id)), [options, model.id])
    const tabs = [
        { value: 'user' as const, label: permission('subject.user') },
        { value: 'department' as const, label: permission('subject.department') },
        { value: 'user_group' as const, label: t('dsh.unified.role') },
    ]
    const searchLabel = (type: SubjectType) => t({ user: 'dsh.unified.searchUser', department: 'dsh.unified.searchDepartment', user_group: 'dsh.unified.searchRole' }[type])
    const subjectName = (kind: string, id: number) => kind === 'USER'
        ? value.users?.find(user => user.value === id)?.label ?? `#${id}`
        : options.find(option => option.kind === kind && option.id === id)?.name ?? `#${id}`
    const rows = value.subjects.filter(subject => subject.kind === modelSubjectKinds[tab]
        && subjectName(subject.kind, subject.id).toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))
    const alreadySelected = (type: SubjectType) => value.subjects.filter(subject => subject.kind === modelSubjectKinds[type]).map(subject => subject.id)
    const add = () => {
        const subjects = [...value.subjects]
        for (const selected of selection.map(toModelSubject)) {
            if (!subjects.some(subject => subject.kind === selected.kind && subject.id === selected.id)) subjects.push(selected)
        }
        const users = [...(value.users ?? [])]
        for (const selected of selection.filter(subject => subject.type === 'user')) {
            if (!users.some(user => user.value === selected.id)) users.push({ value: selected.id, label: selected.name })
        }
        onChange({ ...value, subjects, users })
        setAdding(false)
        setSelection([])
    }
    return <>
        <Tabs value={tab} onValueChange={next => { setTab(next as SubjectType); setSearch('') }} className="flex min-h-0 flex-1 flex-col">
            <div className="flex items-center justify-between gap-3">
                <PermissionSubjectTabs tabs={tabs} />
                <Button type="button" disabled={disabled} className="h-8 shrink-0 rounded-[6px] px-3 text-[14px] leading-[22px]"
                    onClick={() => { setGrantTab(tab); setSelection([]); setAdding(true) }}>{permission('dialog.tabGrant')}</Button>
            </div>
            <TabsContent value={tab} className="mt-3 flex min-h-0 flex-1 flex-col gap-3 overflow-hidden p-0">
                <div className="relative shrink-0">
                    <Search aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[#999999]" />
                    <input type="search" aria-label={searchLabel(tab)} placeholder={searchLabel(tab)} value={search} onChange={event => setSearch(event.target.value)}
                        className="h-9 w-full rounded-[6px] border border-[#EBECF0] bg-white pl-9 pr-3 text-sm outline-none focus:border-[#C9CDD4]" />
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto">
                    {rows.map(subject => <article key={subject.id} className="flex min-h-[58px] items-center gap-4 border-b border-[#F2F3F5] py-3 last:border-b-0">
                        <PermissionSubjectIdentity type={tab} name={subjectName(subject.kind, subject.id)}
                            metadata={subject.kind === 'DEPARTMENT' ? permission('source.includeChildren') : undefined} />
                        <span className="text-sm text-muted-foreground">{t('dsh.unified.canUse')}</span>
                        <Button type="button" variant="ghost" size="icon" disabled={disabled}
                            aria-label={`${permission('grant.remove')} ${subjectName(subject.kind, subject.id)}`}
                            onClick={() => onChange({ ...value, subjects: value.subjects.filter(item => item.kind !== subject.kind || item.id !== subject.id) })}>
                            <Trash2 aria-hidden="true" className="size-4 text-muted-foreground" />
                        </Button>
                    </article>)}
                    {!rows.length && <p className="py-10 text-center text-sm text-muted-foreground">{permission(search ? 'empty.searchResults' : 'list.emptyForSubject')}</p>}
                </div>
            </TabsContent>
        </Tabs>
        <Dialog open={adding} onOpenChange={setAdding}>
            <DialogContent ref={grantContentRef} className={`${permissionDialogClassName} p-5`} onOpenAutoFocus={event => {
                event.preventDefault()
                requestAnimationFrame(() => grantContentRef.current?.focus({ preventScroll: true }))
            }}>
                <DialogHeader className="shrink-0"><DialogTitle>{permission('dialog.tabGrant')} - {model.name}</DialogTitle>
                    <DialogDescription className="sr-only">{t('dsh.unified.visibilityHelp')}</DialogDescription></DialogHeader>
                <div className="mt-4 flex items-center gap-3">
                    <PermissionSubjectTabs tabs={tabs} value={grantTab} onChange={setGrantTab} />
                    {grantTab === 'department' && <span className="text-sm text-muted-foreground">{permission('source.includeChildren')}</span>}
                </div>
                <div className="mt-4 min-h-0 flex-1 overflow-hidden">
                    {grantTab === 'user' && <SubjectSearchUser value={selection} onChange={setSelection} scopeKey={`model-users:${model.id}`}
                        searchPlaceholder={searchLabel('user')} disabledIds={alreadySelected('user')} fetchPage={async (keyword, page, signal) => {
                            const result = await getUsersApi({ name: keyword, page, pageSize: 50, withDepartmentPath: true }, { signal })
                            return { total: result.total, data: result.data.map(user => ({ ...user, user_id: Number(user.user_id) })) }
                        }} />}
                    {grantTab === 'department' && <SubjectSearchDepartment value={selection} onChange={setSelection}
                        searchPlaceholder={searchLabel('department')} dataSource={source} includeChildren showIncludeChildrenToggle={false} disabledIds={alreadySelected('department')} />}
                    {grantTab === 'user_group' && <SubjectSearchUserGroup value={selection} onChange={setSelection}
                        showBusinessId={false} scopeKey={`model-roles:${model.id}`} searchPlaceholder={searchLabel('user_group')} disabledIds={alreadySelected('user_group')}
                        fetchPage={async (keyword, page) => {
                            const matches = options.filter(option => option.kind === 'ROLE' && option.name.toLocaleLowerCase().includes(keyword.toLocaleLowerCase()))
                            return { data: matches.slice((page - 1) * 50, page * 50), total: matches.length }
                        }} />}
                </div>
                <div className="mt-4 flex shrink-0 items-center justify-between border-t pt-4">
                    <p className="text-sm text-muted-foreground" aria-live="polite">{t('dsh.unified.selectedSubjects', { count: selection.length })}</p>
                    <div className="flex gap-2"><Button variant="outline" onClick={() => setAdding(false)}>{t('dsh.unified.cancel')}</Button>
                        <Button disabled={!selection.length} onClick={add}>{t('dsh.unified.addToDraft')}</Button></div>
                </div>
            </DialogContent>
        </Dialog>
    </>
}
