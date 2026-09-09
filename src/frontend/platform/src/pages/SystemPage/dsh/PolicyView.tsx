import { Button } from '@/components/bs-ui/button'
import { Input } from '@/components/bs-ui/input'
import { getDshPolicy } from '@/controllers/API/dsh'
import { getUsersApi } from '@/controllers/API/user'
import type { User } from '@/types/api/user'
import type { DshOperation, DshOperationRef, DshPolicy } from '@/types/dsh'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { DshPager } from './common'
import { PolicyEditor } from './PolicyEditor'
import { UsageSummary } from './UsageSummary'

interface PolicyViewProps {
    onOperation: (ref: DshOperationRef, result?: DshOperation) => void
    operations: Record<string, DshOperation>
}
export function PolicyView({ onOperation, operations }: PolicyViewProps) {
    const { t } = useTranslation()
    const [keyword, setKeyword] = useState('')
    const [page, setPage] = useState(1)
    const [users, setUsers] = useState<{ data: User[]; total: number } | null>(
        null,
    )
    const [selected, setSelected] = useState<User | null>(null)
    const [policy, setPolicy] = useState<DshPolicy | null>(null)
    const [error, setError] = useState(false)
    const [usersError, setUsersError] = useState(false)
    const [revision, setRevision] = useState(0)
    useEffect(() => {
        const abort = new AbortController()
        setUsers(null)
        setUsersError(false)
        const timer = window.setTimeout(() => {
            getUsersApi(
                {
                    name: keyword,
                    page,
                    pageSize: 20,
                    simple: true,
                    withDepartmentPath: true,
                },
                { signal: abort.signal },
            )
                .then((value) => {
                    if (!abort.signal.aborted) setUsers(value)
                })
                .catch(() => {
                    if (!abort.signal.aborted) setUsersError(true)
                })
        }, 300)
        return () => {
            abort.abort()
            window.clearTimeout(timer)
        }
    }, [keyword, page])
    useEffect(() => {
        if (!selected) return
        const abort = new AbortController()
        setPolicy(null)
        setError(false)
        getDshPolicy(String(selected.user_id), undefined, abort.signal)
            .then((value) => {
                if (!abort.signal.aborted) {
                    setPolicy(value)
                }
            })
            .catch(() => {
                if (!abort.signal.aborted) setError(true)
            })
        return () => abort.abort()
    }, [selected, revision])
    return (
        <section className="space-y-4">
            <p className="text-sm text-muted-foreground">
                {t('dsh.policyScope')}
            </p>
            <Input
                className="max-w-sm"
                aria-label={t('dsh.searchUsers')}
                placeholder={t('dsh.searchUsers')}
                value={keyword}
                onChange={(event) => {
                    setKeyword(event.target.value)
                    setPage(1)
                }}
            />
            {!users ? (
                <p role="status">
                    {t(usersError ? 'dsh.unavailable' : 'dsh.loading')}
                </p>
            ) : (
                <div className="flex flex-wrap gap-2">
                    {users.data.map((item) => (
                        <Button
                            key={item.user_id}
                            variant={
                                selected?.user_id === item.user_id
                                    ? 'default'
                                    : 'outline'
                            }
                            onClick={() => setSelected(item)}
                        >
                            {item.user_name}{' '}
                            {item.department_path
                                ? `· ${item.department_path}`
                                : ''}
                        </Button>
                    ))}
                    {!users.data.length && <p>{t('dsh.empty')}</p>}
                </div>
            )}
            <DshPager
                previous={page > 1}
                next={!!users && page * 20 < users.total}
                loading={!users && !usersError}
                onPrevious={() => setPage((old) => old - 1)}
                onNext={() => setPage((old) => old + 1)}
            />
            {selected && (
                <>
                    <h3 className="font-semibold">{selected.user_name}</h3>
                    {!policy ? (
                        <p role="status">
                            {t(error ? 'dsh.unavailable' : 'dsh.loading')}
                        </p>
                    ) : (
                        <>
                            <UsageSummary
                                usage={policy.usage}
                                lastCall={policy.last_call}
                                lastCallSource={policy.last_call_source}
                                modelNames={Object.fromEntries(
                                    policy.available_models.map((model) => [
                                        String(model.id),
                                        model.name,
                                    ]),
                                )}
                            />
                            <PolicyEditor
                                key={`${selected.user_id}:${revision}`}
                                userId={String(selected.user_id)}
                                tenantId={String(policy.tenant_id)}
                                policy={policy}
                                operations={operations}
                                onOperation={onOperation}
                                onReload={() => setRevision((old) => old + 1)}
                            />
                        </>
                    )}
                </>
            )}
        </section>
    )
}
