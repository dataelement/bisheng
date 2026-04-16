import UsersSelect from "@/components/bs-comp/selectComponent/Users";
import { Button } from "@/components/bs-ui/button";
import { Label } from "@/components/bs-ui/label";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { getGroupFlowsApi, saveGroupApi } from "@/controllers/API/pro";
import {
    createUserGroupV2,
    getUserGroupMembersV2,
    syncUserGroupMembersV2,
    updateUserGroupV2,
    UserGroupMemberRow,
    UserGroupV2,
} from "@/controllers/API/userGroups";
import { useTable } from "@/util/hook";
import { CircleHelp } from "lucide-react";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Input, SearchInput } from "../../../components/bs-ui/input";

const enum LimitType {
    LIMITED = 'limited',
    UNLIMITED = 'unlimited'
}

function FlowRadio({ limit, onChange }) {
    const { t } = useTranslation()
    const [status, setStatus] = useState(LimitType.UNLIMITED)
    const [limitState, setLimitState] = useState<any>(limit)
    const limitRef = useRef(0)

    const handleCommit = (type: LimitType, value: string = '0') => {
        if (value === '') return
        const valueNum = parseInt(value)
        if (valueNum < 0 || valueNum > 9999) return
        setStatus(type)
        setLimitState(value)
        onChange(Number(value))
        limitRef.current = Number(value)
    }
    useEffect(() => {
        setStatus(limit ? LimitType.LIMITED : LimitType.UNLIMITED)
        setLimitState(limit)
        limitRef.current = limit
    }, [limit])

    return <div>
        <RadioGroup className="flex space-x-2 h-[20px] items-center" value={status}
            onValueChange={(value: LimitType) => handleCommit(value, value === LimitType.LIMITED ? '10' : '0')}>
            <div>
                <Label className="flex justify-center">
                    <RadioGroupItem className="mr-2" value={LimitType.UNLIMITED} />{t('system.unlimited')}
                </Label>
            </div>
            <div>
                <Label className="flex justify-center">
                    <RadioGroupItem className="mr-2" value={LimitType.LIMITED} />{t('system.limit')}
                </Label>
            </div>
            {status === LimitType.LIMITED && <div className="mt-[-3px] flex items-center">
                <Label className="whitespace-nowrap">{t('system.maximum')}</Label>
                <Input
                    type="number"
                    value={limitState}
                    className="inline h-5 w-[70px] font-medium"
                    onChange={(e) => handleCommit(LimitType.LIMITED, e.target.value)}
                    onBlur={(e) => {
                        if (e.target.value === '') {
                            e.target.value = limitRef.current + ''
                        }
                    }}
                />
                <Label className="min-w-[100px]">{t('system.perMinute')}</Label>
            </div>}
        </RadioGroup>
    </div>
}

