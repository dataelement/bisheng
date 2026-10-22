import UsersSelect from '@/components/bs-comp/selectComponent/Users'
import type { DepartmentUserOption } from '@/components/bs-comp/selectComponent/DepartmentUsersSelect'
import { Button } from '@/components/bs-ui/button'
import { Checkbox } from '@/components/bs-ui/checkBox'
import { Input } from '@/components/bs-ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/bs-ui/select'
import { getCreditRules, getPolicySubjects, saveCreditRule, type CreditRule, type PolicySubject, type PolicySubjectOption } from '@/controllers/API/dshUnified'
import { getDshRequestErrorKey } from '@/utils/dshRequestError'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

export function CreditRulesView() {
    const { t } = useTranslation()
    const [rules, setRules] = useState<CreditRule[]>([])
    const [options, setOptions] = useState<PolicySubjectOption[]>([])
    const [subject, setSubject] = useState<PolicySubject | null>(null)
    const [kind, setKind] = useState<PolicySubject['kind']>('DEPARTMENT')
    const [users, setUsers] = useState<DepartmentUserOption[]>([])
    const [credits, setCredits] = useState('500')
    const [version, setVersion] = useState(0)
    const [enabled, setEnabled] = useState(true)
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
    const select = (next: PolicySubject | null) => {
        setSubject(next)
        const rule = rules.find(row => row.subject_type === next?.kind && row.subject_id === next?.id)
        setVersion(rule?.version ?? 0)
        setCredits(rule?.monthly_credits ?? '500')
        setEnabled(rule?.enabled ?? true)
    }
    const save = async () => {
        if (!subject || pending) return
        setPending(true); setError(null)
        try {
            const saved = await saveCreditRule(subject, { version, enabled, monthly_credits: credits })
            const name = subject.kind === 'USER' ? users[0]?.label : options.find(item => item.kind === subject.kind && item.id === subject.id)?.name
            setRules(rows => [...rows.filter(row => row.subject_type !== subject.kind || row.subject_id !== subject.id), { ...saved, name }])
            setVersion(saved.version)
        } catch (reason) { setError(getDshRequestErrorKey(reason) ?? 'dsh.unavailable') }
        finally { setPending(false) }
    }
    return <section className="space-y-4 rounded-lg border bg-background p-4">
        <div className="flex items-center justify-between">
            <h2 className="font-semibold">{t('dsh.unified.credits')}</h2>
            <Button variant="outline" disabled={pending} onClick={() => { select(null); setRevision(old => old + 1) }}>{t('dsh.refresh')}</Button>
        </div>
        <p className="text-sm text-muted-foreground">{t('dsh.unified.ruleHelp')}</p>
        {error && <p role="alert">{t(error)}</p>}
        {!loaded ? <p role="status">{t('dsh.loading')}</p> : <>
            <fieldset disabled={pending} className="flex flex-wrap items-end gap-3">
                <div className="space-y-1 text-sm">
                    <label htmlFor="credit-rule-kind">{t('dsh.unified.scope')}</label>
                    <Select disabled={pending} value={kind} onValueChange={value => {
                        if (value === 'DEPARTMENT' || value === 'ROLE' || value === 'USER') {
                            setKind(value); select(null); setUsers([])
                        }
                    }}>
                        <SelectTrigger id="credit-rule-kind" className="w-28"><SelectValue /></SelectTrigger>
                        <SelectContent>
                            {(['DEPARTMENT', 'ROLE', 'USER'] as const).map(value => <SelectItem key={value} value={value}>{t(`dsh.unified.${value}`)}</SelectItem>)}
                        </SelectContent>
                    </Select>
                </div>
                {kind === 'USER' ? <UsersSelect value={users} disabled={pending} onChange={next => {
                    setUsers(next); select(next[0] ? { kind: 'USER', id: Number(next[0].value) } : null)
                }} /> : <Select key={kind} disabled={pending} value={subject ? String(subject.id) : ''} onValueChange={value => select({ kind, id: Number(value) })}>
                    <SelectTrigger aria-label={t('dsh.unified.selectSubject')} className="w-56"><SelectValue placeholder={t('dsh.unified.selectSubject')} /></SelectTrigger>
                    <SelectContent>
                        {options.filter(item => item.kind === kind).map(item => <SelectItem key={item.id} value={String(item.id)}>
                            <span style={{ paddingLeft: item.depth * 16 }}>{item.name}</span>
                        </SelectItem>)}
                    </SelectContent>
                </Select>}
                <label className="space-y-1 text-sm">{t('dsh.unified.monthlyCredits')}
                    <Input aria-label={t('dsh.unified.monthlyCredits')} className="w-36" inputMode="decimal" value={credits} onChange={event => setCredits(event.target.value)} />
                </label>
                <label className="flex items-center gap-2 py-2 text-sm"><Checkbox disabled={pending} checked={enabled} onCheckedChange={checked => setEnabled(checked === true)} />{t('dsh.unified.enabled')}</label>
                <Button disabled={!subject || !/^(0|[1-9][0-9]{0,12})(\.[0-9]{1,6})?$/.test(credits) || pending} onClick={save}>{t(pending ? 'dsh.unified.saving' : 'dsh.unified.save')}</Button>
            </fieldset>
            <table className="w-full text-left text-sm">
                <thead><tr className="border-b"><th className="py-2">{t('dsh.unified.scope')}</th><th>{t('dsh.unified.monthlyCredits')}</th><th>{t('dsh.unified.enabled')}</th><th /></tr></thead>
                <tbody>{rules.map(rule => <tr className="border-b" key={`${rule.subject_type}:${rule.subject_id}`}>
                    <td className="py-2">{t(`dsh.unified.${rule.subject_type}`)} · {rule.name ?? rule.subject_id}</td>
                    <td>{rule.monthly_credits}</td><td>{t(rule.enabled ? 'dsh.unified.yes' : 'dsh.unified.no')}</td>
                    <td><Button variant="ghost" disabled={pending} onClick={() => {
                        setKind(rule.subject_type); setUsers(rule.subject_type === 'USER' ? [{ value: rule.subject_id, label: rule.name || String(rule.subject_id) }] : [])
                        select({ kind: rule.subject_type, id: rule.subject_id })
                    }}>{t('dsh.unified.edit')}</Button></td>
                </tr>)}</tbody>
            </table>
        </>}
    </section>
}
