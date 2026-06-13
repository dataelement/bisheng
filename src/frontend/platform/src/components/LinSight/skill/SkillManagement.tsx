// F035 (PRD §4.5): tenant custom skill management section, mounted in the
// merged 日常 tab of 构建-工作台配置 (replaces the legacy SOP manual library).
// List shows display_name only — the skill ID stays detail-level; no
// migration-source badge (FR-5.1).
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { SearchInput } from "@/components/bs-ui/input";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import {
    Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue,
} from "@/components/bs-ui/select";
import { Switch } from "@/components/bs-ui/switch";
import {
    Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/bs-ui/table";
import { toast } from "@/components/bs-ui/toast/use-toast";
import { SkillBrief, SkillDetail, skillApi } from "@/controllers/API/linsight";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { ChevronRight, Plus, Sparkles, Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { SkillDetailSheet } from "./SkillDetailSheet";
import { SkillFormDrawer } from "./SkillFormDrawer";
import { SkillUploadDialog } from "./SkillUploadDialog";
import { getSkillErrorMessage } from "./skillErrors";

const PAGE_SIZE = 10;

export function SkillManagement({ scopeVersion = 0 }: { scopeVersion?: number }) {
    const { t } = useTranslation();
    const [skills, setSkills] = useState<SkillBrief[]>([]);
    const [total, setTotal] = useState(0);
    const [page, setPage] = useState(1);
    const [keyword, setKeyword] = useState('');
    const [statusFilter, setStatusFilter] = useState<'all' | 'enabled' | 'disabled'>('all');
    const [loading, setLoading] = useState(false);

    const [uploadOpen, setUploadOpen] = useState(false);
    const [formOpen, setFormOpen] = useState(false);
    const [editing, setEditing] = useState<SkillDetail | null>(null);
    const [detail, setDetail] = useState<SkillDetail | null>(null);

    const loadSkills = useCallback((targetPage: number, kw: string, status: typeof statusFilter) => {
        setLoading(true);
        skillApi.getSkillList({
            keyword: kw || undefined,
            enabled: status === 'all' ? undefined : status === 'enabled',
            page: targetPage,
            page_size: PAGE_SIZE,
        }).then(res => {
            setSkills(res.data);
            setTotal(res.total);
        }).finally(() => setLoading(false));
    }, []);

    useEffect(() => {
        loadSkills(page, keyword, statusFilter);
        // eslint-disable-next-line react-hooks/exhaustive-deps -- keyword is applied via handleSearch
    }, [page, statusFilter, scopeVersion]);

    const refresh = () => loadSkills(page, keyword, statusFilter);

    const searchTimerRef = useRef<ReturnType<typeof setTimeout>>();
    const handleSearch = (value: string) => {
        setKeyword(value);
        clearTimeout(searchTimerRef.current);
        searchTimerRef.current = setTimeout(() => {
            setPage(1);
            loadSkills(1, value, statusFilter);
        }, 300);
    };

    const handleToggle = (skill: SkillBrief, enabled: boolean) => {
        // Optimistic flip: takes effect immediately in the end-user picker (FR-5.9).
        setSkills(prev => prev.map(s => s.name === skill.name ? { ...s, enabled } : s));
        captureAndAlertRequestErrorHoc(skillApi.setSkillStatus(skill.name, enabled)).then(res => {
            if (res) {
                toast({ variant: 'success', description: enabled ? t('skillManage.enabledToast') : t('skillManage.disabledToast') });
            } else {
                setSkills(prev => prev.map(s => s.name === skill.name ? { ...s, enabled: !enabled } : s));
            }
        });
    };

    const handleDelete = (skill: SkillBrief) => {
        bsConfirm({
            desc: t('skillManage.deleteConfirm', { name: skill.display_name }),
            okTxt: t('skillManage.deleteAction'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(skillApi.deleteSkill(skill.name)).then(res => {
                    if (res) {
                        toast({ variant: 'success', description: t('skillManage.deleted') });
                        refresh();
                    }
                });
                next();
            },
        });
    };

    const openDetail = (skill: SkillBrief) => {
        skillApi.getSkillDetail(skill.name)
            .then(setDetail)
            .catch(err => toast({ variant: 'error', description: getSkillErrorMessage(err, t) }));
    };

    // From the detail sheet: close it first, then open the next overlay once the
    // exit animation finishes — stacking two Radix modals traps focus/clicks.
    const handleEditFromDetail = (d: SkillDetail) => {
        setDetail(null);
        setTimeout(() => { setEditing(d); setFormOpen(true); }, 200);
    };

    const handleDeleteFromDetail = (d: SkillDetail) => {
        setDetail(null);
        setTimeout(() => handleDelete(d), 200);
    };

    const handleCreate = () => {
        setEditing(null);
        setFormOpen(true);
    };

    const emptyHint = keyword || statusFilter !== 'all' ? t('skillManage.noMatch') : t('skillManage.empty');

    return (
        <div className="mb-6">
            <p className="text-lg font-bold mb-1">{t('skillManage.title')}</p>
            <p className="text-sm text-muted-foreground mb-3">{t('skillManage.subtitle')}</p>
            <div className="flex items-center gap-2 mb-3">
                <SearchInput
                    placeholder={t('skillManage.searchPlaceholder')}
                    className="w-64"
                    onChange={(e) => handleSearch(e.target.value)}
                />
                <Select value={statusFilter} onValueChange={(v) => { setStatusFilter(v as typeof statusFilter); setPage(1); }}>
                    <SelectTrigger className="w-28">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectGroup>
                            <SelectItem value="all">{t('skillManage.statusAll')}</SelectItem>
                            <SelectItem value="enabled">{t('skillManage.statusEnabled')}</SelectItem>
                            <SelectItem value="disabled">{t('skillManage.statusDisabled')}</SelectItem>
                        </SelectGroup>
                    </SelectContent>
                </Select>
                <div className="ml-auto flex gap-2">
                    <Button variant="outline" onClick={() => setUploadOpen(true)}>
                        <Upload className="size-4 mr-1.5" />{t('skillManage.upload')}
                    </Button>
                    <Button onClick={handleCreate}>
                        <Plus className="size-4 mr-1.5" />{t('skillManage.create')}
                    </Button>
                </div>
            </div>
            <div className="border rounded-md">
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-56">{t('skillManage.columns.displayName')}</TableHead>
                            <TableHead>{t('skillManage.columns.description')}</TableHead>
                            <TableHead className="w-24">{t('skillManage.columns.status')}</TableHead>
                            <TableHead className="w-40">{t('skillManage.columns.createTime')}</TableHead>
                            <TableHead className="w-8" />
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {skills.length === 0 && !loading && (
                            <TableRow>
                                <TableCell colSpan={5} className="text-center text-muted-foreground py-10">{emptyHint}</TableCell>
                            </TableRow>
                        )}
                        {skills.map(skill => (
                            <TableRow
                                key={skill.id}
                                className="group cursor-pointer hover:bg-primary/5"
                                onClick={() => openDetail(skill)}
                            >
                                <TableCell className="font-medium">
                                    <div className="flex items-center gap-3 min-w-0">
                                        <div className="size-[34px] shrink-0 rounded-[9px] grid place-items-center text-primary bg-gradient-to-br from-[#EEF2FF] to-[#E2EAFF]">
                                            <Sparkles className="size-[17px]" />
                                        </div>
                                        <span className="truncate min-w-0">{skill.display_name}</span>
                                    </div>
                                </TableCell>
                                <TableCell className="max-w-[320px] truncate" title={skill.description}>{skill.description}</TableCell>
                                {/* Quick toggle stays inline; stop the click from opening the detail sheet */}
                                <TableCell onClick={(e) => e.stopPropagation()}>
                                    <Switch checked={skill.enabled} onCheckedChange={(checked) => handleToggle(skill, checked)} />
                                </TableCell>
                                <TableCell className="text-muted-foreground text-xs">
                                    {skill.create_time?.replace('T', ' ').slice(0, 16) ?? '--'}
                                </TableCell>
                                {/* chevron nudges right + turns brand-blue on row hover — a quiet "clickable" cue */}
                                <TableCell className="text-[#C4C9D4] transition-all duration-150 group-hover:translate-x-0.5 group-hover:text-primary">
                                    <ChevronRight className="size-4" />
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>
            {total > 0 && (
                <div className="flex items-center justify-between mt-2">
                    <span className="text-xs text-muted-foreground">{t('skillManage.count', { count: total })}</span>
                    {total > PAGE_SIZE && (
                        <AutoPagination page={page} pageSize={PAGE_SIZE} total={total} onChange={(p) => setPage(p)} />
                    )}
                </div>
            )}
            <SkillUploadDialog open={uploadOpen} onOpenChange={setUploadOpen} onUploaded={refresh} />
            <SkillFormDrawer open={formOpen} editing={editing} onOpenChange={setFormOpen} onSaved={refresh} />
            <SkillDetailSheet
                detail={detail}
                onOpenChange={(open) => !open && setDetail(null)}
                onEdit={handleEditFromDetail}
                onDelete={handleDeleteFromDetail}
            />
        </div>
    );
}
