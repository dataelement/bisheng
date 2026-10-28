import UsersSelect from '@/components/bs-comp/selectComponent/Users'
import type { DepartmentUserOption } from '@/components/bs-comp/selectComponent/DepartmentUsersSelect'
import { Button } from "@bisheng/ui";
import { Checkbox } from "@bisheng/ui";
import { Input } from "@bisheng/ui";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/bs-ui/select'
import { Tabs } from "@bisheng/ui"
import { getCreditRules, getPolicySubjects, saveCreditRule, type CreditRule, type PolicySubject, type PolicySubjectOption } from '@/controllers/API/dshUnified'
import { getDshRequestErrorKey } from '@/utils/dshRequestError'
import { MAX_MONTHLY_CREDITS, isValidMonthlyCredits } from '@/utils/dshCreditAmount'
import { useEffect, useId, useState } from 'react'
import { useTranslation } from 'react-i18next'

type CreditDraft = {
    subject: PolicySubject | null
    name: string
    version: number
    credits: string
    enabled: boolean
    isNew: boolean
}

export function CreditRulesView() {
    const { t } = useTranslation()
    const creditHintId = useId()
    const [rules, setRules] = useState<CreditRule[]>([])
    const [options, setOptions] = useState<PolicySubjectOption[]>([])
    const [kind, setKind] = useState<PolicySubject['kind']>('USER')
    const [draft, setDraft] = useState<CreditDraft | null>(null)
    const [users, setUsers] = useState<DepartmentUserOption[]>([])
    const [pending, setPending] = useState(false)
    const [loaded, setLoaded] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [revision, setRevision] = useState(0)
    useEffect(() => {
        const abort = new AbortController()
        setLoaded(false)
        setError(null)
        Promise.all([getCreditRules(abort.signal), getPolicySubjects(abort.signal)])
            .then(([rows, subjects]) => { if (!abort.signal.aborted) { setRules(rows); setOptions(subjects); setLoaded(true) } })
            .catch(() => { if (!abort.signal.aborted) setError('dsh.unavailable') })
        return () => abort.abort()
    }, [revision])
    const cancel = () => { setDraft(null); setUsers([]); setError(null) }
    const select = (subject: PolicySubject | null, name: string) => {
        const rule = rules.find(row => row.subject_type === subject?.kind && row.subject_id === subject?.id)
        setDraft(old => old && ({ ...old, subject, name, version: rule?.version ?? 0,
            credits: rule?.monthly_credits ?? old.credits, enabled: rule?.enabled ?? old.enabled }))
    }
    const save = async () => {
        if (!draft?.subject || pending || !isValidMonthlyCredits(draft.credits)) return
        setPending(true); setError(null)
        try {
            const saved = await saveCreditRule(draft.subject, {
                version: draft.version, enabled: draft.enabled, monthly_credits: draft.credits,
            })
            setRules(rows => {
                const next = { ...saved, name: draft.name }
                const exists = rows.some(row => row.subject_type === saved.subject_type && row.subject_id === saved.subject_id)
                return exists ? rows.map(row => row.subject_type === saved.subject_type && row.subject_id === saved.subject_id ? next : row) : [...rows, next]
            })
            cancel()
        } catch (reason) { setError(getDshRequestErrorKey(reason) ?? 'dsh.unavailable') }
        finally { setPending(false) }
    }
    const visibleRules = rules.filter(rule => rule.subject_type === kind)
    const validCredits = !!draft && isValidMonthlyCredits(draft.credits)
    const creditInput = draft && <div className="space-y-1">
        <Input aria-label={t('dsh.unified.monthlyCredits')} className="w-40" inputMode="decimal" disabled={pending}
            aria-invalid={!validCredits} aria-describedby={creditHintId}
            value={draft.credits} onChange={event => setDraft({ ...draft, credits: event.target.value })} />
        <p id={creditHintId} role={!validCredits ? 'alert' : undefined}
            className={validCredits ? 'text-xs text-muted-foreground' : 'text-xs text-destructive'}>
            {t('dsh.unified.creditRangeHint', { max: MAX_MONTHLY_CREDITS })}
        </p>
    </div>
    const enabledInput = draft && <Checkbox aria-label={t('dsh.unified.enabled')} disabled={pending} checked={draft.enabled}
        onCheckedChange={checked => setDraft({ ...draft, enabled: checked === true })} />
    const actions = <div className="flex items-center justify-end gap-2">
        <Button disabled={!draft?.subject || !validCredits || pending} onClick={save}>{t(pending ? 'dsh.unified.saving' : 'dsh.unified.save')}</Button>
        <Button variant="text" disabled={pending} onClick={cancel}>{t('dsh.unified.cancel')}</Button>
    </div>
    return <section className="space-y-4">
        <div className="flex items-center justify-between gap-4">
            <Tabs activeKey={kind} onChange={value => {
              if (value === 'USER' || value === 'DEPARTMENT' || value === 'ROLE') { setKind(value); cancel(); }
            }} aria-label={t('dsh.unified.scope')}
              items={(['USER', 'DEPARTMENT', 'ROLE'] as const).map(value => ({
                key: value, disabled: pending, label: t(value === 'USER' ? 'dsh.unified.userTab' : `dsh.unified.${value}`),
              }))} />
            <div className="flex gap-2">
                <Button variant="outlined" disabled={pending} onClick={() => { cancel(); setRevision(old => old + 1) }}>{t('dsh.refresh')}</Button>
                <Button disabled={pending || !loaded} onClick={() => {
                    setError(null); setUsers([]); setDraft({ subject: null, name: '', version: 0, credits: '500', enabled: true, isNew: true })
                }}>{t('dsh.unified.addCredits')}</Button>
            </div>
        </div>
        <p className="text-sm text-muted-foreground">{t('dsh.unified.ruleHelp')}</p>
        {error && <p role="alert">{t(error)}</p>}
        {!loaded ? <p role="status">{t('dsh.loading')}</p> : <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
                <thead><tr className="border-b">
                    <th className="py-3 font-medium">{t(kind === 'USER' ? 'dsh.unified.userTab' : `dsh.unified.${kind}`)}</th>
                    <th className="w-56 font-medium">{t('dsh.unified.monthlyCredits')}</th>
                    <th className="w-32 font-medium">{t('dsh.unified.enabled')}</th>
                    <th className="w-40" />
                </tr></thead>
                <tbody>
                    {draft?.isNew && <tr className="border-b">
                        <td className="py-3 pr-4">
                            {kind === 'USER' ? <UsersSelect value={users} disabled={pending} lockedValues={visibleRules.map(rule => rule.subject_id)} onChange={(next: DepartmentUserOption[]) => {
                                setUsers(next); select(next[0] ? { kind: 'USER', id: Number(next[0].value) } : null, next[0]?.label ?? '')
                            }} /> : <Select disabled={pending} value={draft.subject ? String(draft.subject.id) : ''} onValueChange={value => {
                                const option = options.find(item => item.kind === kind && item.id === Number(value))
                                select({ kind, id: Number(value) }, option?.name ?? value)
                            }}>
                                <SelectTrigger aria-label={t('dsh.unified.selectSubject')} className="w-64"><SelectValue placeholder={t('dsh.unified.selectSubject')} /></SelectTrigger>
                                <SelectContent>
                                    {options.filter(item => item.kind === kind && !visibleRules.some(rule => rule.subject_id === item.id)).map(item => <SelectItem key={item.id} value={String(item.id)}>
                                        <span style={{ paddingLeft: item.depth * 16 }}>{item.name}</span>
                                    </SelectItem>)}
                                </SelectContent>
                            </Select>}
                        </td>
                        <td>{creditInput}</td><td>{enabledInput}</td><td>{actions}</td>
                    </tr>}
                    {visibleRules.map(rule => {
                        const editing = draft && !draft.isNew && draft.subject?.kind === rule.subject_type && draft.subject.id === rule.subject_id
                        return <tr className="border-b" key={`${rule.subject_type}:${rule.subject_id}`}>
                            <td className="py-4 pr-4">{rule.name ?? rule.subject_id}</td>
                            <td>{editing ? creditInput : rule.monthly_credits}</td>
                            <td>{editing ? enabledInput : t(rule.enabled ? 'dsh.unified.yes' : 'dsh.unified.no')}</td>
                            <td>{editing ? actions : <div className="flex justify-end"><Button variant="text" disabled={pending} onClick={() => {
                                setError(null); setDraft({ subject: { kind: rule.subject_type, id: rule.subject_id }, name: rule.name ?? String(rule.subject_id),
                                    credits: rule.monthly_credits, enabled: rule.enabled, version: rule.version, isNew: false })
                            }}>{t('dsh.unified.edit')}</Button></div>}</td>
                        </tr>
                    })}
                    {visibleRules.length === 0 && !draft?.isNew && <tr><td colSpan={4} className="py-12 text-center text-muted-foreground">{t('dsh.unified.emptyCredits')}</td></tr>}
                </tbody>
            </table>
        </div>}
    </section>
}
