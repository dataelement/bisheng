import { bsConfirm } from '@/components/bs-ui/alertDialog/useConfirm'
import { Button, LoadButton } from '@/components/bs-ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/bs-ui/dialog'
import { Input } from '@/components/bs-ui/input'
import { useToast } from '@/components/bs-ui/toast/use-toast'
import { getDshModelSubjects, getDshModelUserPermissions, saveDshSubjectPolicy } from '@/controllers/API/dsh'
import { getDshRequestErrorKey } from '@/utils/dshRequestError'
import type { DshModelUserPermission, DshSubjectPolicyInventory, DshSubjectPolicy } from '@/types/dsh'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { DepartmentAccessTree } from './DepartmentAccessTree'
import { useUserPolicyDrafts, withinSaveDeadline } from './useUserPolicyDrafts'
import { policyKey, type PolicyDrafts } from './SubjectPolicyControls'

export type DshAccessModel = { id: number; name: string }
export const quotaValid = (value: string) => /^\d*$/.test(value) && Number.isSafeInteger(Number(value))

export function ModelAccessDialog({ model, onClose }: { model: DshAccessModel | null; onClose: () => void }) {
    const { t } = useTranslation()
    const { message } = useToast()
    const [inventory, setInventory] = useState<DshSubjectPolicyInventory | null>(null)
    const [drafts, setDrafts] = useState<PolicyDrafts>({})
    const [query, setQuery] = useState('')
    const [loadError, setLoadError] = useState(false)
    const [saveError, setSaveError] = useState<string | null>(null)
    const [saving, setSaving] = useState(false)
    const [refresh, setRefresh] = useState(0)
    const [membersVersion, setMembersVersion] = useState(0)
    const [savedRevision, setSavedRevision] = useState(0)
    const busy = useRef(false)
    const modelId = model?.id
    const reloadUser = useCallback(
        async (user: DshModelUserPermission) => {
            if (!modelId) throw new Error('Model context unavailable')
            let cursor: string | undefined
            const visited = new Set<string>()
            do {
                const page = await getDshModelUserPermissions(modelId, {
                    keyword: String(user.user_id),
                    limit: 50,
                    cursor,
                })
                const item = page.items.find((row) => row.user_id === user.user_id)
                if (item) return item
                cursor = page.has_more ? (page.next_cursor ?? undefined) : undefined
                if (cursor && visited.has(cursor)) break
                if (cursor) visited.add(cursor)
            } while (cursor)
            throw new Error('User permission unavailable')
        },
        [modelId],
    )
    const users = useUserPolicyDrafts(modelId, reloadUser)

    useEffect(() => {
        setDrafts({})
        setQuery('')
        setSaveError(null)
    }, [modelId])
    useEffect(() => {
        if (!modelId) return
        const abort = new AbortController()
        setInventory(null)
        setLoadError(false)
        getDshModelSubjects(modelId, abort.signal)
            .then((value) => {
                if (!abort.signal.aborted) setInventory(value)
            })
            .catch(() => {
                if (!abort.signal.aborted) setLoadError(true)
            })
        return () => abort.abort()
    }, [modelId, refresh])

    const departments = inventory?.departments ?? []
    const dirty = departments.filter((item) => {
        const draft = drafts[policyKey(item)]
        return (
            draft &&
            (!quotaValid(draft.limit) ||
                Number(draft.limit) !== (item.enabled ? item.monthly_token_limit : 0))
        )
    })
    const hasChanges = dirty.length > 0 || users.hasChanges
    const canSave = hasChanges || users.hasPending || Object.keys(drafts).length > 0
    const valid = users.valid && dirty.every((item) => quotaValid(drafts[policyKey(item)].limit))
    const changeDepartment = (item: DshSubjectPolicy, value: string) => {
        setSaveError(null)
        setDrafts((current) => ({
            ...current,
            [policyKey(item)]: { limit: value, enabled: Number(value) > 0 },
        }))
    }
    const close = () => {
        if (busy.current) return
        if (hasChanges || users.hasPending)
            bsConfirm({
                title: t('dsh.discardPolicyEdits'),
                desc: t('dsh.discardPolicyEditsHelp'),
                okTxt: t('dsh.discardEdits'),
                onOk(next) {
                    onClose()
                    next()
                },
            })
        else onClose()
    }
    async function save() {
        if (!modelId || !inventory || busy.current || !valid || !canSave) return
        busy.current = true
        setSaving(true)
        setSaveError(null)
        let complete = true
        try {
            // Each successful item advances independently and remains committed on retry.
            if (!(await users.save(inventory.tenant_id))) complete = false
            for (const item of dirty) {
                const limit = Number(drafts[policyKey(item)].limit)
                const value = await withinSaveDeadline(
                    saveDshSubjectPolicy(modelId, 'DEPARTMENT', item.subject_id, inventory.tenant_id, {
                        expected_version: item.version,
                        enabled: limit > 0,
                        monthly_token_limit: limit,
                    }),
                )
                setInventory((current) =>
                    current
                        ? {
                              ...current,
                              departments: current.departments.map((row) =>
                                  row.subject_id === item.subject_id
                                      ? { ...row, ...value, subject_type: 'DEPARTMENT' as const }
                                      : row,
                              ),
                          }
                        : current,
                )
                setDrafts((current) => {
                    const next = { ...current }
                    delete next[policyKey(item)]
                    return next
                })
            }
            setMembersVersion((value) => value + 1)
            if (complete) {
                setDrafts({})
                setSavedRevision((value) => value + 1)
            }
            setSaveError(complete ? null : 'dsh.policySaveFailed')
            message({
                variant: complete ? 'success' : 'error',
                description: t(complete ? 'dsh.policySaved' : 'dsh.policySaveFailed'),
            })
        } catch (error) {
            const errorKey = getDshRequestErrorKey(error) ?? 'dsh.policySaveFailed'
            setSaveError(errorKey)
            setMembersVersion((value) => value + 1)
            message({ variant: 'error', description: t(errorKey) })
        } finally {
            busy.current = false
            setSaving(false)
        }
    }
    async function reload() {
        if (busy.current || !modelId) return
        busy.current = true
        setSaving(true)
        try {
            await users.refresh()
            setInventory(await withinSaveDeadline(getDshModelSubjects(modelId)))
            setMembersVersion((value) => value + 1)
            setSaveError(null)
        } catch (error) {
            setSaveError(getDshRequestErrorKey(error) ?? 'dsh.policySaveFailed')
        } finally {
            busy.current = false
            setSaving(false)
        }
    }
    return (
        <Dialog
            open={!!model}
            onOpenChange={(open) => {
                if (!open) close()
            }}
        >
            <DialogContent
                aria-describedby={undefined}
                className="flex h-[88vh] max-h-[calc(100vh-64px)] min-h-0 flex-col overflow-hidden sm:max-w-6xl"
            >
                <DialogHeader className="shrink-0">
                    <DialogTitle className="break-words pr-8">{model?.name}</DialogTitle>
                </DialogHeader>
                {!inventory || !modelId ? (
                    <div className="py-6">
                        <p role={loadError ? 'alert' : 'status'}>
                            {t(loadError ? 'dsh.unavailable' : 'dsh.loading')}
                        </p>
                        {loadError && (
                            <Button onClick={() => setRefresh((value) => value + 1)}>
                                {t('dsh.refresh')}
                            </Button>
                        )}
                    </div>
                ) : (
                    <>
                        <div className="flex shrink-0 justify-end gap-2">
                            <Input
                                boxClassName="w-72"
                                aria-label={t('dsh.searchUsername')}
                                placeholder={t('dsh.searchUsername')}
                                value={query}
                                disabled={saving}
                                onChange={(event) => setQuery(event.target.value)}
                            />
                            <LoadButton
                                loading={saving}
                                disabled={!canSave || !valid}
                                onClick={save}
                            >
                                {t(saving ? 'dsh.savingPolicies' : 'save')}
                            </LoadButton>
                        </div>
                        {saveError && (
                            <div className="flex items-center justify-end gap-2 text-sm">
                                <span role="alert" className="text-destructive">
                                    {t(saveError)}
                                </span>
                                <Button size="sm" variant="outline" disabled={saving} onClick={reload}>
                                    {t('dsh.refresh')}
                                </Button>
                            </div>
                        )}
                        <div className="min-h-0 flex-1 overflow-auto overscroll-contain rounded-lg border">
                            <DepartmentAccessTree
                                tenantId={inventory.tenant_id}
                                key={modelId}
                                modelId={modelId}
                                items={departments}
                                drafts={drafts}
                                query={query}
                                onQueryClear={() => setQuery('')}
                                users={users}
                                saving={saving}
                                refresh={membersVersion}
                                savedRevision={savedRevision}
                                onDepartmentChange={changeDepartment}
                            />
                        </div>
                    </>
                )}
            </DialogContent>
        </Dialog>
    )
}