function FlowControl({ groupId, type, onChange }) {
    const { t } = useTranslation()
    const map = {
        3: { name: t('build.assistantName'), label: t('system.AssistantFlowCtrl'), placeholder: t('system.assistantName') },
        2: { name: t('skills.skillName'), label: t('system.SkillFlowCtrl'), placeholder: t('skills.skillName') },
        5: { name: t('build.workFlowName'), label: t('system.flowCtrl'), placeholder: t('build.workFlowName') },
    }
    const { name, label, placeholder } = map[type]
    const { page, pageSize, data, total, setPage, search, refreshData } = useTable({ pageSize: 10 }, (params) =>
        getGroupFlowsApi(params.page, params.pageSize, type, groupId, params.keyword)
    )

    const itemsRef = useRef([])
    const handleChange = (value, id) => {
        const item = itemsRef.current.find(item => item.resource_id === id)
        if (item) {
            item.resource_limit = value
        } else {
            itemsRef.current.push({
                resource_id: id,
                group_id: groupId,
                resource_limit: value
            })
        }
        refreshData((item) => item.id === id, { limit: value })
        onChange(itemsRef.current)
    }

    const searchEndRef = useRef(false)
    const handleSearch = (e) => {
        searchEndRef.current = true
        search(e.target.value)
    }

    if (!searchEndRef.current && !data.length) return null

    return <>
        <div className="flex items-center mb-4 justify-between">
            <div className="flex items-center space-x-2">
                <p className="text-xl font-bold">{label}</p>
                <TooltipProvider>
                    <Tooltip>
                        <TooltipTrigger>
                            <CircleHelp className="w-4 h-4" />
                        </TooltipTrigger>
                        <TooltipContent>
                            <p>{t('system.iconHover')}</p>
                        </TooltipContent>
                    </Tooltip>
                </TooltipProvider>
            </div>
            <SearchInput placeholder={placeholder} onChange={handleSearch} />
        </div>
        <div className="rounded-[5px]">
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[150px]">{name}</TableHead>
                        <TableHead className="w-[100px]">{t('system.createdBy')}</TableHead>
                        <TableHead className="w-[380px]">{t('system.flowCtrlStrategy')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {data.map((i: any) => (<TableRow key={i.id}>
                        <TableCell className="break-all">{i.name}</TableCell>
                        <TableCell className="break-all">{i.user_name}</TableCell>
                        <TableCell className="pt-4">
                            <FlowRadio limit={i.limit} onChange={(val) => handleChange(val, i.id)}></FlowRadio>
                        </TableCell>
                    </TableRow>))}
                </TableBody>
            </Table>
            <AutoPagination className="m-0 mt-4 w-auto justify-end"
                page={page} pageSize={pageSize} total={total}
                onChange={setPage}
            />
        </div>
    </>
}

type EditProps = {
    data: UserGroupV2 | Record<string, never>
    onBeforeChange: (name: string) => UserGroupV2 | undefined
    onChange: (flag?: boolean) => void | Promise<void>
}

/** MultiSelect 与接口可能混用 string/number，统一为数字再参与 Set 比较，避免保存时 diff 错误。 */
function uid(v: unknown): number {
    const n = Number(v)
    return Number.isFinite(n) ? n : 0
}

export default function EditUserGroup({ data, onBeforeChange, onChange }: EditProps) {
    const { t } = useTranslation()
    const { toast } = useToast()
    const { appConfig } = useContext(locationContext)
    const { user } = useContext(userContext)

    const [form, setForm] = useState({
        groupName: '',
        groupLimit: 0,
        visibility: 'public' as 'public' | 'private',
        assistant: [],
        skill: [],
        workFlows: []
    })

    const [members, setMembers] = useState<UserGroupMemberRow[]>([])
    const [memberPick, setMemberPick] = useState<{ label: string; value: number }[]>([])

    const loadMembers = async (groupId: number, creatorUserId?: number | null) => {
        const res = await getUserGroupMembersV2(groupId)
        const rows = res?.data ?? []
        setMembers(rows)
        const creator = creatorUserId != null ? uid(creatorUserId) : null
        const pickRows = rows.filter(
            (r) => creator == null || uid(r.user_id) !== creator,
        )
        setMemberPick(
            pickRows.map((r) => ({ label: r.user_name, value: uid(r.user_id) })),
        )
    }

    const handleSave = async () => {
        if (!form.groupName) {
            setForm({ ...form, groupName: (data as UserGroupV2).group_name || '' })
            toast({ title: t('prompt'), description: t('system.groupNameRequired'), variant: 'error' });
            return
        }
        if (form.groupName.length > 30) {
            setForm({ ...form, groupName: (data as UserGroupV2).group_name || '' })
            toast({ title: t('prompt'), description: t('system.groupNamePrompt'), variant: 'error' });
            return
        }
        const dup = onBeforeChange(form.groupName)
        if (dup) {
            setForm({ ...form, groupName: '' })
            toast({ title: t('prompt'), description: t('system.groupNameExists'), variant: 'error' });
            return
        }

        const ugData = data as UserGroupV2
        try {
            let gid = ugData.id
            if (!gid) {
                const created = await createUserGroupV2({
                    group_name: form.groupName,
                    visibility: form.visibility,
                })
                gid = created.id
            } else {
                await updateUserGroupV2(gid, {
                    group_name: form.groupName,
                    visibility: form.visibility,
                })
            }

            const desiredIds = memberPick
                .map((m) => uid(m.value))
                .filter((id) => id > 0)
            await syncUserGroupMembersV2(gid, desiredIds)

            if (appConfig.isPro) {
                const adminLabel = ugData.id
                    ? (ugData.group_admins?.[0]?.user_name ?? ugData.create_user_name ?? '')
                    : (user?.user_name ?? '')
                const adminIdStr = ugData.id
                    ? String(ugData.group_admins?.[0]?.user_id ?? ugData.create_user ?? '')
                    : String(user?.user_id ?? '')
                await saveGroupApi({
                    ...form,
                    id: gid,
                    adminUser: adminLabel,
                    adminUserId: adminIdStr,
                })
            }

            toast({ title: t('prompt'), description: t('system.saveUserGroupSuccess'), variant: 'success' })
            await onChange(true)
        } catch (e) {
            const msg =
                e == null || e === ''
                    ? t('system.saveUserGroupFailedUnknown')
                    : typeof e === 'string'
                      ? e
                      : (e as Error)?.message || t('system.saveUserGroupFailedUnknown')
            toast({ title: t('prompt'), description: msg, variant: 'error' })
        }
    }

    useEffect(() => {
        const ug = data as UserGroupV2
        setForm((f) => ({
            ...f,
            groupName: ug.group_name || '',
            groupLimit: (ug as any).group_limit || 0,
            visibility: ug.visibility === 'private' ? 'private' : 'public',
        }))
        async function init() {
            if (ug.id) {
                await loadMembers(ug.id, ug.create_user ?? null)
            } else {
                setMembers([])
                setMemberPick([])
            }
        }
        init()
    }, [(data as UserGroupV2)?.id])

    const gid = (data as UserGroupV2).id

    const memberDisplayRows = useMemo(() => {
        const pathById = new Map<number, string>()
        for (const m of members) {
            pathById.set(uid(m.user_id), (m.department_path || '').trim() || '—')
        }
        const byId = new Map<number, { user_id: number; user_name: string; department_path: string }>()
        for (const p of memberPick) {
            const id = uid(p.value)
            if (!id) continue
            byId.set(id, {
                user_id: id,
                user_name: p.label,
                department_path: pathById.get(id) ?? '—',
            })
        }
        return [...byId.values()]
    }, [memberPick, members])

    const removeMemberFromPick = (userId: number) => {
        if (!userId) return
        setMemberPick((prev) => prev.filter((x) => uid(x.value) !== userId))
    }

    return (
        <div className="mx-auto flex h-[calc(100vh-128px)] max-w-[800px] flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto px-1 pt-4 pb-4">
        <div className="font-bold mt-4">
            <p className="text-xl mb-4">{t('system.groupName')}</p>
            <Input placeholder={t('system.userGroupName')} required value={form.groupName} onChange={(e) => setForm({ ...form, groupName: e.target.value })}></Input>
        </div>
        <div className="font-bold mt-12">
            <p className="text-xl mb-4">{t('system.groupVisibility')}</p>
            <RadioGroup className="flex flex-wrap gap-6" value={form.visibility}
                onValueChange={(v: 'public' | 'private') => setForm({ ...form, visibility: v })}>
                <Label className="flex items-center gap-2 font-normal">
                    <RadioGroupItem value="public" />{t('system.visibilityPublic')}
                </Label>
                <Label className="flex items-center gap-2 font-normal">
                    <RadioGroupItem value="private" />{t('system.visibilityPrivate')}
                </Label>
            </RadioGroup>
        </div>
        <div className="font-bold mt-12">
            <p className="text-xl mb-4">{t('system.groupCreator')}</p>
            <p className="text-sm text-muted-foreground font-normal mb-2">{t('system.groupCreatorReadonlyHint')}</p>
            <div className="rounded-md border bg-muted/30 px-4 py-3 text-sm">
                {(data as UserGroupV2).id
                    ? ((data as UserGroupV2).create_user_name?.trim()
                        || (data as UserGroupV2).group_admins?.map((a) => a.user_name).filter(Boolean).join(", ")
                        || ((data as UserGroupV2).create_user != null ? String((data as UserGroupV2).create_user) : "—"))
                    : (user?.user_name || "—")}
            </div>
        </div>

        <div className="font-bold mt-12">
            <p className="text-xl mb-4">{t('system.groupMembers')}</p>
            <p className="text-sm text-muted-foreground font-normal mb-1">{t('system.addGroupMembersHint')}</p>
            <p className="text-sm text-muted-foreground font-normal mb-3">{t('system.groupMembersRemoveHint')}</p>
            <UsersSelect
                multiple
                lockedValues={[]}
                value={memberPick}
                onChange={setMemberPick}
            />
            {!!gid && memberDisplayRows.length > 0 && (
                <div className="mt-4 max-h-96 overflow-y-auto rounded-md border">
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>{t('system.memberName')}</TableHead>
                                <TableHead>{t('system.departmentPath')}</TableHead>
                                <TableHead className="w-[100px] text-right">{t('operations')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {memberDisplayRows.map((m) => (
                                <TableRow key={m.user_id}>
                                    <TableCell>{m.user_name}</TableCell>
                                    <TableCell className="text-muted-foreground text-sm">
                                        {m.department_path}
                                    </TableCell>
                                    <TableCell className="text-right">
                                        <Button
                                            type="button"
                                            variant="link"
                                            className="h-auto p-0 text-red-500"
                                            onClick={() => removeMemberFromPick(m.user_id)}
                                        >
                                            {t('system.removeFromGroup')}
                                        </Button>
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </div>
            )}
        </div>

        {appConfig.isPro && <>
            <div className="font-bold mt-12">
                <p className="text-xl mb-4">{t('system.flowControl')}</p>
                <FlowRadio limit={form.groupLimit} onChange={(f) => setForm({ ...form, groupLimit: f })}></FlowRadio>
            </div>
            <div className="mt-12">
                <FlowControl
                    groupId={gid}
                    type={3}
                    onChange={(vals) => setForm({ ...form, assistant: vals })}
                ></FlowControl>
            </div>
            <div className="mt-12 mb-20">
                <FlowControl
                    groupId={gid}
                    type={2}
                    onChange={(vals) => setForm({ ...form, skill: vals })}
                ></FlowControl>
            </div>
            <div className="mt-12 mb-20">
                <FlowControl
                    groupId={gid}
                    type={5}
                    onChange={(vals) => setForm({ ...form, workFlows: vals })}
                ></FlowControl>
            </div>
        </>}
        </div>
        <div className="flex shrink-0 items-center justify-center gap-4 border-t bg-background-login py-3">
            <Button variant="outline" className="px-16" onClick={() => onChange()}>{t('cancel')}</Button>
            <Button className="px-16" onClick={() => { void handleSave(); }}>{t('save')}</Button>
        </div>
    </div>
    )
}
